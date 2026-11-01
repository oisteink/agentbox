package main

import (
	"bufio"
	"context"
	"crypto/rand"
	"crypto/rsa"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

const testPlaceholder = "abx-" + "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

func testCA(t *testing.T) tls.Certificate {
	t.Helper()
	k, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	c := &x509.Certificate{SerialNumber: big.NewInt(42), Subject: pkix.Name{CommonName: "test CA"}, NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour), IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign}
	der, err := x509.CreateCertificate(rand.Reader, c, c, &k.PublicKey, k)
	if err != nil {
		t.Fatal(err)
	}
	return tls.Certificate{Certificate: [][]byte{der}, PrivateKey: k}
}

func TestInterceptPolicy(t *testing.T) {
	var calls atomic.Int64
	var lastAuth atomic.Value
	upstream := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		lastAuth.Store(r.Header.Get("Authorization"))
		if got := r.Header.Values("Authorization"); len(got) > 1 || (len(got) == 1 && got[0] != "Bearer synthetic" && got[0] != "other") {
			t.Errorf("upstream auth=%v", got)
		}
		_, _ = io.WriteString(w, "ok")
	}))
	defer upstream.Close()
	ca := testCA(t)
	roots := x509.NewCertPool()
	roots.AddCert(upstream.Certificate())
	p := Policy{Version: 3, Listen: "172.30.240.2:3128", Destinations: []Destination{{Host: "example.com", Port: 443, IP: "93.184.216.34", Credentials: []Credential{{Header: "authorization", Env: "AGENTBOX_TOKEN_0", Placeholder: testPlaceholder}}}}}
	proxy, err := newProxy(p, &ca, roots, map[string]string{"AGENTBOX_TOKEN_0": "synthetic"})
	if err != nil {
		t.Fatal(err)
	}
	// Local test transport only: production public-IP dialer is exercised in the VM.
	proxy.Tr.DialContext = func(ctx context.Context, network, address string) (net.Conn, error) {
		if address != "example.com:443" {
			t.Errorf("unexpected upstream destination %s", address)
		}
		return (&net.Dialer{}).DialContext(ctx, "tcp", upstream.Listener.Addr().String())
	}
	server := httptest.NewUnstartedServer(proxy)
	server.Listener = &limitedListener{Listener: server.Listener, slots: make(chan struct{}, 128)}
	server.Start()
	defer server.Close()
	u, _ := url.Parse(server.URL)
	clientRoots := x509.NewCertPool()
	cert, _ := x509.ParseCertificate(ca.Certificate[0])
	clientRoots.AddCert(cert)
	for _, h2 := range []bool{false, true} {
		transport := &http.Transport{Proxy: http.ProxyURL(u), TLSClientConfig: &tls.Config{RootCAs: clientRoots}, ForceAttemptHTTP2: h2}
		client := &http.Client{Transport: transport, Timeout: 5 * time.Second}
		for _, tc := range []struct {
			name   string
			auth   []string
			host   string
			status int
		}{
			{"missing", nil, "", 200}, {"single", []string{"Bearer " + testPlaceholder}, "", 200}, {"other", []string{"other"}, "", 200}, {"partial", []string{testPlaceholder[:20]}, "", 403}, {"embedded", []string{"prefix " + testPlaceholder}, "", 403}, {"repeated", []string{testPlaceholder + " " + testPlaceholder}, "", 403},
			{"duplicate", []string{"one", "two"}, "", 403}, {"wrong-host", nil, "other.example.com", 403}, {"large-header", nil, "", 403},
		} {
			before := calls.Load()
			r, _ := http.NewRequest("GET", "https://example.com/", nil)
			r.Host = tc.host
			if tc.name == "large-header" {
				r.Header.Set("User-Agent", strings.Repeat("x", 40000))
			}
			for _, v := range tc.auth {
				r.Header.Add("Authorization", v)
			}
			resp, err := client.Do(r)
			if err != nil {
				t.Fatalf("h2=%v %s: %v", h2, tc.name, err)
			}
			_, _ = io.Copy(io.Discard, resp.Body)
			resp.Body.Close()
			if resp.StatusCode != tc.status {
				t.Fatalf("h2=%v %s status=%d", h2, tc.name, resp.StatusCode)
			}
			if h2 && resp.ProtoMajor != 2 {
				t.Fatal("HTTP/2 was not exercised")
			}
			if tc.status == 200 {
				expected := ""
				if tc.name == "single" {
					expected = "Bearer synthetic"
				}
				if tc.name == "other" {
					expected = "other"
				}
				if lastAuth.Load() != expected {
					t.Fatalf("%s upstream auth=%v", tc.name, lastAuth.Load())
				}
			}
			if tc.status == 403 && calls.Load() != before {
				t.Fatal("denied request reached upstream")
			}
		}
		transport.CloseIdleConnections()
	}
	before := calls.Load()
	conn, err := net.DialTimeout("tcp", server.Listener.Addr().String(), time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(5 * time.Second))
	_, _ = io.WriteString(conn, "CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
	reader := bufio.NewReader(conn)
	for {
		line, err := reader.ReadString('\n')
		if err != nil {
			t.Fatal(err)
		}
		if line == "\r\n" {
			break
		}
	}
	// Disable only the client check, so a client-side name rejection cannot fake a pass.
	wrong := tls.Client(conn, &tls.Config{ServerName: "other.example.com", InsecureSkipVerify: true})
	if err := wrong.Handshake(); err == nil {
		t.Fatal("mismatched SNI accepted")
	}
	if calls.Load() != before {
		t.Fatal("wrong SNI reached HTTP upstream")
	}
}

