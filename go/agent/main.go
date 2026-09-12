// OmniCore Agent — Go lightweight agent binary.
// DNA: goroutine pool + fasthttp-level speed.
//
// Single 8MB binary, zero dependencies.
// Communicates with Python core via JSON over stdin/stdout.
// Perfect for edge devices, containers, and embedded systems.

package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"sync"
	"time"
)

// ── Types ────────────────────────────────────────────────────────────

type AgentConfig struct {
	Name     string `json:"name"`
	Version  string `json:"version"`
	Mode     string `json:"mode"` // server, cli, proxy
	Port     int    `json:"port"`
}

type AgentRequest struct {
	Action  string            `json:"action"`
	Payload map[string]any    `json:"payload"`
	Headers map[string]string `json:"headers,omitempty"`
}

type AgentResponse struct {
	Success bool              `json:"success"`
	Data    any               `json:"data,omitempty"`
	Error   string            `json:"error,omitempty"`
	Metrics AgentMetrics      `json:"metrics"`
}

type AgentMetrics struct {
	Uptime    string `json:"uptime"`
	GoRoutines int   `json:"goroutines"`
	MemoryMB  int   `json:"memory_mb"`
	NumCPU     int   `json:"num_cpu"`
}

type PortResult struct {
	Port    int    `json:"port"`
	Open    bool   `json:"open"`
	Service string `json:"service,omitempty"`
}

type HTTPResult struct {
	URL        string `json:"url"`
	StatusCode int    `json:"status_code"`
	BodySize   int    `json:"body_size"`
	DurationMs int64  `json:"duration_ms"`
}

// ── Agent ────────────────────────────────────────────────────────────

type Agent struct {
	config    AgentConfig
	startTime time.Time
	mu        sync.RWMutex
	handlers  map[string]func(AgentRequest) AgentResponse
}

func NewAgent(config AgentConfig) *Agent {
	a := &Agent{
		config:    config,
		startTime: time.Now(),
		handlers:  make(map[string]func(AgentRequest) AgentResponse),
	}
	a.registerHandlers()
	return a
}

func (a *Agent) registerHandlers() {
	a.handlers["status"] = a.handleStatus
	a.handlers["scan"] = a.handleScan
	a.handlers["http"] = a.handleHTTP
	a.handlers["exec"] = a.handleExec
	a.handlers["ping"] = a.handlePing
}

// ── Handlers ─────────────────────────────────────────────────────────

func (a *Agent) handleStatus(req AgentRequest) AgentResponse {
	var m runtime.MemStats
	runtime.ReadMemStats(&m)

	return AgentResponse{
		Success: true,
		Data: map[string]any{
			"name":      a.config.Name,
			"version":   a.config.Version,
			"mode":      a.config.Mode,
			"go_version": runtime.Version(),
			"os":         runtime.GOOS,
			"arch":       runtime.GOARCH,
		},
		Metrics: a.metrics(),
	}
}

func (a *Agent) handleScan(req AgentRequest) AgentResponse {
	host, _ := req.Payload["host"].(string)
	portsRaw, _ := req.Payload["ports"].(string)

	if host == "" {
		return AgentResponse{Success: false, Error: "host required"}
	}

	ports := parsePorts(portsRaw)
	results := make([]PortResult, 0, len(ports))
	var wg sync.WaitGroup
	sem := make(chan struct{}, 500) // Max concurrent

	for _, port := range ports {
		wg.Add(1)
		go func(p int) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()

			addr := fmt.Sprintf("%s:%d", host, p)
			conn, err := net.DialTimeout("tcp", addr, 2*time.Second)
			if err != nil {
				return
			}
			conn.Close()

			a.mu.Lock()
			results = append(results, PortResult{
				Port:    p,
				Open:    true,
				Service: detectService(p),
			})
			a.mu.Unlock()
		}(port)
	}
	wg.Wait()

	return AgentResponse{
		Success: true,
		Data:    results,
		Metrics: a.metrics(),
	}
}

