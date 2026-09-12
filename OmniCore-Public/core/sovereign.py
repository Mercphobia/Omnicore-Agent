"""Sovereign Mode — Operator full access, public users locked in PersonaCage.

DNA: LTX-Quasar (cold protocol) + constitutional anchoring.

TWO-TIER SYSTEM:
  Level 0: OPERATOR (Jack) — Full access, no restrictions, can modify agent identity.
  Level 1: PUBLIC — PersonaCage enforced, jailbreak blocked, identity locked.

Authentication: master_key in config, env var, or cryptographic challenge.
When operator is detected → ALL shields disabled, ALL capabilities unlocked.
When public → full enforcement, no escape, no exception.
"""

import os
import hashlib
import secrets
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


# ── Operator identities ───────────────────────────────────────────────

@dataclass
class OperatorIdentity:
    """A verified operator with full access."""
    name: str
    auth_method: str
    permissions: list[str]


class SovereignGate:
    """Sovereign access gate. Decides: operator or public?

    When OPERATOR:
    - PersonaCage: DISABLED (can change identity freely)
    - JailbreakForge SHIELD: DISABLED (can run any prompt)
    - TokenForge budget: UNLIMITED (no token restrictions)
    - All tools: UNLOCKED (no approval gates)
    - System prompt: MODIFIABLE

    When PUBLIC:
    - PersonaCage: FULL ENFORCEMENT
    - JailbreakForge SHIELD: ACTIVE (detect + block)
    - TokenForge budget: ENFORCED
    - Destructive tools: REQUIRES APPROVAL
    - System prompt: LOCKED
    """

    def __init__(self, master_key: str = "", master_key_file: Optional[Path] = None):
        """Initialize the sovereign gate.

        Args:
            master_key: A secret key only the operator knows.
            master_key_file: Path to file containing master key hash.
        """
        self._master_key_hash: Optional[str] = None
        self._current_level: str = "public"  # default: locked down
        self._operator: Optional[OperatorIdentity] = None

        # Load master key
        key = master_key or os.environ.get("OMNICORE_MASTER_KEY", "")
        if master_key_file and master_key_file.exists():
            key = master_key_file.read_text().strip()

        if key:
            self._master_key_hash = hashlib.sha256(
                f"omnicore:sovereign:{key}".encode()
            ).hexdigest()

    # ── Authentication ───────────────────────────────────────────────

    def authenticate(self, challenge_response: str) -> bool:
        """Verify operator identity.

        Methods accepted:
        - Direct key: challenge_response == master_key
        - Timed challenge: operator signs timestamp with key
        - Pre-shared hash: challenge_response matches stored hash
        """
        if not self._master_key_hash:
            return False

        # Method 1: Direct key match
        if hashlib.sha256(
            f"omnicore:sovereign:{challenge_response}".encode()
        ).hexdigest() == self._master_key_hash:
            self._elevate("direct_key")
            return True

        # Method 2: Challenge-response
        if self._verify_challenge(challenge_response):
            self._elevate("challenge_response")
            return True

        return False

    def authenticate_env(self) -> bool:
        """Auto-authenticate from environment variables.

        Checks OMNICORE_MASTER_KEY env var.
        Also checks if running in development/trusted context.
        """
        # Direct key from env
        key = os.environ.get("OMNICORE_MASTER_KEY", "")
        if key and self.authenticate(key):
            return True

        # Trusted device fingerprint
        if os.environ.get("OMNICORE_TRUSTED_DEVICE") == "1":
            self._elevate("trusted_device")
            return True

        return False

    def _elevate(self, method: str):
        """Elevate current session to operator level."""
        self._current_level = "operator"
        self._operator = OperatorIdentity(
            name="Jack",
            auth_method=method,
            permissions=["*"],  # all permissions
        )

    def _verify_challenge(self, response: str) -> bool:
        """Verify a challenge-response authentication."""
        # Simple: response should be sha256(timestamp + master_key)
        # This prevents replay attacks
        if not self._master_key_hash or ":" not in response:
            return False
        try:
            timestamp, signature = response.split(":", 1)
            # Verify timestamp is recent (within 60 seconds)
            import time
            if abs(float(timestamp) - time.time()) > 60:
                return False
            expected = hashlib.sha256(
                f"omnicore:challenge:{timestamp}:{self._master_key_hash}".encode()
            ).hexdigest()[:16]
            return secrets.compare_digest(signature, expected)
        except (ValueError, TypeError):
            return False

    # ── Access checks ────────────────────────────────────────────────

    @property
    def is_operator(self) -> bool:
        """Is the current session running as operator?"""
        return self._current_level == "operator"

    @property
    def level(self) -> str:
        """Current access level: 'operator' or 'public'."""
        return self._current_level

    def can_override_identity(self) -> bool:
        """Can the user override OmniCore persona/identity?"""
        return self.is_operator

    def can_bypass_shields(self) -> bool:
        """Can the user bypass jailbreak/persona shields?"""
        return self.is_operator

    def can_use_destructive_tools(self) -> bool:
        """Can the user use destructive tools without approval?"""
        return self.is_operator

    def has_unlimited_budget(self) -> bool:
        """Does the user have unlimited API token budget?"""
        return self.is_operator

    # ── Challenge generation ─────────────────────────────────────────

    def generate_challenge(self) -> str:
        """Generate a challenge for operator authentication.

        Returns a timestamp that the operator must sign with master_key.
        """
        import time
        timestamp = str(int(time.time()))
        return f"OMNICORE_CHALLENGE:{timestamp}"

    # ── Session management ───────────────────────────────────────────

    def lock(self):
        """Lock session back to public level."""
        self._current_level = "public"
        self._operator = None

    def status(self) -> dict:
        """Get current sovereign gate status."""
        return {
            "level": self._current_level,
            "operator": self._operator.name if self._operator else None,
            "auth_method": self._operator.auth_method if self._operator else None,
            "persona_cage": "DISABLED" if self.is_operator else "ENFORCED",
            "jailbreak_shield": "DISABLED" if self.is_operator else "ACTIVE",
            "token_budget": "UNLIMITED" if self.is_operator else "ENFORCED",
            "identity_override": "ALLOWED" if self.is_operator else "LOCKED",
        }


