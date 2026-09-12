# OMNICORE v1.0 — IMPLEMENTATION PLAN
## "All-Rounder AI Agent — On-Device, Multi-Model, Self-Improving"

---

## ARSITEKTUR REAL (bukan fantasi)

```
OmniCore/
├── core/
│   ├── engine.py          # Agent loop utama
│   ├── planner.py         # Task planning + decomposition
│   ├── memory.py          # SQLite persistent memory
│   └── persona.py         # SOUL.md identity loader
│
├── tools/
│   ├── registry.py        # Tool registration + discovery
│   ├── file_tools.py      # Read/write/patch/search files
│   ├── terminal.py        # Shell exec (gated)
│   ├── web_search.py      # Web search + scraping
│   ├── browser.py         # Playwright headless
│   ├── git_tools.py       # Git operations
│   ├── code_tools.py      # AST parsing, linting, formatting
│   └── mcp_server.py      # MCP protocol server
│
├── providers/
│   ├── base.py            # Abstract provider interface
│   ├── claude.py          # Anthropic (Claude Opus/Sonnet)
│   ├── openai.py          # OpenAI (GPT-5, GPT-4o)
│   ├── gemini.py          # Google Gemini
│   ├── deepseek.py        # DeepSeek
│   ├── local.py           # Ollama / local models
│   └── router.py          # Auto-select best model per task
│
├── memory/
│   ├── store.py           # SQLite CRUD
│   ├── vector.py          # Embedding + semantic search
│   └── context.py         # Context window management
│
├── skills/
│   ├── loader.py          # Skill discovery + loading
│   ├── self_improve.py    # Learn from execution, save patterns
│   └── builtin/           # Pre-built skill modules
│       ├── coding.py
│       ├── debugging.py
│       ├── security.py
│       └── design.py
│
├── multi_agent/
│   ├── orchestrator.py    # Task decomposition + spawn
│   ├── worker.py          # Sub-agent process
│   └── bus.py             # Inter-agent communication
│
├── ui/
│   ├── cli.py             # Rich terminal UI
│   └── api.py             # FastAPI HTTP (optional)
│
├── SOUL.md                # Agent identity
├── config.yaml            # User configuration
├── requirements.txt       # Python dependencies
└── README.md
```

---

## FASE IMPLEMENTASI

### FASE 1 — CORE ENGINE (hari 1-2)
**Goal:** Agent loop bisa berpikir + eksekusi tool.

```
✅ engine.py      — Agent loop: plan → execute → observe → replan
✅ providers/     — Claude + OpenAI + Gemini (minimal: OpenRouter buat semua)
✅ tools/registry  — Tool registration system
✅ tools/file_tools — CRUD file (read, write, patch, search)
✅ tools/terminal  — Shell exec dengan approval gate
✅ tools/web_search — Web search via SerpAPI / DuckDuckGo
✅ config.yaml     — User config (provider, keys, preferences)
✅ cli.py          — Minimal CLI: input → agent → output
```

**Test milestone:** "Baca file README.md, cari tau ini project apa, buat summary"

---

### FASE 2 — MEMORY + SKILLS (hari 3-4)
**Goal:** Agent ingat antar session + belajar dari pengalaman.

```
✅ memory/store.py   — SQLite: sessions, conversations, facts
✅ memory/vector.py  — Embeddings + semantic search (sentence-transformers)
✅ memory/context.py — Auto-summarize old context, sliding window
✅ skills/loader.py  — Load skill modules dari folder
✅ skills/self_improve.py — Simpan successful patterns sebagai skill baru
✅ persona.py        — SOUL.md loader, personality injection
```

**Test milestone:** "Remember my favorite stack is FastAPI + React." → next session → "Use FastAPI like you prefer"

---

### FASE 3 — ADVANCED TOOLS (hari 5-6)
**Goal:** Agent bisa browsing, git, analisis kode.

```
✅ tools/browser.py   — Playwright: screenshot, click, form fill
✅ tools/git_tools.py — Status, diff, commit, push (safe branch only)
✅ tools/code_tools.py — AST parsing, lint integration, format
✅ tools/mcp_server.py — MCP protocol: external tools registry
✅ providers/router.py — Auto-select cheapest/best model per task
✅ skills/builtin/    — Pre-built skills: coding, debug, security, design
```

