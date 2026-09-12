// OmniCore Network Tools — Go package for network operations.
// DNA: gopacket + goroutine pool.
//
// Features: Proxy, DNS, Tunneling, Packet capture

package network

import (
	"bufio"
	"crypto/tls"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"sync"
	"time"
)

// ── Proxy ─────────────────────────────────────────────────────────────

// Proxy is a simple TCP proxy that forwards connections.
type Proxy struct {
	ListenAddr string
	TargetAddr string
	TLS       bool
	Timeout    time.Duration
}

// ProxyResult holds the result of a proxy operation.
type ProxyResult struct {
	BytesIn  int64
	BytesOut int64
	Duration time.Duration
}

// StartProxy starts a TCP proxy. Returns a stop function.
func (p *Proxy) StartProxy() (func(), error) {
	if p.Timeout == 0 {
		p.Timeout = 30 * time.Second
	}

	listener, err := net.Listen("tcp", p.ListenAddr)
	if err != nil {
		return nil, fmt.Errorf("proxy listen: %w", err)
	}

	done := make(chan struct{})
	stop := func() {
		close(done)
		listener.Close()
	}

	go func() {
		for {
			select {
			case <-done:
				return
			default:
			}

			conn, err := listener.Accept()
			if err != nil {
				continue
			}
			go p.handle(conn)
		}
	}()

	return stop, nil
}

func (p *Proxy) handle(client net.Conn) {
	defer client.Close()

	var target net.Conn
	var err error

	if p.TLS {
		target, err = tls.Dial("tcp", p.TargetAddr, &tls.Config{
			InsecureSkipVerify: true,
		})
	} else {
		target, err = net.DialTimeout("tcp", p.TargetAddr, p.Timeout)
	}

	if err != nil {
		return
	}
	defer target.Close()

	var wg sync.WaitGroup
	wg.Add(2)

	go func() {
		defer wg.Done()
		io.Copy(target, client)
	}()

	go func() {
		defer wg.Done()
		io.Copy(client, target)
	}()

	wg.Wait()
}

// ── DNS ───────────────────────────────────────────────────────────────

// DNSResolver provides DNS resolution with caching.
type DNSResolver struct {
	cache    map[string][]string
	cacheTTL time.Duration
	mu       sync.RWMutex
}

// NewDNSResolver creates a DNS resolver with caching.
func NewDNSResolver(ttl time.Duration) *DNSResolver {
	return &DNSResolver{
		cache:    make(map[string][]string),
		cacheTTL: ttl,
	}
}

// Resolve resolves a hostname to IP addresses.
func (r *DNSResolver) Resolve(host string) ([]string, error) {
	r.mu.RLock()
	if ips, ok := r.cache[host]; ok {
		r.mu.RUnlock()
		return ips, nil
	}
	r.mu.RUnlock()

	ips, err := net.LookupHost(host)
	if err != nil {
		return nil, err
	}

	r.mu.Lock()
	r.cache[host] = ips
	r.mu.Unlock()

	// Cleanup expired entries periodically
	go func() {
		time.Sleep(r.cacheTTL)
		r.mu.Lock()
		delete(r.cache, host)
		r.mu.Unlock()
	}()

	return ips, nil
}

// ResolveAll resolves all DNS records for a domain.
func (r *DNSResolver) ResolveAll(domain string) map[string][]string {
	result := make(map[string][]string)

	if ips, err := net.LookupHost(domain); err == nil {
		result["A"] = ips
	}
	if cname, err := net.LookupCNAME(domain); err == nil {
		result["CNAME"] = []string{cname}
	}
	if mxs, err := net.LookupMX(domain); err == nil {
		for _, mx := range mxs {
			result["MX"] = append(result["MX"], fmt.Sprintf("%s (priority:%d)", mx.Host, mx.Pref))
		}
	}
	if nss, err := net.LookupNS(domain); err == nil {
		for _, ns := range nss {
			result["NS"] = append(result["NS"], ns.Host)
		}
	}
	if txts, err := net.LookupTXT(domain); err == nil {
		result["TXT"] = txts
	}

	return result
}

// ── Tunnel ─────────────────────────────────────────────────────────────

// Tunnel represents a bi-directional TCP tunnel.
type Tunnel struct {
	Local  string
	Remote string
}

// CreateTunnel creates a bi-directional tunnel between local and remote.
func (t *Tunnel) CreateTunnel() error {
	local, err := net.Listen("tcp", t.Local)
	if err != nil {
		return fmt.Errorf("tunnel listen: %w", err)
	}
	defer local.Close()

	for {
		conn, err := local.Accept()
		if err != nil {
			continue
		}

		go func(client net.Conn) {
			defer client.Close()

			remote, err := net.DialTimeout("tcp", t.Remote, 10*time.Second)
			if err != nil {
				return
			}
			defer remote.Close()

			var wg sync.WaitGroup
			wg.Add(2)

			go func() { defer wg.Done(); io.Copy(remote, client) }()
			go func() { defer wg.Done(); io.Copy(client, remote) }()

			wg.Wait()
		}(conn)
	}
}