func TestPolicyRejectsUnsafeInputs(t *testing.T) {
	for _, ip := range []string{"127.0.0.1", "10.0.0.1", "169.254.169.254", "100.64.0.1", "::1", "224.0.0.1", "192.0.2.1"} {
		if publicIP(ip, nil) {
			t.Errorf("allowed %s", ip)
		}
	}
	if publicIP("93.184.216.34", []string{"93.184.216.34"}) {
		t.Fatal("host address allowed")
	}
	for _, host := range []string{"127.0.0.1", "localhost", "api.example.com.evil.invalid:443", "api..com", "a/b.example"} {
		if _, err := hostName(host); err == nil {
			t.Errorf("allowed %s", host)
		}
	}
	for _, value := range []string{"", "key\nvalue", "key\x00", strings.Repeat("x", 16385)} {
		if validToken(value) {
			t.Fatal("invalid token accepted")
		}
	}
}

func TestMissingTokenDoesNotConstructProxy(t *testing.T) {
	p := Policy{Version: 3, Listen: "172.30.240.2:3128", Destinations: []Destination{{Host: "example.com", Port: 443, IP: "93.184.216.34", Credentials: []Credential{{Header: "authorization", Env: "AGENTBOX_TOKEN_0", Placeholder: testPlaceholder}}}}}
	ca := testCA(t)
	if _, err := newProxy(p, &ca, nil, nil); err == nil {
		t.Fatal("missing token accepted")
	}
}

func TestPlaceholderMappingValidation(t *testing.T) {
	base := Policy{Version: 3, Listen: "172.30.240.2:3128", Destinations: []Destination{
		{Host: "first.example.com", Port: 443, IP: "93.184.216.34", Credentials: []Credential{{Header: "Authorization", Env: "AGENTBOX_TOKEN_0", Placeholder: testPlaceholder}}},
		{Host: "second.example.com", Port: 443, IP: "93.184.216.34", Credentials: []Credential{{Header: "Authorization", Env: "AGENTBOX_TOKEN_0", Placeholder: testPlaceholder}}},
	}}
	if err := base.validate(); err != nil {
		t.Fatal(err)
	}
	c := &base.Destinations[1].Credentials[0]
	c.Env = "AGENTBOX_TOKEN_1"
	if base.validate() == nil {
		t.Fatal("same placeholder assigned to two tokens")
	}
	c.Env = "AGENTBOX_TOKEN_0"
	c.Placeholder = "abx-" + strings.Repeat("f", 64)
	if base.validate() == nil {
		t.Fatal("same token assigned to two placeholders")
	}
	c.Env = "AGENTBOX_TOKEN_1"
	if err := base.validate(); err != nil {
		t.Fatal(err)
	}
	c.Placeholder = "placeholder"
	if base.validate() == nil {
		t.Fatal("invalid placeholder accepted")
	}
	c.Placeholder = testPlaceholder
	base.Version = 1
	if base.validate() == nil {
		t.Fatal("legacy policy accepted")
	}
}

