package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/elazarl/goproxy"
)

type connectionBinding struct {
	target  string
	tlsSeen atomic.Bool
}
type certCache struct {
	mu      sync.Mutex
	entries map[string]*tls.Certificate
}

func (c *certCache) Fetch(h string, gen func() (*tls.Certificate, error)) (*tls.Certificate, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if cert := c.entries[h]; cert != nil {
		return cert, nil
	}
	if len(c.entries) >= 128 {
		return nil, errors.New("certificate cache full")
	}
	cert, err := gen()
	if err == nil {
		c.entries[h] = cert
	}
	return cert, err
}

// A sliding idle deadline covers hijacked CONNECT connections as well as HTTP.
type idleConn struct {
	net.Conn
	mu            sync.Mutex
	readDeadline  time.Time
	writeDeadline time.Time
}

func earlier(explicit time.Time, duration time.Duration) time.Time {
	idle := time.Now().Add(duration)
	if !explicit.IsZero() && explicit.Before(idle) {
		return explicit
	}
	return idle
}

func (c *idleConn) SetReadDeadline(t time.Time) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.readDeadline = t
	return c.Conn.SetReadDeadline(earlier(t, 120*time.Second))
}
func (c *idleConn) SetWriteDeadline(t time.Time) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.writeDeadline = t
	return c.Conn.SetWriteDeadline(earlier(t, 30*time.Second))
}
func (c *idleConn) SetDeadline(t time.Time) error {
	if err := c.SetReadDeadline(t); err != nil {
		return err
	}
	return c.SetWriteDeadline(t)
}

func (c *idleConn) Read(b []byte) (int, error) {
	c.mu.Lock()
	_ = c.Conn.SetReadDeadline(earlier(c.readDeadline, 120*time.Second))
	c.mu.Unlock()
	return c.Conn.Read(b)
}
func (c *idleConn) Write(b []byte) (int, error) {
	c.mu.Lock()
	_ = c.Conn.SetWriteDeadline(earlier(c.writeDeadline, 30*time.Second))
	c.mu.Unlock()
	return c.Conn.Write(b)
}

type limitedListener struct {
	net.Listener
	slots chan struct{}
}
type slotConn struct {
	net.Conn
	once    sync.Once
	release func()
}

func (c *slotConn) Close() error { err := c.Conn.Close(); c.once.Do(c.release); return err }
func (l *limitedListener) Accept() (net.Conn, error) {
	l.slots <- struct{}{}
	c, err := l.Listener.Accept()
	if err != nil {
		<-l.slots
		return nil, err
	}
	return &slotConn{Conn: &idleConn{Conn: c}, release: func() { <-l.slots }}, nil
}

