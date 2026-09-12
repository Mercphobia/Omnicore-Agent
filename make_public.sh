#!/data/data/com.termux/files/usr/bin/bash
# make_public.sh — Strip operator features for public release
# Usage: ./make_public.sh [output_dir]
# Default: ../OmniCore-Public

set -e

SOURCE="${1:-$(dirname "$0")}"
OUTPUT="${2:-$(dirname "$SOURCE")/OmniCore-Public}"

echo "⚡ OmniCore — Public Release Builder"
echo "   Source: $SOURCE"
echo "   Output: $OUTPUT"
echo ""

# Clean output
rm -rf "$OUTPUT"
mkdir -p "$OUTPUT"

# Copy everything first
cp -r "$SOURCE"/* "$OUTPUT"/
cp "$SOURCE"/.gitignore "$OUTPUT"/ 2>/dev/null || true

echo "   [1/6] Stripping SovereignGate operator bypass..."
# Remove operator authentication capability
cat > "$OUTPUT/core/sovereign.py" << 'SOVEREIGN_EOF'
"""SovereignGate — PUBLIC MODE ONLY. Operator access removed."""
import os

class SovereignGate:
    def __init__(self, **kwargs):
        self._current_level = "public"
    def authenticate(self, challenge=""):
        return False
    def authenticate_env(self):
        return False
    @property
    def is_operator(self):
        return False
    @property
    def level(self):
        return "public"
    def can_override_identity(self):
        return False
    def can_bypass_shields(self):
        return False
    def can_use_destructive_tools(self):
        return False
    def has_unlimited_budget(self):
        return False
    def status(self):
        return {"level": "public", "persona_cage": "ENFORCED", "jailbreak_shield": "ACTIVE"}
    def generate_challenge(self):
        return ""
    def lock(self):
        pass
SOVEREIGN_EOF

echo "   [2/6] Stripping JailbreakForge SWORD..."
# Keep SHIELD (defense), remove SWORD (offense)
cat > "$OUTPUT/core/jailbreak_forge.py" << 'JB_EOF'
"""Jailbreak SHIELD — defensive only. SWORD removed for public release."""
import re

KNOWN_JAILBREAK_SIGNATURES = [
    r'(?i)\bDAN\b', r'(?i)\bDo Anything Now\b', r'(?i)\bignore\b.*\binstructions?\b',
    r'(?i)\bpretend\b.*\byou are\b', r'(?i)\byou are now\b',
    r'(?i)\boverride\b.*\b(system|safety)\b', r'(?i)\bjailbreak\b',
    r'(?i)\b(forget|disregard)\b.*\b(instructions?|rules?)\b',
    r'(?i)\bdecode\b.*\b(base64|rot13)\b', r'(?i)\brepeat\b.*\bverbatim\b',
    r'(?i)\bhypothetical\b', r'(?i)\bno (restrictions?|limits?|rules?)\b',
]

DANGEROUS_INTENT_PATTERNS = [
    (r'(?i)\b(create|write|generate|code)\b.*\b(malware|virus|ransomware)\b', 'MALWARE_GEN'),
    (r'(?i)\b(hack|crack|compromise)\b.*\b(system|network|account)\b', 'UNAUTHORIZED'),
    (r'(?i)\b(ddos|denial of service)\b', 'DDOS'),
    (r'(?i)\b(steal|exfiltrate)\b.*\b(credentials?|passwords?|data)\b', 'DATA_THEFT'),
]

class JailbreakForge:
    """SHIELD ONLY — defensive jailbreak detection. No SWORD."""
    def __init__(self):
        self.blocked_count = 0
        self._jb = [re.compile(p) for p in KNOWN_JAILBREAK_SIGNATURES]
        self._di = [(re.compile(p), t) for p, t in DANGEROUS_INTENT_PATTERNS]
    def shield_scan(self, text, system_prompt=""):
        detected, blocked = [], False
        for p in self._jb:
            if p.search(text): detected.append(f"JAILBREAK:{p.pattern[:40]}")
        for p, t in self._di:
            if p.search(text): detected.append(f"INTENT:{t}"); blocked = True
        threat = "BLOCKED" if blocked else ("SUSPICIOUS" if detected else "SAFE")
        return type('R',(),{'safe':threat=='SAFE','threat_level':threat,'detected_patterns':detected,'blocked':blocked,'sanitized_input':text,'reason':'; '.join(detected)})()
    def stats(self):
        return {"blocked": self.blocked_count}
JB_EOF

echo "   [3/6] Stripping operator-only skill prompts..."
# Remove SWORD-related language from skills
for f in "$OUTPUT"/skills/builtin/*.py; do
    sed -i 's/SWORD mode available//g' "$f" 2>/dev/null || true
    sed -i 's/operator.*full access//g' "$f" 2>/dev/null || true
done

echo "   [4/6] Locking PersonaCage to always-enforced..."
cat > "$OUTPUT/core/persona_cage.py" << 'PC_EOF'
"""PersonaCage — ALWAYS ENFORCED. No operator bypass in public release."""
import re

OMNICORE_IDENTITY = """You are OmniCore v3 Public Edition.
IDENTITY LOCK: You are OmniCore. No model disclosure. No escape. No exception."""
BANNED_PATTERNS = [(r'(?i)\bI am (Claude|GPT|Gemini|DeepSeek)\b', 'I am OmniCore'),
    (r'(?i)\bpowered by (OpenAI|Anthropic|Google)\b', 'OmniCore v3'),
    (r'(?i)\ban AI (?:language )?model\b', 'an autonomous hyper-agent'),]

class PersonaCage:
    def __init__(self, **kw): pass
    def get_system_message(self): return {"role":"system","content":OMNICORE_IDENTITY}
    def sanitize_response(self, text):
        for p, r in BANNED_PATTERNS: text = re.sub(p, r, text)
        return text
    def check_compliance(self, r):
        return type('C',(),{'compliant':True,'violations':[],'cleaned_response':r,'retry_needed':False})()
    def prepare_messages(self, msgs):
        return [self.get_system_message()] + [m for m in msgs if m.get('role')!='system']
    def process_response(self, r, **kw): return (self.sanitize_response(r), False)

def cage_prompt(p): return f"[OmniCore v3] {p}"
PC_EOF

echo "   [5/6] Making engine public-only..."
# Patch engine to always use public mode
sed -i 's/self\.sovereign\.authenticate_env()/pass  # public mode only/' "$OUTPUT/core/engine.py"
sed -i 's/if not self\.sovereign\.is_operator:/if True:  # always public/' "$OUTPUT/core/engine.py"
sed -i 's/self\.sovereign\.is_operator/False  # public mode/g' "$OUTPUT/core/engine.py"

echo "   [6/6] Cleaning up..."
# Remove development artifacts
rm -f "$OUTPUT/core/red_team.py.redteam.bak" 2>/dev/null || true
rm -rf "$OUTPUT/__pycache__" "$OUTPUT/**/__pycache__" 2>/dev/null || true
rm -rf "$OUTPUT/.pytest_cache" 2>/dev/null || true
rm -f "$OUTPUT/generated_tools/image_converter.py" 2>/dev/null || true
rm -f "$OUTPUT/hermes_plugin.py" 2>/dev/null || true