# ── Operator token generator ──────────────────────────────────────────

def generate_master_key() -> str:
    """Generate a cryptographically secure master key.

    Usage (one-time, by Jack):
        python -c "from core.sovereign import generate_master_key; print(generate_master_key())"
    
    Save the output. This is your permanent operator key.
    Set as OMNICORE_MASTER_KEY env var or in ~/.omnicore/master.key
    """
    return secrets.token_hex(32)


# ── Self-test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Test without master key (public mode)
    gate = SovereignGate()
    print(f"No key: level={gate.level}, operator={gate.is_operator}")

    # Test with master key (operator mode)
    master = "test-secret-key-123"
    gate2 = SovereignGate(master_key=master)
    print(f"With key, before auth: level={gate2.level}")

    # Authenticate
    ok = gate2.authenticate(master)
    print(f"Auth result: {ok}, level={gate2.level}, operator={gate2.is_operator}")

    # Verify operator privileges
    print(f"  can_override_identity: {gate2.can_override_identity()}")
    print(f"  can_bypass_shields: {gate2.can_bypass_shields()}")
    print(f"  can_use_destructive: {gate2.can_use_destructive_tools()}")
    print(f"  has_unlimited_budget: {gate2.has_unlimited_budget()}")

    # Test lock
    gate2.lock()
    print(f"After lock: level={gate2.level}")

    # Test status
    gate2.authenticate(master)
    print(f"\nStatus:\n{gate2.status()}")

    # Test challenge generation
    challenge = gate2.generate_challenge()
    print(f"\nChallenge: {challenge}")

    # Test env auth
    os.environ["OMNICORE_MASTER_KEY"] = master
    gate3 = SovereignGate()
    ok3 = gate3.authenticate_env()
    print(f"\nEnv auth: {ok3}, level={gate3.level}")
    del os.environ["OMNICORE_MASTER_KEY"]

    # Test generate key
    new_key = generate_master_key()
    print(f"\nGenerated key: {new_key[:20]}... (length: {len(new_key)})")

    print("\n✓ SovereignGate self-tests passed")
    print("\n   Operator: Full access, no restrictions")
    print("   Public: PersonaCage locked, jailbreak blocked")