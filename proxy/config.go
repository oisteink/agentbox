package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/netip"
	"os"
	"regexp"
	"strconv"
	"strings"
)

type Credential struct {
	Header      string `json:"header"`
	Env         string `json:"env"`
	Placeholder string `json:"placeholder"`
}
type Destination struct {
	Host        string       `json:"host"`
	Port        int          `json:"port"`
	IP          string       `json:"ip"`
	Credentials []Credential `json:"credentials"`
}
type Policy struct {
	Version       int           `json:"version"`
	Listen        string        `json:"listen"`
	HostAddresses []string      `json:"host_addresses"`
	Destinations  []Destination `json:"destinations"`
}

var label = regexp.MustCompile(`^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$`)
var placeholderValue = regexp.MustCompile(`^abx-[0-9a-f]{64}$`)
var tokenVariable = regexp.MustCompile(`^AGENTBOX_TOKEN_[0-9]{1,3}$`)
var forbidden = strings.Fields("0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.0.0.0/24 192.0.2.0/24 192.168.0.0/16 198.18.0.0/15 198.51.100.0/24 203.0.113.0/24 224.0.0.0/4 240.0.0.0/4")

func hostName(raw string) (string, error) {
	h := strings.TrimSuffix(strings.ToLower(raw), ".")
	if len(h) > 253 || !strings.Contains(h, ".") {
		return "", errors.New("invalid host")
	}
	if _, err := netip.ParseAddr(h); err == nil {
		return "", errors.New("IP literal denied")
	}
	for _, part := range strings.Split(h, ".") {
		if !label.MatchString(part) {
			return "", errors.New("invalid host")
		}
	}
	return h, nil
}
func authority(raw string, defaultPort int) (string, error) {
	h, p, err := net.SplitHostPort(raw)
	if err != nil {
		h = raw
		p = strconv.Itoa(defaultPort)
	}
	h, err = hostName(h)
	if err != nil {
		return "", err
	}
	n, err := strconv.Atoi(p)
	if err != nil || n != defaultPort {
		return "", errors.New("invalid port")
	}
	return net.JoinHostPort(h, p), nil
}
func publicIP(raw string, local []string) bool {
	ip, err := netip.ParseAddr(raw)
	if err != nil || !ip.Is4() || !ip.IsGlobalUnicast() {
		return false
	}
	for _, block := range forbidden {
		if netip.MustParsePrefix(block).Contains(ip) {
			return false
		}
	}
	for _, address := range local {
		if address == raw {
			return false
		}
	}
	return true
}
func authHeader(raw string) bool {
	switch normalizedHeader(raw) {
	case "authorization", "x-api-key", "context7-api-key":
		return true
	}
	return false
}

// Some upstream frameworks map both underscores and hyphens to the same key.
func normalizedHeader(raw string) string {
	return strings.ReplaceAll(strings.ToLower(raw), "_", "-")
}
func validToken(s string) bool {
	if len(s) == 0 || len(s) > 16384 {
		return false
	}
	for _, c := range []byte(s) {
		if c < 32 || c == 127 {
			return false
		}
	}
	return true
}
func loadPolicy(path string) (Policy, error) {
	var p Policy
	b, err := os.ReadFile(path)
	if err != nil || len(b) > 262144 {
		return p, errors.New("policy unavailable")
	}
	d := json.NewDecoder(bytes.NewReader(b))
	d.DisallowUnknownFields()
	if err = d.Decode(&p); err != nil {
		return p, errors.New("invalid policy")
	}
	if err = d.Decode(new(any)); err != io.EOF {
		return p, errors.New("invalid policy suffix")
	}
	if err = p.validate(); err != nil {
		return p, err
	}
	return p, nil
}
func (p Policy) validate() error {
	if p.Version != 3 || len(p.Destinations) > 128 {
		return errors.New("invalid policy version or size")
	}
	h, port, err := net.SplitHostPort(p.Listen)
	ip, e := netip.ParseAddr(h)
	if err != nil || e != nil || !ip.Is4() || ip.IsUnspecified() || port != "3128" {
		return errors.New("invalid listener")
	}
	for _, address := range p.HostAddresses {
		if _, err := netip.ParseAddr(address); err != nil {
			return errors.New("invalid host address")
		}
	}
	seen := map[string]bool{}
	byEnv := map[string]string{}
	byPlaceholder := map[string]string{}
	for _, d := range p.Destinations {
		h, err := hostName(d.Host)
		key := net.JoinHostPort(d.Host, strconv.Itoa(d.Port))
		if err != nil || h != d.Host || (d.Port != 80 && d.Port != 443) || !publicIP(d.IP, p.HostAddresses) || seen[key] {
			return errors.New("invalid destination")
		}
		seen[key] = true
		headers := map[string]bool{}
		for _, c := range d.Credentials {
			name := normalizedHeader(c.Header)
			if d.Port != 443 || !authHeader(name) || headers[name] || !tokenVariable.MatchString(c.Env) || (c.Placeholder != "" && !placeholderValue.MatchString(c.Placeholder)) {
				return errors.New("invalid credential rule")
			}
			if old, ok := byEnv[c.Env]; ok && old != c.Placeholder {
				return errors.New("inconsistent token placeholder")
			}
			if old, ok := byPlaceholder[c.Placeholder]; c.Placeholder != "" && ok && old != c.Env {
				return errors.New("ambiguous token placeholder")
			}
			byEnv[c.Env] = c.Placeholder
			byPlaceholder[c.Placeholder] = c.Env
			headers[name] = true
		}
	}
	return nil
}
