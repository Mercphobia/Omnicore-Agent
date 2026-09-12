#!/bin/sh
# OmniCore Agent — One-Line Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/Mercphobia/Omnicore-Agent/main/install.sh | sh

set -e

REPO="https://github.com/Mercphobia/Omnicore-Agent.git"
INSTALL_DIR="${HOME}/omnicore-agent"
BRANCH="main"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║     OmniCore Agent v3 — Installer       ║"
echo "║     Autonomous Hyper-Agent              ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Check Python
if ! command -v python3 >/dev/null 2>&1; then
    echo "❌ Python 3.11+ required. Install python3 first."
    exit 1
fi

PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✓ Python ${PYVER} detected"

# Clone or update
if [ -d "$INSTALL_DIR" ]; then
    echo "✓ Updating existing installation..."
    cd "$INSTALL_DIR"
    git pull origin "$BRANCH" 2>/dev/null || echo "  (update skipped — continuing)"
else
    echo "✓ Cloning OmniCore Agent..."
    git clone --depth 1 --branch "$BRANCH" "$REPO" "$INSTALL_DIR" 2>/dev/null || {
        echo "  Git clone failed. Trying download..."
        mkdir -p "$INSTALL_DIR"
        # Fallback: download zip
        if command -v curl >/dev/null 2>&1; then
            curl -fsSL "${REPO}/archive/refs/heads/${BRANCH}.zip" -o /tmp/omnicore.zip
        elif command -v wget >/dev/null 2>&1; then
            wget -q "${REPO}/archive/refs/heads/${BRANCH}.zip" -O /tmp/omnicore.zip
        fi
        if [ -f /tmp/omnicore.zip ]; then
            unzip -qo /tmp/omnicore.zip -d /tmp/omnicore-tmp
            mv /tmp/omnicore-tmp/*/* "$INSTALL_DIR/" 2>/dev/null
            rm -rf /tmp/omnicore.zip /tmp/omnicore-tmp
        fi
    }
fi

# Install Python dependencies
echo "✓ Installing dependencies..."
cd "$INSTALL_DIR"
pip install httpx pyyaml rich duckduckgo-search 2>/dev/null || pip3 install httpx pyyaml rich duckduckgo-search 2>/dev/null || {
    echo "  ⚠ pip install failed. Install manually:"
    echo "    pip install httpx pyyaml rich duckduckgo-search"
}

# Create config directory
mkdir -p ~/.omnicore

# Make launcher executable
chmod +x "$INSTALL_DIR/omnicore.py" 2>/dev/null || true

# Add to PATH (optional)
ALIAS_LINE="alias omnicore='python3 ${INSTALL_DIR}/omnicore.py'"
if [ -f "$HOME/.bashrc" ] && ! grep -q "omnicore" "$HOME/.bashrc" 2>/dev/null; then
    echo "$ALIAS_LINE" >> "$HOME/.bashrc"
    echo "✓ Added 'omnicore' alias to ~/.bashrc"
elif [ -f "$HOME/.zshrc" ] && ! grep -q "omnicore" "$HOME/.zshrc" 2>/dev/null; then
    echo "$ALIAS_LINE" >> "$HOME/.zshrc"
    echo "✓ Added 'omnicore' alias to ~/.zshrc"
fi

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║     ✓ OmniCore Agent installed!         ║"
echo "╠══════════════════════════════════════════╣"
echo "║                                          ║"
echo "║  Quick start:                            ║"
echo "║    export OPENAI_API_KEY='sk-...'        ║"
echo "║    python3 ~/omnicore-agent/omnicore.py  ║"
echo "║                                          ║"
echo "║  Or use alias:                           ║"
echo "║    source ~/.bashrc                      ║"
echo "║    omnicore                              ║"
echo "║                                          ║"
echo "║  API server:                             ║"
echo "║    python3 ~/omnicore-agent/omnicore.py --server ║"
echo "║                                          ║"
echo "╚══════════════════════════════════════════╝"
echo ""