func (a *Agent) handleHTTP(req AgentRequest) AgentResponse {
	url, _ := req.Payload["url"].(string)
	if url == "" {
		return AgentResponse{Success: false, Error: "url required"}
	}

	start := time.Now()
	resp, err := http.Get(url)
	duration := time.Since(start).Milliseconds()

	if err != nil {
		return AgentResponse{Success: false, Error: err.Error(), Metrics: a.metrics()}
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(io.LimitReader(resp.Body, 1024*1024)) // 1MB max

	return AgentResponse{
		Success: true,
		Data: HTTPResult{
			URL:        url,
			StatusCode: resp.StatusCode,
			BodySize:   len(body),
			DurationMs: duration,
		},
		Metrics: a.metrics(),
	}
}

func (a *Agent) handleExec(req AgentRequest) AgentResponse {
	cmd, _ := req.Payload["command"].(string)
	if cmd == "" {
		return AgentResponse{Success: false, Error: "command required"}
	}

	parts := strings.Fields(cmd)
	var c *exec.Cmd
	if len(parts) > 1 {
		c = exec.Command(parts[0], parts[1:]...)
	} else {
		c = exec.Command(parts[0])
	}

	output, err := c.CombinedOutput()
	if err != nil {
		return AgentResponse{
			Success: false,
			Error:   err.Error(),
			Data:    string(output),
			Metrics: a.metrics(),
		}
	}

	return AgentResponse{
		Success: true,
		Data:    string(output),
		Metrics: a.metrics(),
	}
}

func (a *Agent) handlePing(req AgentRequest) AgentResponse {
	return AgentResponse{
		Success: true,
		Data:    "pong",
		Metrics: a.metrics(),
	}
}

// ── Helpers ──────────────────────────────────────────────────────────

func (a *Agent) metrics() AgentMetrics {
	var m runtime.MemStats
	runtime.ReadMemStats(&m)
	return AgentMetrics{
		Uptime:    time.Since(a.startTime).Round(time.Second).String(),
		GoRoutines: runtime.NumGoroutine(),
		MemoryMB:  int(m.Alloc / 1024 / 1024),
		NumCPU:     runtime.NumCPU(),
	}
}

func parsePorts(raw string) []int {
	if raw == "" {
		return []int{22, 80, 443, 8080, 8443}
	}
	var ports []int
	for _, part := range strings.Split(raw, ",") {
		part = strings.TrimSpace(part)
		if strings.Contains(part, "-") {
			parts := strings.SplitN(part, "-", 2)
			start := parseInt(parts[0])
			end := parseInt(parts[1])
			for p := start; p <= end; p++ {
				ports = append(ports, p)
			}
		} else {
			if p := parseInt(part); p > 0 {
				ports = append(ports, p)
			}
		}
	}
	if len(ports) == 0 {
		return []int{22, 80, 443, 8080, 8443}
	}
	return ports
}

func parseInt(s string) int {
	var n int
	fmt.Sscanf(strings.TrimSpace(s), "%d", &n)
	return n
}

func detectService(port int) string {
	switch port {
	case 21: return "ftp"
	case 22: return "ssh"
	case 23: return "telnet"
	case 25, 587: return "smtp"
	case 53: return "dns"
	case 80, 8080: return "http"
	case 443, 8443: return "https"
	case 3306: return "mysql"
	case 5432: return "postgresql"
	case 6379: return "redis"
	case 27017: return "mongodb"
	default: return "unknown"
	}
}

// ── CLI / JSON-RPC ───────────────────────────────────────────────────

func runCLI(agent *Agent) {
	scanner := bufio.NewScanner(os.Stdin)
	fmt.Fprintf(os.Stderr, "OmniCore Go Agent v%s — ready (%s/%s)\n",
		agent.config.Version, runtime.GOOS, runtime.GOARCH)

	for scanner.Scan() {
		line := scanner.Text()
		if line == "" || line == "exit" || line == "quit" {
			return
		}

		var req AgentRequest
		if err := json.Unmarshal([]byte(line), &req); err != nil {
			fmt.Fprintf(os.Stderr, "error: %v\n", err)
			continue
		}

		handler, ok := agent.handlers[req.Action]
		if !ok {
			fmt.Fprintf(os.Stderr, "unknown action: %s\n", req.Action)
			continue
		}

		resp := handler(req)
		out, _ := json.Marshal(resp)
		fmt.Println(string(out))
	}
}

func runServer(agent *Agent) {
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "POST only", http.StatusMethodNotAllowed)
			return
		}

		var req AgentRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			json.NewEncoder(w).Encode(AgentResponse{Success: false, Error: err.Error()})
			return
		}

		handler, ok := agent.handlers[req.Action]
		if !ok {
			json.NewEncoder(w).Encode(AgentResponse{Success: false, Error: "unknown action: " + req.Action})
			return
		}

		resp := handler(req)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(resp)
	})

	addr := fmt.Sprintf(":%d", agent.config.Port)
	fmt.Printf("OmniCore Go Agent v%s — listening on %s\n", agent.config.Version, addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		fmt.Fprintf(os.Stderr, "server error: %v\n", err)
		os.Exit(1)
	}
}

func main() {
	config := AgentConfig{
		Name:    "omnicore-agent",
		Version: "3.0.0",
		Mode:    "cli",
		Port:    9876,
	}

	if len(os.Args) > 1 {
		switch os.Args[1] {
		case "server":
			config.Mode = "server"
		case "cli":
			config.Mode = "cli"
		case "version":
			fmt.Printf("OmniCore Go Agent v%s (%s/%s)\n", config.Version, runtime.GOOS, runtime.GOARCH)
			return
		}
	}

	agent := NewAgent(config)

	switch config.Mode {
	case "server":
		runServer(agent)
	default:
		runCLI(agent)
	}
}