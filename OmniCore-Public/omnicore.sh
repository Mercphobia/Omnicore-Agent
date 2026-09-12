#!/data/data/com.termux/files/usr/bin/bash
# OmniCore launcher — auto-wires API key from Hermes env
# Usage: omnicore [args...]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Auto-detect API key from Hermes environment
if [ -z "$OMNICORE_API_KEY" ] && [ -n "$HERMES_BUATPREM_API_KEY" ]; then
    export OMNICORE_API_KEY="$HERMES_BUATPREM_API_KEY"
fi

# Run
cd "$SCRIPT_DIR"
exec python ui/cli.py "$@"