package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/http/httputil"
	"net/url"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestCredentialReflectionAndAmbiguity(t *testing.T) {
	const secret = "SECRET-TOKEN-security-regression"
	var calls atomic.Int64
	upstream := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		// Read trailers and reflect exactly what a TRACE/debug upstream can see.
		_, _ = io.Copy(io.Discard, r.Body)
		if r.Method == "TRACE" || r.Method == "TRACK" {
			raw, _ := httputil.DumpRequest(r, false)
			_, _ = w.Write(raw)
			return
		}
		count := 0
		for name, values := range r.Header {
			if strings.ReplaceAll(strings.ToLower(name), "_", "-") == "context7-api-key" {
				count += len(values)
			}
		}
		if count != 1 || len(r.Trailer) != 0 {
			t.Errorf("ambiguous upstream headers/trailers: %v / %v", r.Header, r.Trailer)
		}
		if got := r.Header.Get("context7_api_key"); got != secret {
			t.Errorf("wrong injected credential: %q", got)
		}
		_, _ = io.WriteString(w, "ok")
	}))
	defer upstream.Close()
	ca := testCA(t)
	roots := x509.NewCertPool()
	roots.AddCert(upstream.Certificate())
	p := Policy{Version: 3, Listen: "172.30.240.2:3128", Destinations: []Destination{{Host: "example.com", Port: 443, IP: "93.184.216.34", Credentials: []Credential{{Header: "context7_api_key", Env: "AGENTBOX_TOKEN_0", Placeholder: testPlaceholder}}}}}
	proxy, err := newProxy(p, &ca, roots, map[string]string{"AGENTBOX_TOKEN_0": secret})
	if err != nil {
		t.Fatal(err)
	}
	proxy.Tr.DialContext = func(ctx context.Context, network, address string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "tcp", upstream.Listener.Addr().String())
	}
	server := httptest.NewUnstartedServer(proxy)
	server.Listener = &limitedListener{Listener: server.Listener, slots: make(chan struct{}, 128)}
	server.Start()
	defer server.Close()
	address, _ := url.Parse(server.URL)
	trust := x509.NewCertPool()
	cert, _ := x509.ParseCertificate(ca.Certificate[0])
	trust.AddCert(cert)
	for _, h2 := range []bool{false, true} {
		transport := &http.Transport{Proxy: http.ProxyURL(address), TLSClientConfig: &tls.Config{RootCAs: trust}, ForceAttemptHTTP2: h2}
		client := &http.Client{Transport: transport, Timeout: 5 * time.Second}
		for _, tc := range []struct {
			name, method string
			headers      http.Header
			trailer      bool
			status       int
		}{
			{name: "positive", method: "POST", status: 200},
			{name: "trace", method: "TRACE", status: 403},
			{name: "track", method: "TRACK", status: 403},
			{name: "extension-method", method: "REFLECT", status: 403},
			{name: "auth-trailer", method: "POST", trailer: true, status: 403},
			{name: "single-alias", method: "POST", headers: http.Header{"Context7-Api-Key": []string{testPlaceholder}}, status: 200},
			{name: "two-aliases", method: "POST", headers: http.Header{"Context7-Api-Key": []string{"one"}, "Context7_api_key": []string{"two"}}, status: 403},
			{name: "duplicate-alias", method: "POST", headers: http.Header{"Context7-Api-Key": []string{"one", "two"}}, status: 403},
		} {
			t.Run(tc.name+map[bool]string{true: "-h2", false: "-h1"}[h2], func(t *testing.T) {
				before := calls.Load()
				r, _ := http.NewRequest(tc.method, "https://example.com/", io.NopCloser(strings.NewReader("payload")))
				r.Header.Set("Context7_api_key", testPlaceholder)
				if tc.headers != nil {
					r.Header = tc.headers.Clone()
				}
				if tc.trailer {
					r.Trailer = http.Header{"Authorization": []string{"agent-value"}}
				}
				response, err := client.Do(r)
				if err != nil {
					// H2 may reset a stream with unread request trailers instead of
					// returning the early 403. It must still send no upstream HTTP.
					if tc.status == 403 && calls.Load() == before {
						return
					}
					t.Fatal(err)
				}
				body, err := io.ReadAll(response.Body)
				response.Body.Close()
				if err != nil {
					if tc.status == 403 && response.StatusCode == 403 && calls.Load() == before && !strings.Contains(string(body), secret) {
						return
					}
					t.Fatal(err)
				}
				if response.StatusCode != tc.status || strings.Contains(string(body), secret) {
					t.Errorf("status=%d token reflected=%v", response.StatusCode, strings.Contains(string(body), secret))
				}
				if h2 && response.ProtoMajor != 2 {
					t.Fatal("HTTP/2 not exercised")
				}
				if tc.status == 403 && calls.Load() != before {
					t.Error("rejected request reached upstream")
				}
			})
		}
		transport.CloseIdleConnections()
	}
}