**Test milestone:** "Clone repo X, analisis code quality, bikin PR dengan improvement"

---

### FASE 4 — MULTI-AGENT (hari 7-8)
**Goal:** Spawn sub-agents buat parallel processing.

```
✅ multi_agent/orchestrator.py — Parse complex task → sub-tasks → assign
✅ multi_agent/worker.py       — Isolated sub-agent process
✅ multi_agent/bus.py          — Shared context + result merging
✅ providers/composite.py      — Model fusion (cheap model plans, smart model codes)
```

**Test milestone:** "Bikin full-stack app" → 3 sub-agents parallel: frontend, backend, database

---

### FASE 5 — UI + POLISH (hari 9-10)
**Goal:** UX halus, error handling, dokumentasi.

```
✅ ui/cli.py v2       — Rich: panels, streaming, syntax highlight, history
✅ ui/api.py          — FastAPI: POST /chat, GET /sessions, WebSocket streaming
✅ Error handling     — Graceful degradation, retry logic, fallback models
✅ Telemetry          — Usage stats, cost tracking, performance metrics
✅ README.md          — Full documentation
✅ SOUL.md            — OmniCore identity (dari diskusi kita)
```

**Test milestone:** "OmniCore, introduce yourself and show what you can do"

---

## DEPENDENCIES

```txt
# Core
httpx>=0.27          # HTTP client untuk API calls
pydantic>=2.5        # Type validation
pyyaml>=6.0          # Config parsing

# Memory
sqlite-utils>=3.35   # SQLite helper
chromadb>=0.4        # Vector store (atau sqlite-vec)

# Tools
playwright>=1.40     # Browser automation
duckduckgo-search>=5 # Free web search
rich>=13.7           # Terminal UI

# Optional
fastapi>=0.109       # HTTP API
uvicorn>=0.27        # ASGI server
sentence-transformers # Embeddings (bisa fallback ke API)

# Provider SDKs (optional, bisa via httpx langsung)
anthropic>=0.30
openai>=1.50
google-generativeai>=0.7
```

---

## KEY DESIGN DECISIONS

| Decision | Choice | Reason |
|---|---|---|
| Language | Python 3.11+ | Eco-system terbesar, semua provider ada SDK |
| Provider | OpenRouter first | 1 key, semua model, gampang pivot |
| Memory | SQLite | Zero-dependency, portable, cukup buat single-user |
| Vector | ChromaDB / sqlite-vec | Local, no server needed |
| Sub-agent | Multiprocessing | True isolation, GPU-friendly |
| Tool safety | Approval gate | Terminal + git destructive = user confirm |
| Config | YAML | Human-readable, easy backup |
| Logging | structlog | Structured, JSON, searchable |

---

## PRINSIP PENTING

1. **WORKING CODE > perfect code.** Tiap fase harus ada milestone yg bisa di-test.
2. **STDLIB FIRST.** Jangan nambah dependency kalo stdlib udah cukup.
3. **GRACEFUL DEGRADATION.** Kalo 1 provider down, auto-switch.
4. **MEMORY FIRST.** Agent tanpa memory = chatbot. Ingat antar session.
5. **SELF-IMPROVE.** Tiap sukses → simpan pattern. Tiap gagal → catat pitfall.
6. **GATED DESTRUCTIVE.** Terminal + git + file delete = user approval required.

---

## FILE PERTAMA YANG DIBUAT

```
1. config.yaml           (user config template)
2. core/engine.py        (agent loop)
3. providers/base.py     (abstract interface)
4. providers/claude.py   (provider pertama)
5. tools/registry.py     (tool system)
6. tools/file_tools.py   (tool pertama)
7. ui/cli.py             (minimal CLI)
```

Itu fase 1. 7 file. Estimasi 4-6 jam kerja.

---

## MILESTONE CHECKPOINTS

```
[M1] Fase 1 selesai → agent bisa chat + execute tools
[M2] Fase 2 selesai → agent ingat cross-session
[M3] Fase 3 selesai → agent bisa browse + git
[M4] Fase 4 selesai → multi-agent parallel
[M5] Fase 5 selesai → production-ready
```

---

Gas mulai Fase 1? Gue bikin `config.yaml` + `core/engine.py` dulu.