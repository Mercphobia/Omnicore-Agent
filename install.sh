#!/bin/sh
# OmniCore Private — One-Line Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/Mercphobia/Omnicore/main/install.sh | sh

set -e

REPO="https://github.com/Mercphobia/Omnicore.git"
INSTALL_DIR="${HOME}/omnicore"
BRANCH="main"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   OmniCore v3 — Private Installer       ║"
echo "║   Autonomous Hyper-Agent                ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Check Python
if ! command -v python3 >/dev/null 2>&1; then
    echo "❌ Python 3.11+ required."
    exit 1
fi

PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✓ Python ${PYVER}"

# Clone or update
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "✓ Updating..."
    cd "$INSTALL_DIR"
    git pull origin "$BRANCH" 2>/dev/null || echo "  (update skipped)"
else
    echo "✓ Cloning OmniCore..."
    git clone --depth 1 --branch "$BRANCH" "$REPO" "$INSTALL_DIR" 2>/dev/null || {
        echo "  ⚠ Clone failed. Need access to private repo."
        echo "  Make sure you have GitHub access to Mercphobia/Omnicore"
        exit 1
    }
fi

# Install Python deps
echo "✓ Installing dependencies..."
cd "$INSTALL_DIR"
pip install httpx pyyaml rich duckduckgo-search 2>/dev/null || pip3 install httpx pyyaml rich duckduckgo-search 2>/dev/null

# Config
mkdir -p ~/.omnicore

# Alias
ALIAS_LINE="alias omnicore='python3 ${INSTALL_DIR}/omnicore.py'"
for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
    if [ -f "$rc" ] && ! grep -q "omnicore" "$rc" 2>/dev/null; then
        echo "$ALIAS_LINE" >> "$rc"
        echo "✓ Added alias to $(basename $rc)"
    fi
done

# Generate master key if not exists
if [ ! -f "$HOME/.omnicore/master.key" ]; then
    python3 -c "import secrets; print(secrets.token_hex(32))" > "$HOME/.omnicore/master.key"
    chmod 600 "$HOME/.omnicore/master.key"
    echo "✓ Master key generated: ~/.omnicore/master.key"
    echo "  Set: export OMNICORE_MASTER_KEY=\$(cat ~/.omnicore/master.key)"
fi

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║    ✓ OmniCore v3 Installed!             ║"
echo "╠══════════════════════════════════════════╣"
echo "║                                          ║"
echo "║  Quick start:                            ║"
echo "║    export OPENAI_API_KEY='sk-...'        ║"
echo "║    omnicore                              ║"
echo "║                                          ║"
echo "║  Operator mode:                          ║"
echo "║    export OMNICORE_MASTER_KEY=\$(cat ~/.omnicore/master.key)"
echo "║    omnicore                              ║"
echo "║                                          ║"
echo "║  API server:                             ║"
echo "║    omnicore --server                     ║"
echo "║                                          ║"
echo "║  Web dashboard:                          ║"
echo "║    open ui/dashboard.html                ║"
echo "║                                          ║"
echo "╚══════════════════════════════════════════╝"
echo ""