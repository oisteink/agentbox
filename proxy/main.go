package main

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"log"
	"math/big"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"time"
)

const policyPath = "/run/agentbox/policy.json"

func preparePKI() error {
	private, public := "/private", "/public"
	keyPath, certPath := filepath.Join(private, "ca.key"), filepath.Join(private, "ca.pem")
	if _, err := os.Stat(certPath); errors.Is(err, os.ErrNotExist) {
		if _, err := os.Stat(keyPath); !errors.Is(err, os.ErrNotExist) {
			return errors.New("incomplete PKI")
		}
		key, err := rsa.GenerateKey(rand.Reader, 2048)
		if err != nil {
			return err
		}
		serial, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
		if err != nil {
			return err
		}
		template := &x509.Certificate{SerialNumber: serial, Subject: pkix.Name{CommonName: "Agentbox environment CA"}, NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().AddDate(2, 0, 0), IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign | x509.KeyUsageCRLSign}
		der, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
		if err != nil {
			return err
		}
		if err = os.WriteFile(keyPath, pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(key)}), 0600); err != nil {
			return err
		}
		if err = os.WriteFile(certPath, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der}), 0600); err != nil {
			return err
		}
	}
	ca, err := tls.LoadX509KeyPair(certPath, keyPath)
	if err != nil {
		return errors.New("invalid local CA")
	}
	parsed, err := x509.ParseCertificate(ca.Certificate[0])
	if err != nil || !parsed.IsCA || time.Now().After(parsed.NotAfter) {
		return errors.New("invalid or expired local CA")
	}
	cert, err := os.ReadFile(certPath)
	if err != nil {
		return err
	}
	roots, err := os.ReadFile("/etc/ssl/certs/ca-certificates.crt")
	if err != nil {
		return err
	}
	for name, value := range map[string][]byte{"ca.pem": cert, "bundle.pem": append(append(roots, '\n'), cert...)} {
		f, err := os.CreateTemp(public, ".ca-")
		if err != nil {
			return err
		}
		temporary := f.Name()
		defer os.Remove(temporary)
		if _, err = f.Write(value); err != nil {
			f.Close()
			return err
		}
		if err = f.Chmod(0644); err != nil {
			f.Close()
			return err
		}
		if err = f.Sync(); err != nil {
			f.Close()
			return err
		}
		if err = f.Close(); err != nil {
			return err
		}
		if err = os.Rename(temporary, filepath.Join(public, name)); err != nil {
			return err
		}
	}
	return nil
}

func run() error {
	if len(os.Args) != 2 {
		return errors.New("expected serve, check or pki")
	}
	if os.Args[1] == "pki" {
		return preparePKI()
	}
	p, err := loadPolicy(policyPath)
	if err != nil {
		return err
	}
	if os.Args[1] == "check" {
		client := &http.Client{Transport: &http.Transport{Proxy: nil}, Timeout: 2 * time.Second}
		response, err := client.Get("http://" + p.Listen + "/agentbox-readiness")
		if err != nil {
			return errors.New("proxy not ready")
		}
		defer response.Body.Close()
		_, _ = io.Copy(io.Discard, response.Body)
		if response.StatusCode != 403 {
			return errors.New("unexpected readiness response")
		}
		return nil
	}
	if os.Args[1] != "serve" {
		return errors.New("unknown operation")
	}
	roots, err := x509.SystemCertPool()
	if err != nil {
		return errors.New("public CA roots unavailable")
	}
	tokens := map[string]string{}
	needsCA := false
	for _, d := range p.Destinations {
		for _, c := range d.Credentials {
			tokens[c.Env] = os.Getenv(c.Env)
			needsCA = true
		}
	}
	var ca *tls.Certificate
	if needsCA {
		value, e := tls.LoadX509KeyPair("/run/agentbox/ca.pem", "/run/agentbox/ca.key")
		if e != nil {
			return errors.New("local CA unavailable")
		}
		ca = &value
	}
	proxy, err := newProxy(p, ca, roots, tokens)
	if err != nil {
		return err
	}
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !r.URL.IsAbs() && r.Method != http.MethodConnect {
			http.Error(w, "denied", 403)
			return
		}
		proxy.ServeHTTP(w, r)
	}), ReadHeaderTimeout: 10 * time.Second, MaxHeaderBytes: 32768, ErrorLog: log.New(io.Discard, "", 0)}
	listener, err := net.Listen("tcp4", p.Listen)
	if err != nil {
		return errors.New("listener unavailable")
	}
	return server.Serve(&limitedListener{Listener: listener, slots: make(chan struct{}, 128)})
}
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "agentbox proxy:", err)
		os.Exit(1)
	}
}