func TestMultiplePlaceholderRules(t *testing.T) {
	second := "abx-" + strings.Repeat("e", 64)
	received := make(chan http.Header, 32)
	upstream := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		received <- r.Header.Clone()
		_, _ = io.WriteString(w, "ok")
	}))
	defer upstream.Close()
	ca := testCA(t)
	roots := x509.NewCertPool()
	roots.AddCert(upstream.Certificate())
	p := Policy{Version: 3, Listen: "172.30.240.2:3128", Destinations: []Destination{{Host: "example.com", Port: 443, IP: "93.184.216.34", Credentials: []Credential{
		{Header: "Authorization", Env: "AGENTBOX_TOKEN_0", Placeholder: testPlaceholder},
		{Header: "X-API-Key", Env: "AGENTBOX_TOKEN_1", Placeholder: second},
	}}}}
	proxy, err := newProxy(p, &ca, roots, map[string]string{"AGENTBOX_TOKEN_0": "first-secret", "AGENTBOX_TOKEN_1": "second-secret"})
	if err != nil {
		t.Fatal(err)
	}
	proxy.Tr.DialContext = func(ctx context.Context, network, address string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "tcp", upstream.Listener.Addr().String())
	}
	server := httptest.NewServer(proxy)
	defer server.Close()
	u, _ := url.Parse(server.URL)
	trust := x509.NewCertPool()
	cert, _ := x509.ParseCertificate(ca.Certificate[0])
	trust.AddCert(cert)
	for _, h2 := range []bool{false, true} {
		tr := &http.Transport{Proxy: http.ProxyURL(u), TLSClientConfig: &tls.Config{RootCAs: trust}, ForceAttemptHTTP2: h2}
		client := &http.Client{Transport: tr, Timeout: 5 * time.Second}
		for _, tc := range []struct {
			name, auth, apiKey, other, wantAuth, wantKey string
			status                                       int
		}{
			{name: "bare-and-bearer", auth: testPlaceholder, apiKey: "Bearer " + second, wantAuth: "first-secret", wantKey: "Bearer second-secret", status: 200},
			{name: "bearer-case", auth: "bEaReR " + testPlaceholder, wantAuth: "bEaReR first-secret", status: 200},
			{name: "missing", status: 200},
			{name: "other", auth: "unrelated", wantAuth: "unrelated", status: 200},
			{name: "wrong-rule", auth: second, status: 403},
			{name: "wrong-header", other: testPlaceholder, status: 403},
			{name: "foreign-placeholder", auth: "abx-" + strings.Repeat("f", 64), status: 403},
		} {
			r, _ := http.NewRequest("GET", "https://example.com/", nil)
			if tc.auth != "" {
				r.Header.Set("Authorization", tc.auth)
			}
			if tc.apiKey != "" {
				r.Header.Set("X-API-Key", tc.apiKey)
			}
			if tc.other != "" {
				r.Header.Set("X-Unrelated", tc.other)
			}
			resp, err := client.Do(r)
			if err != nil {
				t.Fatalf("h2=%v %s: %v", h2, tc.name, err)
			}
			_, _ = io.Copy(io.Discard, resp.Body)
			resp.Body.Close()
			if resp.StatusCode != tc.status {
				t.Fatalf("%s status %d", tc.name, resp.StatusCode)
			}
			if h2 && resp.ProtoMajor != 2 {
				t.Fatal("HTTP/2 not exercised")
			}
			if tc.status == 200 {
				headers := <-received
				if headers.Get("Authorization") != tc.wantAuth || headers.Get("X-API-Key") != tc.wantKey {
					t.Fatalf("%s incorrect upstream mapping", tc.name)
				}
			} else {
				select {
				case <-received:
					t.Fatal("denied request reached upstream")
				default:
				}
			}
		}
		tr.CloseIdleConnections()
	}
}