func newProxy(p Policy, ca *tls.Certificate, roots *x509.CertPool, tokens map[string]string) (*goproxy.ProxyHttpServer, error) {
	if err := p.validate(); err != nil {
		return nil, err
	}
	destinations := map[string]Destination{}
	for _, d := range p.Destinations {
		for _, c := range d.Credentials {
			if ca == nil || (c.Placeholder != "" && !validToken(tokens[c.Env])) || (c.Placeholder == "" && tokens[c.Env] != "") {
				return nil, errors.New("missing token or CA")
			}
		}
		destinations[net.JoinHostPort(d.Host, strconv.Itoa(d.Port))] = d
	}
	proxy := goproxy.NewProxyHttpServer()
	proxy.Logger = log.New(io.Discard, "", 0) // Raw library errors can include client-controlled data.
	proxy.CertStore = &certCache{entries: map[string]*tls.Certificate{}}
	proxy.AllowHTTP2 = true
	proxy.ConnectDial = nil
	proxy.ConnectDialWithReq = nil
	proxy.Tr = &http.Transport{
		Proxy: nil, TLSClientConfig: &tls.Config{RootCAs: roots, MinVersion: tls.VersionTLS12},
		DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
			d, ok := destinations[address]
			if !ok || !publicIP(d.IP, p.HostAddresses) {
				return nil, errors.New("destination denied")
			}
			conn, err := (&net.Dialer{Timeout: 10 * time.Second}).DialContext(ctx, "tcp4", net.JoinHostPort(d.IP, strconv.Itoa(d.Port)))
			if err != nil {
				return nil, errors.New("upstream unavailable")
			}
			return &idleConn{Conn: conn}, nil
		},
		TLSHandshakeTimeout: 10 * time.Second, ResponseHeaderTimeout: 30 * time.Second,
		IdleConnTimeout: 90 * time.Second, MaxIdleConns: 64, MaxIdleConnsPerHost: 4, MaxConnsPerHost: 32,
		MaxResponseHeaderBytes: 32768, DisableCompression: true,
	}
	proxy.OnRequest().HandleConnectFunc(func(raw string, ctx *goproxy.ProxyCtx) (action *goproxy.ConnectAction, host string) {
		action = goproxy.RejectConnect
		host = raw
		defer func() {
			if recover() != nil {
				action = goproxy.RejectConnect
			}
		}()
		key, err := authority(raw, 443)
		if err != nil || ctx.Req.URL.User != nil {
			return
		}
		d, ok := destinations[key]
		if !ok {
			ctx.Resp = goproxy.NewResponse(ctx.Req, "text/plain", 403, "denied")
			return
		}
		host = key
		if len(d.Credentials) == 0 {
			return goproxy.OkConnect, key
		}
		b := &connectionBinding{target: key}
		ctx.UserData = b
		return &goproxy.ConnectAction{Action: goproxy.ConnectMitm, TLSConfig: func(host string, c *goproxy.ProxyCtx) (*tls.Config, error) {
			cfg, err := goproxy.TLSConfigFromCA(ca)(host, c)
			if err != nil {
				return nil, errors.New("local TLS unavailable")
			}
			cfg.MinVersion = tls.VersionTLS12
			cfg.GetConfigForClient = func(hello *tls.ClientHelloInfo) (*tls.Config, error) {
				h, err := hostName(hello.ServerName)
				if err != nil || h != d.Host {
					return nil, errors.New("SNI denied")
				}
				b.tlsSeen.Store(true)
				return nil, nil
			}
			return cfg, nil
		}}, key
	})
	proxy.OnRequest().DoFunc(func(r *http.Request, ctx *goproxy.ProxyCtx) (out *http.Request, resp *http.Response) {
		out = r
		resp = goproxy.NewResponse(r, "text/plain", 403, "denied")
		defer func() {
			if recover() != nil {
				out = r
				resp = goproxy.NewResponse(r, "text/plain", 503, "policy error")
			}
		}()
		// Intercepted H1 is parsed by goproxy rather than http.Server. Enforce the
		// forwarding limit here as well; the container memory limit bounds parsing.
		headerBytes := len(r.RequestURI)
		for name, values := range r.Header {
			for _, value := range values {
				headerBytes += len(name) + len(value) + 4
			}
		}
		if headerBytes > 32768 {
			return
		}
		port := 80
		if r.URL.Scheme == "https" {
			port = 443
		} else if r.URL.Scheme != "http" {
			return
		}
		key, err := authority(r.URL.Host, port)
		if err != nil || r.URL.User != nil {
			return
		}
		host, err := authority(r.Host, port)
		if err != nil || host != key {
			return
		}
		d, ok := destinations[key]
		if !ok {
			return
		}
		b, intercepted := ctx.UserData.(*connectionBinding)
		if intercepted {
			if !b.tlsSeen.Load() || port != 443 || key != b.target || len(d.Credentials) == 0 {
				return
			}
			// TRACE/TRACK can reflect injected credentials. Unknown extensions have
			// no established safety contract for credential-bearing requests.
			switch r.Method {
			case http.MethodGet, http.MethodHead, http.MethodPost, http.MethodPut,
				http.MethodPatch, http.MethodDelete, http.MethodOptions:
			default:
				return
			}
			if len(r.Trailer) > 0 || len(r.Header.Values("Trailer")) > 0 {
				return
			}
		} else if port != 80 || len(d.Credentials) != 0 {
			return
		}
		if r.Method == http.MethodConnect || r.Header.Get("Upgrade") != "" {
			return
		}
		// Remove hop-by-hop header nominations before injecting credentials.
		for _, part := range strings.Split(r.Header.Get("Connection"), ",") {
			name := strings.TrimSpace(part)
			if authHeader(name) || strings.EqualFold(name, "host") {
				return
			}
			r.Header.Del(name)
		}
		for _, c := range d.Credentials {
			count := 0
			for name, values := range r.Header {
				if normalizedHeader(name) == normalizedHeader(c.Header) {
					count += len(values)
				}
			}
			if count > 1 {
				return
			}
		}
		r.Header.Del("Connection")
		r.Header.Del("Proxy-Authorization")
		r.Header.Del("Proxy-Connection")
		r.URL.Host = key
		r.Host = key
		// Validate all replacements before mutation. The public marker carries no
		// authority: only a matching destination/header rule supplies a real token.
		replacements := make(map[string]string)
		for name, values := range r.Header {
			for _, value := range values {
				if !strings.Contains(value, "abx-") {
					continue
				}
				matched := false
				for _, c := range d.Credentials {
					if normalizedHeader(name) != normalizedHeader(c.Header) {
						continue
					}
					prefix := ""
					candidate := value
					if len(value) >= 7 && strings.EqualFold(value[:7], "Bearer ") {
						prefix, candidate = value[:7], value[7:]
					}
					if candidate == c.Placeholder {
						replacements[c.Header] = prefix + tokens[c.Env]
						matched = true
					}
				}
				if !matched {
					return
				}
			}
		}
		for header, value := range replacements {
			for name := range r.Header {
				if normalizedHeader(name) == normalizedHeader(header) {
					delete(r.Header, name)
				}
			}
			r.Header.Set(header, value)
		}
		return r, nil
	})
	proxy.OnResponse().DoFunc(func(r *http.Response, ctx *goproxy.ProxyCtx) *http.Response {
		if ctx.Error != nil || r == nil {
			r = goproxy.NewResponse(ctx.Req, "text/plain", 502, "upstream unavailable")
		}
		// No path/query, headers, token values, body or raw errors in logs.
		host := ""
		if ctx.Req != nil && ctx.Req.URL != nil {
			host = ctx.Req.URL.Hostname()
		}
		if _, err := hostName(host); err == nil {
			log.Printf("destination=%s status=%d", host, r.StatusCode)
		}
		return r
	})
	proxy.ConnectionErrHandler = func(w io.Writer, ctx *goproxy.ProxyCtx, err error) {
		_, _ = fmt.Fprint(w, "HTTP/1.1 502 Bad Gateway\r\nContent-Length: 6\r\n\r\ndenied")
	}
	return proxy, nil
}
