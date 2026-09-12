#!/data/data/com.termux/files/usr/bin/bash
# OmniCore Setup — One-command installer
# Usage: bash setup.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
BOLD='\033[1m'

echo -e "${CYAN}${BOLD}"
echo "  ╔══════════════════════════════════════╗"
echo "  ║       OmniCore v1.0 Setup           ║"
echo "  ║   The All-Rounder AI Agent          ║"
echo "  ╚══════════════════════════════════════╝"
echo -e "${NC}"

# ── Step 1: Python check ──
echo -e "\n${BOLD}[1/5]${NC} Checking Python..."
PYTHON=$(which python3 || which python)
PYVER=$($PYTHON --version 2>&1 | grep -oP '\d+\.\d+')
echo "  Python: $PYVER"
if (( $(echo "$PYVER < 3.11" | bc -l 2>/dev/null || echo 0) )); then
    echo -e "  ${RED}⚠ Python 3.11+ required${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC}"

# ── Step 2: Install deps ──
echo -e "\n${BOLD}[2/5]${NC} Installing dependencies..."
$PYTHON -m pip install -q httpx pyyaml rich duckduckgo-search pytest pytest-asyncio 2>&1 | tail -1
echo -e "  ${GREEN}✓ Core deps installed${NC}"

# Optional deps
echo "  Optional: fastapi uvicorn playwright..."
$PYTHON -m pip install -q fastapi uvicorn 2>/dev/null && echo -e "  ${GREEN}✓ FastAPI installed${NC}" || echo "  ⚠ FastAPI skipped (optional)"

# ── Step 3: Config ──
echo -e "\n${BOLD}[3/5]${NC} Setting up config..."
CONFIG_DIR="$HOME/.omnicore"
CONFIG_FILE="$CONFIG_DIR/config.yaml"
mkdir -p "$CONFIG_DIR"

if [ -f "$CONFIG_FILE" ]; then
    echo "  Config exists: $CONFIG_FILE"
else
    # Auto-detect provider from Hermes
    if [ -n "$HERMES_BUATPREM_API_KEY" ]; then
        cat > "$CONFIG_FILE" << YAML
# OmniCore Configuration — auto-generated
provider:
  default: custom
  custom:
    api_key: "\${HERMES_BUATPREM_API_KEY}"
    base_url: https://autoapp.biz.id/v1
    default_model: glm-5.3

router:
  smart_model: glm-5.3
  fast_model: glm-5.3
  cheap_model: glm-5.3
  auto_select: true

agent:
  name: OmniCore
  max_retries: 2
  temperature: 0.7
  max_output_tokens: 4096

memory:
  db_path: ~/.omnicore/memory.db
  vector_path: ~/.omnicore/vectors

tools:
  terminal_enabled: true
  terminal_safe_mode: true
  browser_enabled: false
  git_enabled: true

ui:
  theme: dark
  streaming: false
YAML
        echo -e "  ${GREEN}✓ Config created (auto-detected Hermes key)${NC}"
    else
        cp "$SCRIPT_DIR/config.example.yaml" "$CONFIG_FILE"
        echo -e "  ${GREEN}✓ Config created from example${NC}"
        echo -e "  ${RED}⚠ Edit ~/.omnicore/config.yaml to add API key${NC}"
    fi
fi

# ── Step 4: Symlink CLI ──
echo -e "\n${BOLD}[4/5]${NC} Installing omnicore command..."
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"

# Create wrapper script
cat > "$BIN_DIR/omnicore" << 'WRAPPER'
#!/data/data/com.termux/files/usr/bin/bash
SCRIPT_DIR="/storage/emulated/0/OmniCore"
export OMNICORE_API_KEY="${OMNICORE_API_KEY:-$HERMES_BUATPREM_API_KEY}"
cd "$SCRIPT_DIR" && exec python ui/cli.py "$@"
WRAPPER
chmod +x "$BIN_DIR/omnicore"

# Add to PATH if needed
if ! echo "$PATH" | grep -q "$BIN_DIR"; then
    echo "  Add to PATH: export PATH=\"$BIN_DIR:\$PATH\"" 
    if [ -f "$HOME/.bashrc" ]; then
        grep -q "$BIN_DIR" "$HOME/.bashrc" || echo "export PATH=\"$BIN_DIR:\$PATH\"" >> "$HOME/.bashrc"
    fi
fi
echo -e "  ${GREEN}✓ omnicore → $BIN_DIR/omnicore${NC}"

# ── Step 5: Verify ──
echo -e "\n${BOLD}[5/5]${NC} Verifying installation..."
cd "$SCRIPT_DIR"
if $PYTHON -c "import sys; sys.path.insert(0,'.'); from core.engine import OmniCore; print('OK')" 2>/dev/null | grep -q OK; then
    echo -e "  ${GREEN}✓ Engine imports OK${NC}"
else
    echo -e "  ${RED}✗ Engine import failed${NC}"
fi

if $PYTHON -m pytest tests/ -q 2>/dev/null | grep -q "passed"; then
    echo -e "  ${GREEN}✓ Tests pass${NC}"
else
    echo -e "  ${RED}✗ Tests failed${NC}"
fi

echo -e "\n${GREEN}${BOLD}═══ OmniCore Ready ═══${NC}"
echo "  Run:  omnicore              # Interactive mode"
echo "  Run:  omnicore 'query'      # Single query"
echo "  Config: ~/.omnicore/config.yaml"
echo "  Memory: ~/.omnicore/memory.db"
echo "  Skills: ~/.omnicore/skills/"
echo ""