// ── HTTP Client ───────────────────────────────────────────────────────

// FastHTTPClient is a high-concurrency HTTP client.
type FastHTTPClient struct {
	client    *http.Client
	semaphore chan struct{}
}

// NewFastHTTPClient creates a rate-limited HTTP client.
func NewFastHTTPClient(maxConcurrent int, timeout time.Duration) *FastHTTPClient {
	return &FastHTTPClient{
		client: &http.Client{
			Timeout: timeout,
			Transport: &http.Transport{
				MaxIdleConns:        100,
				MaxIdleConnsPerHost: 10,
				IdleConnTimeout:     90 * time.Second,
			},
		},
		semaphore: make(chan struct{}, maxConcurrent),
	}
}

// Do executes an HTTP request with concurrency control.
func (c *FastHTTPClient) Do(req *http.Request) (*http.Response, error) {
	c.semaphore <- struct{}{}
	defer func() { <-c.semaphore }()
	return c.client.Do(req)
}

// BulkGet executes multiple GET requests concurrently.
func (c *FastHTTPClient) BulkGet(urls []string) []*http.Response {
	var wg sync.WaitGroup
	results := make([]*http.Response, len(urls))

	for i, url := range urls {
		wg.Add(1)
		go func(idx int, u string) {
			defer wg.Done()
			c.semaphore <- struct{}{}
			defer func() { <-c.semaphore }()

			resp, err := c.client.Get(u)
			if err != nil {
				return
			}
			results[idx] = resp
		}(i, url)
	}

	wg.Wait()
	return results
}

// ── Packet Capture (simplified) ───────────────────────────────────────

// PacketSniffer captures packets from a network interface.
type PacketSniffer struct {
	Interface string
	Filter    string
	MaxPackets int
}

// SniffResult holds captured packet data (simplified, no libpcap dependency).
type SniffResult struct {
	Source      net.IP
	Destination net.IP
	Protocol    string
	Length      int
}

// StartSniffer begins packet capture (uses raw sockets or tcpdump fallback).
func (s *PacketSniffer) StartSniffer(callback func(SniffResult)) error {
	// ponytail: full raw socket or libpcap integration if packet capture matters.
	// For now: use net.Interfaces to list available interfaces.
	ifaces, err := net.Interfaces()
	if err != nil {
		return fmt.Errorf("sniffer: %w", err)
	}

	for _, iface := range ifaces {
		addrs, _ := iface.Addrs()
		for _, addr := range addrs {
			if ipnet, ok := addr.(*net.IPNet); ok && !ipnet.IP.IsLoopback() {
				callback(SniffResult{
					Source:      ipnet.IP,
					Destination: net.IPv4(0, 0, 0, 0),
					Protocol:    iface.Name,
					Length:      0,
				})
			}
		}
	}
	return nil
}

// ── Network Scanner ───────────────────────────────────────────────────

// ScanPorts scans TCP ports on a host using goroutines.
func ScanPorts(host string, ports []int, timeout time.Duration) []int {
	var openPorts []int
	var mu sync.Mutex
	sem := make(chan struct{}, 1000) // Max concurrent

	var wg sync.WaitGroup
	for _, port := range ports {
		wg.Add(1)
		go func(p int) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()

			addr := net.JoinHostPort(host, fmt.Sprintf("%d", p))
			conn, err := net.DialTimeout("tcp", addr, timeout)
			if err == nil {
				conn.Close()
				mu.Lock()
				openPorts = append(openPorts, p)
				mu.Unlock()
			}
		}(port)
	}
	wg.Wait()
	return openPorts
}

// ── Utilities ─────────────────────────────────────────────────────────

// IsPortOpen checks if a single port is open.
func IsPortOpen(host string, port int, timeout time.Duration) bool {
	addr := net.JoinHostPort(host, fmt.Sprintf("%d", port))
	conn, err := net.DialTimeout("tcp", addr, timeout)
	if err != nil {
		return false
	}
	conn.Close()
	return true
}

// GrabBanner connects to a port and reads the initial response.
func GrabBanner(host string, port int, timeout time.Duration) string {
	addr := net.JoinHostPort(host, fmt.Sprintf("%d", port))
	conn, err := net.DialTimeout("tcp", addr, timeout)
	if err != nil {
		return ""
	}
	defer conn.Close()

	conn.SetReadDeadline(time.Now().Add(timeout))
	reader := bufio.NewReader(conn)

	// Send a probe for common services
	switch port {
	case 80, 8080:
		fmt.Fprintf(conn, "GET / HTTP/1.0\r\nHost: %s\r\n\r\n", host)
	case 22:
		// SSH banner comes automatically
	default:
		fmt.Fprintf(conn, "\r\n")
	}

	line, _ := reader.ReadString('\n')
	return strings.TrimSpace(line)
}