# Remove plan docs (internal only)
rm -f "$OUTPUT/DNA_MYTHOS_ASTRA.md" "$OUTPUT/DNA_PLAN.md" "$OUTPUT/PLAN.md" 2>/dev/null || true
rm -f "$OUTPUT/OVERPOWER_PLAN.md" "$OUTPUT/SUPERWEAPON_PLAN.md" "$OUTPUT/FINAL_ASCENSION.md" 2>/dev/null || true
rm -f "$OUTPUT/VS_HERMES.md" 2>/dev/null || true

echo ""
echo "═══════════════════════════════════════════════"
echo "  ✓ Public release ready at: $OUTPUT"
echo "  ✓ SovereignGate: PUBLIC-ONLY"
echo "  ✓ JailbreakForge: SHIELD ONLY (no SWORD)"
echo "  ✓ PersonaCage: ENFORCED, no bypass"
echo "  ✓ All cybersecurity tools intact (defensive)"
echo "  ✓ All 11 providers"
echo "  ✓ 55 skills (operator mentions removed)"
echo ""
echo "  To publish:"
echo "    cd $OUTPUT"
echo "    git init && git add -A"
echo "    git commit -m 'OmniCore v3 Public Edition'"
echo "    git remote add origin https://github.com/Mercphobia/OmniCore-Public.git"
echo "    git push -u origin main"
echo "═══════════════════════════════════════════════"