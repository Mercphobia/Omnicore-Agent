# OmniCore — Multi-Language Architecture
## "Python thinks. Rust executes. Go networks. TypeScript delivers."

```
┌─────────────────────────────────────────────────────────┐
│                    OMNICORE v4                          │
│              UNIVERSAL AGENT PLATFORM                    │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  🐍 PYTHON (core — 70%)                                  │
│  ┌──────────────────────────────────────────────────┐   │
│  │ • Agent loop, reasoning, AI orchestration         │   │
│  │ • Skill system, memory, providers                 │   │
│  │ • Cybersecurity tools (pentest, exploit, auth)     │   │
│  │ • Config, plugins, API server                     │   │
│  │ • All 170 existing files                          │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
│  ⚙️  RUST (speed — 15%)                                   │
│  ┌──────────────────────────────────────────────────┐   │
│  │ • High-speed network scanner (masscan-level)       │   │
│  │ • Hash cracker (GPU-accelerated, hashcat-like)     │   │
│  │ • Binary parser (PE/ELF/Mach-O, faster than lief)  │   │
│  │ • Regex engine (hyperscan-level throughput)        │   │
│  │ • Crypto operations (AES-GCM, SHA3, Kyber)        │   │
│  │ • Memory-safe, zero-cost, single binary            │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
│  🔧 GO (network — 10%)                                   │
│  ┌──────────────────────────────────────────────────┐   │
│  │ • Lightweight agent (single 8MB binary)            │   │
│  │ • Network tools (proxy, tunnel, DNS, MITM)         │   │
│  │ • HTTP/2 + QUIC client (fastest API calls)         │   │
│  │ • Goroutine pool (100K concurrent connections)     │   │
│  │ • gRPC server (inter-agent communication)          │   │
│  │ • Cross-compile to 15 platforms                    │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
│  📦 TYPESCRIPT (delivery — 5%)                           │
│  ┌──────────────────────────────────────────────────┐   │
│  │ • NPM package: npm install omnicore-agent          │   │
│  │ • Browser SDK (Next.js, React, Vue)               │   │
│  │ • Edge functions (Cloudflare Workers, Deno)        │   │
│  │ • VS Code extension                                │   │
│  │ • Web dashboard (React + Tailwind)                 │   │
│  │ • Chat widget (embeddable, like Intercom)          │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
├─────────────────────────────────────────────────────────┤
│  COMMUNICATION: Python ↔ Rust/Go via FFI/subprocess     │
│  DISTRIBUTION: Single binary per lang + pip/npm/cargo   │
└─────────────────────────────────────────────────────────┘
```

### RUST CRATES (6)

| Crate | File | DNA | Capability |
|---|---|---|---|
| `omnicore-scan` | `rust/scanner/` | masscan + nmap | TCP/UDP scan, 10K ports/sec, banner grab |
| `omnicore-hash` | `rust/hasher/` | hashcat | GPU MD5/SHA/bcrypt/NTLM, wordlist + rules |
| `omnicore-parse` | `rust/parser/` | lief + Ghidra | PE/ELF/Mach-O parser, sections, imports, entropy |
| `omnicore-regex` | `rust/matcher/` | hyperscan | Multi-pattern matching, 1GB/s throughput |
| `omnicore-crypto` | `rust/crypto/` | ring + pqcrypto | AES-GCM, SHA3, Kyber, Dilithium, cert parsing |
| `omnicore-core` | `rust/core/` | std | Shared types, error handling, FFI bridge |

### GO PACKAGES (4)

| Package | File | DNA | Capability |
|---|---|---|---|
| `agent` | `go/agent/` | goroutine pool | Lightweight agent, 8MB binary, zero deps |
| `network` | `go/network/` | gopacket | Proxy, tunnel, DNS, MITM, packet capture |
| `httpclient` | `go/http/` | fasthttp | HTTP/2 + QUIC, 100K req/sec, retry, circuit breaker |
| `grpc` | `go/grpc/` | gRPC | Inter-agent RPC, protobuf, streaming |

### TYPESCRIPT PACKAGES (3)

| Package | File | NPM | Capability |
|---|---|---|---|
| `omnicore-agent` | `ts/sdk/` | npm | SDK: chat, tools, providers, streaming |
| `omnicore-ui` | `ts/ui/` | npm | React components: chat, dashboard, settings |
| `omnicore-vscode` | `ts/vscode/` | marketplace | VS Code extension: inline agent, code actions |

### DIRECTORY STRUCTURE

```
OmniCore/
├── python/           → all 170 existing files (core)
├── rust/
│   ├── Cargo.toml
│   ├── scanner/      → omnicore-scan
│   ├── hasher/       → omnicore-hash
│   ├── parser/       → omnicore-parse
│   ├── matcher/      → omnicore-regex
│   ├── crypto/       → omnicore-crypto
│   └── core/         → FFI bridge to Python
├── go/
│   ├── go.mod
│   ├── agent/        → lightweight agent binary
│   ├── network/      → network tools
│   ├── http/         → fast HTTP client
│   └── grpc/         → inter-agent RPC
├── ts/
│   ├── package.json
│   ├── sdk/          → npm package
│   ├── ui/           → React components
│   └── vscode/       → VS Code extension
└── Makefile           → build all targets
```

### BUILD TARGETS

```bash
make all         # Build everything
make rust        # Build Rust crates (6 binaries)
make go          # Build Go packages (4 binaries)
make ts          # Build TypeScript (npm package)
make python      # Install Python deps
make release     # Build all + package for distribution
```

### INSTALL (post-build)

```bash
# One command, all languages
curl -fsSL https://omnicore.dev/install.sh | sh

# Installs:
#   omnicore          → Python CLI (main)
#   omnicore-scan     → Rust network scanner
#   omnicore-hash     → Rust hash cracker
#   omnicore-agent    → Go lightweight agent
#   npm install omnicore-agent  → TypeScript SDK
```