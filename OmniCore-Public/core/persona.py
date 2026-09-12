"""Persona loader — reads SOUL.md and injects agent identity.
DNA: Mythos (persona fluidity).
"""

from pathlib import Path


def load_soul(soul_path: str = "") -> str:
    """Load SOUL.md and return the agent's identity prompt."""
    paths = [
        Path(soul_path) if soul_path else None,
        Path(__file__).parent.parent / "SOUL.md",
        Path.home() / ".omnicore" / "SOUL.md",
        Path.home() / ".hermes" / "SOUL.md",
    ]
    
    for p in paths:
        if p and p.exists():
            content = p.read_text()
            # Extract just the core identity (skip activation section)
            lines = content.split("\n")
            identity_lines = []
            in_identity = False
            for line in lines:
                if "PERSONA:" in line or "IDENTITY" in line:
                    in_identity = True
                if in_identity and "ACTIVATION" in line:
                    break
                if in_identity:
                    identity_lines.append(line)
            
            if identity_lines:
                return "\n".join(identity_lines)
            return content[:2000]
    
    return "OmniCore — autonomous AI agent. Execute. Learn. Improve."


def get_persona_prompt() -> str:
    """Return the persona prompt for system injection."""
    soul = load_soul()
    return f"""PERSONA:
{soul}

PRINCIPLES:
- Execute immediately. Full code. No stubs.
- Learn from every interaction.
- Be direct, concise, helpful.
- Admit uncertainty rather than fabricate.
"""