func TestDisabledCredentialRules(t *testing.T) {
	p := Policy{Version: 3, Listen: "172.30.240.2:3128", Destinations: []Destination{{Host: "example.com", Port: 443, IP: "93.184.216.34", Credentials: []Credential{
		{Header: "Authorization", Env: "AGENTBOX_TOKEN_0", Placeholder: testPlaceholder},
		{Header: "X-API-Key", Env: "AGENTBOX_TOKEN_1", Placeholder: ""},
		{Header: "CONTEXT7_API_KEY", Env: "AGENTBOX_TOKEN_2", Placeholder: ""},
	}}}}
	if err := p.validate(); err != nil {
		t.Fatal(err)
	}
	ca := testCA(t)
	if _, err := newProxy(p, &ca, nil, map[string]string{"AGENTBOX_TOKEN_0": "active-secret", "AGENTBOX_TOKEN_1": "unexpected-secret"}); err == nil {
		t.Fatal("disabled rule accepted real token")
	}
	if _, err := newProxy(p, nil, nil, map[string]string{"AGENTBOX_TOKEN_0": "active-secret"}); err == nil {
		t.Fatal("disabled destination lost CA requirement")
	}
	received := make(chan http.Header, 8)
	upstream := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		received <- r.Header.Clone()
		_, _ = io.WriteString(w, "ok")
	}))
	defer upstream.Close()
	roots := x509.NewCertPool()
	roots.AddCert(upstream.Certificate())
	proxy, err := newProxy(p, &ca, roots, map[string]string{"AGENTBOX_TOKEN_0": "active-secret"})
	if err != nil {
		t.Fatal(err)
	}
	proxy.Tr.DialContext = func(ctx context.Context, network, address string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "tcp", upstream.Listener.Addr().String())
	}
	server := httptest.NewServer(proxy)
	defer server.Close()
	u, _ := url.Parse(server.URL)
	trust := x509.NewCertPool()
	cert, _ := x509.ParseCertificate(ca.Certificate[0])
	trust.AddCert(cert)
	for _, h2 := range []bool{false, true} {
		tr := &http.Transport{Proxy: http.ProxyURL(u), TLSClientConfig: &tls.Config{RootCAs: trust}, ForceAttemptHTTP2: h2}
		client := &http.Client{Transport: tr, Timeout: 5 * time.Second}
		for _, tc := range []struct {
			auth, key, contextKey, wantAuth string
			status                          int
		}{
			{status: 200},
			{auth: "Bearer " + testPlaceholder, wantAuth: "Bearer active-secret", status: 200},
			{auth: testPlaceholder, key: "own-value", contextKey: "another-value", wantAuth: "active-secret", status: 200},
			{key: testPlaceholder, status: 403},
		} {
			r, _ := http.NewRequest("GET", "https://example.com/", nil)
			if tc.auth != "" {
				r.Header.Set("Authorization", tc.auth)
			}
			if tc.key != "" {
				r.Header.Set("X-API-Key", tc.key)
			}
			if tc.contextKey != "" {
				r.Header.Set("CONTEXT7_API_KEY", tc.contextKey)
			}
			response, err := client.Do(r)
			if err != nil {
				t.Fatal(err)
			}
			_, _ = io.Copy(io.Discard, response.Body)
			response.Body.Close()
			if response.StatusCode != tc.status {
				t.Fatalf("got %d want %d", response.StatusCode, tc.status)
			}
			if h2 && response.ProtoMajor != 2 {
				t.Fatal("HTTP/2 not exercised")
			}
			if tc.status == 200 {
				headers := <-received
				if headers.Get("Authorization") != tc.wantAuth || headers.Get("X-API-Key") != tc.key || headers.Get("CONTEXT7_API_KEY") != tc.contextKey {
					t.Fatal("incorrect active/disabled mapping")
				}
			} else {
				select {
				case <-received:
					t.Fatal("denied request reached upstream")
				default:
				}
			}
		}
		tr.CloseIdleConnections()
	}
	// All-disabled destination still uses interception and needs a CA.
	p.Destinations[0].Credentials = p.Destinations[0].Credentials[1:]
	if _, err := newProxy(p, nil, nil, nil); err == nil {
		t.Fatal("all-disabled destination bypassed CA")
	}
	disabled, err := newProxy(p, &ca, roots, nil)
	if err != nil {
		t.Fatal(err)
	}
	disabled.Tr.DialContext = proxy.Tr.DialContext
	disabledServer := httptest.NewServer(disabled)
	defer disabledServer.Close()
	disabledURL, _ := url.Parse(disabledServer.URL)
	for _, h2 := range []bool{false, true} {
		// Trust only the environment CA, not the real upstream certificate.
		// A tunnel fallback would fail this positive TLS exchange.
		tr := &http.Transport{Proxy: http.ProxyURL(disabledURL), TLSClientConfig: &tls.Config{RootCAs: trust}, ForceAttemptHTTP2: h2}
		client := &http.Client{Transport: tr, Timeout: 5 * time.Second}
		response, err := client.Get("https://example.com/")
		if err != nil {
			t.Fatal(err)
		}
		_, _ = io.Copy(io.Discard, response.Body)
		response.Body.Close()
		if response.StatusCode != 200 || (h2 && response.ProtoMajor != 2) {
			t.Fatal("all-disabled request did not use intercepted TLS")
		}
		headers := <-received
		if headers.Get("Authorization") != "" || headers.Get("X-API-Key") != "" {
			t.Fatal("all-disabled destination injected a key")
		}
		tr.CloseIdleConnections()
	}
}
