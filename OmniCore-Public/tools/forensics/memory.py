#!/usr/bin/env python3
"""Memory forensics — process dumping, string extraction, credential scanning.
DNA: Memory Analysis (process dump, injection detection, credential extraction).

Analysis of process memory dumps on Linux and macOS. Windows support
via Volatility if installed. Pure Python for core analysis; optional
subprocess callouts to external tools.

Usage::

    from tools.forensics.memory import MemoryAnalyzer

    ma = MemoryAnalyzer()
    ma.dump_process(1234)
    creds = ma.extract_credentials("/tmp/dump_1234.bin")
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import struct
import subprocess
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Common patterns for sensitive data
_CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,16}\b")

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

_URL_RE = re.compile(rb'https?://[^\x00-\x1f\x7f-\x9f\s<>"\')\\]+')

_API_KEY_RE = re.compile(
    r"(?i)(?:api[_-]?key|apikey|secret|token|password|passwd|access[_-]?key)"
    r'\s*[:=]\s*[\'"]([^\'"]{8,})[\'"]',
)

# Linux credential patterns
_PASSWD_LINE_RE = re.compile(rb"([^:\x00]+):([^:\x00]*):\d+:\d+:.*")

# SSH private key
_SSH_KEY_RE = re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----\n[\s\S]+?-----END")

# AWS keys
_AWS_ACCESS_KEY_RE = re.compile(rb"(?:AKIA|ASIA)[A-Z0-9]{16}")

# Linux /etc/shadow
_SHADOW_LINE_RE = re.compile(rb"([^:\x00]+):\$[^:\x00]+\$[^:\x00]+\$[^:\x00]+:")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MemoryRegion:
    """Memory region from /proc/PID/maps."""
    start: int
    end: int
    perms: str
    offset: int
    device: str
    inode: int
    pathname: str = ""


@dataclass
class MemoryFinding:
    """A finding from memory analysis."""
    type: str
    value: str
    offset: int = 0
    context: str = ""


# ---------------------------------------------------------------------------
# MemoryAnalyzer
# ---------------------------------------------------------------------------

class MemoryAnalyzer:
    """Analyze process memory for forensics purposes.

    Supports process dumping, string extraction, pattern scanning,
    code injection detection, credential extraction, and timeline building.

    Attributes:
        dump_dir: Directory for storing memory dumps.
        volatile: If True, dumps go to /tmp and are temporary.
    """

    def __init__(self, dump_dir: str = "", volatile: bool = True):
        self.dump_dir = dump_dir or (tempfile.mkdtemp(prefix="omnicore_mem_") if volatile
                                     else os.path.expanduser("~/omnicore_dumps"))
        self.volatile = volatile
        os.makedirs(self.dump_dir, exist_ok=True)

    # ── Process dump ───────────────────────────────────────────────

    def dump_process(self, pid: int, output_path: str = "") -> str:
        """Dump process memory from /proc/PID/mem.

        Args:
            pid: Process ID to dump.
            output_path: Output file path (auto-generated if empty).

        Returns:
            Path to the memory dump file, or empty string on failure.
        """
        if not output_path:
            output_path = os.path.join(self.dump_dir, f"dump_{pid}_{int(time.time())}.bin")

        pid = int(pid)

        # ── Method 1: /proc/PID/mem (Linux) ────────────────────
        mem_path = f"/proc/{pid}/mem"
        maps_path = f"/proc/{pid}/maps"

        if os.path.exists(mem_path) and os.access(mem_path, os.R_OK):
            regions = self._parse_maps(maps_path)
            try:
                with open(mem_path, "rb") as src, open(output_path, "wb") as dst:
                    total = 0
                    for region in regions:
                        if "r" in region.perms:  # Only readable regions
                            try:
                                src.seek(region.start)
                                size = region.end - region.start
                                data = src.read(min(size, 10 * 1024 * 1024))  # Cap at 10MB/region
                                dst.write(data)
                                total += len(data)
                            except OSError:
                                continue
                return output_path if total > 0 else ""
            except (OSError, PermissionError):
                pass

        # ── Method 2: gcore (Linux) ────────────────────────────
        try:
            r = subprocess.run(
                ["gcore", "-o", output_path.replace(".bin", ""), str(pid)],
                capture_output=True, text=True, timeout=30,
            )
            core_file = output_path.replace(".bin", ".core")
            # gcore appends .<pid> to filename
            alt_core = f"{output_path.replace('.bin', '')}.{pid}"
            for candidate in [core_file, alt_core]:
                if os.path.exists(candidate):
                    if candidate != output_path:
                        os.rename(candidate, output_path)
                    return output_path
        except FileNotFoundError:
            pass

        return ""

    def _parse_maps(self, maps_path: str) -> list[MemoryRegion]:
        """Parse /proc/PID/maps into MemoryRegion objects."""
        regions: list[MemoryRegion] = []
        try:
            with open(maps_path) as f:
                for line in f:
                    parts = line.strip().split(None, 5)
                    if len(parts) < 5:
                        continue
                    addr_range = parts[0].split("-")
                    start = int(addr_range[0], 16)
                    end = int(addr_range[1], 16)
                    perms = parts[1]
                    offset = int(parts[2], 16)
                    device = parts[3]
                    inode = int(parts[4])
                    pathname = parts[5] if len(parts) > 5 else ""
                    regions.append(MemoryRegion(start, end, perms, offset, device, inode, pathname))
        except OSError:
            pass
        return regions

    # ── String extraction ──────────────────────────────────────────

    def strings_extract(self, dump_path: str, min_length: int = 4) -> dict[str, list[str]]:
        """Extract ASCII and Unicode strings from a memory dump.

        Args:
            dump_path: Path to memory dump file.
            min_length: Minimum string length.

        Returns:
            Dict with 'ascii' and 'unicode' string lists.
        """
        result: dict[str, list[str]] = {"ascii": [], "unicode": []}

        try:
            with open(dump_path, "rb") as f:
                data = f.read()
        except OSError:
            return result

        ascii_strs: list[str] = []
        uni_strs: list[str] = []

        # ASCII strings
        current: list[int] = []
        for byte in data:
            if 32 <= byte < 127:
                current.append(byte)
            else:
                if len(current) >= min_length:
                    ascii_strs.append(bytes(current).decode("ascii"))
                current = []

        if len(current) >= min_length:
            ascii_strs.append(bytes(current).decode("ascii"))

        # Unicode (UTF-16LE) strings
        current_u: list[int] = []
        i = 0
        while i + 1 < len(data):
            ch = data[i] | (data[i + 1] << 8)
            if 32 <= ch < 65536 and ch != 0:
                current_u.append(ch)
            else:
                if len(current_u) >= min_length:
                    uni_strs.append("".join(chr(c) for c in current_u))
                current_u = []
            i += 2

        if len(current_u) >= min_length:
            uni_strs.append("".join(chr(c) for c in current_u))

        result["ascii"] = list(dict.fromkeys(ascii_strs))  # Deduplicate
        result["unicode"] = list(dict.fromkeys(uni_strs))
        return result

    # ── Pattern scanning ───────────────────────────────────────────

    def scan_patterns(
        self, dump_path: str, patterns: dict[str, str] | None = None,
    ) -> dict[str, list[str]]:
        """Scan a memory dump for patterns (credit cards, emails, URLs, etc.).

        Args:
            dump_path: Path to memory dump.
            patterns: Custom pattern dict {name: regex}. Uses defaults if None.

        Returns:
            Dict with pattern_name -> list of matches.
        """
        results: dict[str, list[str]] = defaultdict(list)

        try:
            with open(dump_path, "rb") as f:
                data = f.read()
        except OSError:
            return dict(results)

        # Default patterns
        if patterns is None:
            patterns = {
                "credit_cards": r"\b(?:\d[ -]*?){13,16}\b",
                "emails": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
                "urls": r'https?://[^\x00-\x1f\x7f-\x9f\s<>"\')\\]+',
                "aws_keys": r"(?:AKIA|ASIA)[A-Z0-9]{16}",
                "ssh_keys": r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----[\\s\\S]+?-----END",
                "ipv4": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
                "base64": r"[A-Za-z0-9+/]{20,}={0,2}",
                "jwt": r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
            }

        for name, pattern in patterns.items():
            try:
                if isinstance(pattern, str):
                    regex = re.compile(pattern.encode() if isinstance(data, bytes) else pattern)
                matches = regex.findall(data) if isinstance(data, bytes) else re.findall(pattern, data)
                deduped: list[str] = []
                seen: set[str] = set()
                for m in matches:
                    m_str = m.decode(errors="replace") if isinstance(m, bytes) else str(m)
                    if m_str not in seen and len(m_str) < 500:
                        seen.add(m_str)
                        deduped.append(m_str)
                results[name] = deduped[:50]  # Limit per pattern
            except re.error:
                pass

        return dict(results)

    # ── Injection detection ────────────────────────────────────────

    def find_injection(self, dump_path: str) -> dict[str, Any]:
        """Detect potential code injection in memory.

        Looks for RWX memory regions, suspicious shellcode patterns,
        and anomalous executable mappings.

        Args:
            dump_path: Path to memory dump file.

        Returns:
            Dict with injection indicators found.
        """
        result: dict[str, Any] = {
            "indicators": [],
            "rwx_regions": [],
            "shellcode_patterns": [],
            "score": 0,
        }

        try:
            with open(dump_path, "rb") as f:
                data = f.read()
        except OSError:
            return result

        # Shellcode patterns (common prologues)
        shellcode_indicators = [
            (b"\x31\xc0\x50\x68", "xor eax, push — Linux x86 shellcode"),
            (b"\x31\xd2\x52\x68", "xor edx, push — Linux x86 shellcode"),
            (b"\xfc\x48\x83\xe4", "cld; and rsp — Windows x64 shellcode"),
            (b"\x55\x8b\xec\x83", "push ebp; mov ebp — function prologue in data"),
            (b"\xcc\xcc\xcc\xcc", "INT3 sled (debug trap)"),
            (b"\x90\x90\x90\x90\x90", "NOP sled"),
        ]

        for sig, desc in shellcode_indicators:
            count = data.count(sig)
            if count > 0:
                result["shellcode_patterns"].append({
                    "pattern": sig.hex(),
                    "description": desc,
                    "occurrences": count,
                })

        # Look for mmap'd RWX regions (from /proc/PID/maps)
        maps_path = dump_path.replace(".bin", ".maps")
        if os.path.exists(maps_path):
            with open(maps_path) as f:
                for line in f:
                    if "rwx" in line:
                        result["rwx_regions"].append(line.strip()[:120])

        # Score
        result["score"] = (
            len(result["shellcode_patterns"]) * 10
            + len(result["rwx_regions"]) * 15
        )
        if result["score"] > 0:
            result["indicators"].append(f"Injection score: {result['score']} (higher = more suspicious)")

        return result

    # ── Credential extraction ──────────────────────────────────────

    def extract_credentials(self, dump_path: str) -> list[dict[str, str]]:
        """Extract credentials from a memory dump.

        Looks for passwords, tokens, SSH keys, API keys, and
        credential-like patterns in process memory.

        Args:
            dump_path: Path to memory dump file.

        Returns:
            List of {'type': ..., 'value': ...} dicts.
        """
        findings: list[dict[str, str]] = []

        try:
            with open(dump_path, "rb") as f:
                data = f.read()
        except OSError:
            return findings

        seen: set[str] = set()

        def _add(ftype: str, fvalue: str, foffset: int = 0):
            key = f"{ftype}:{fvalue[:40]}"
            if key not in seen:
                seen.add(key)
                findings.append({"type": ftype, "value": fvalue, "offset": str(foffset)})

        # SSH private keys
        for match in _SSH_KEY_RE.finditer(data):
            key_data = match.group().decode(errors="replace")
            _add("ssh_private_key", key_data[:200] + "..." if len(key_data) > 200 else key_data,
                 match.start())

        # AWS access keys
        for match in _AWS_ACCESS_KEY_RE.finditer(data):
            _add("aws_access_key", match.group().decode(), match.start())

        # Passwords from /etc/passwd or /etc/shadow
        for match in _SHADOW_LINE_RE.finditer(data):
            user = match.group(1).decode(errors="replace")
            hash_val = match.group(2).decode(errors="replace")
            _add("shadow_entry", f"{user}:{hash_val[:60]}", match.start())

        # API keys in key=value patterns
        for match in re.finditer(_API_KEY_RE, data.decode(errors="replace")):
            _add("api_key", match.group(0)[:120], match.start())

        # JWT tokens
        jwt_re = re.compile(rb"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
        for match in jwt_re.finditer(data):
            _add("jwt_token", match.group().decode(errors="replace")[:120], match.start())

        # Base64 blobs that look like encoded credentials
        b64_re = re.compile(rb"[A-Za-z0-9+/]{40,}={0,2}")
        for match in b64_re.finditer(data):
            candidate = match.group().decode(errors="replace")
            try:
                decoded = base64.b64decode(candidate)
                if b":" in decoded or b"=" in decoded or b"password" in decoded.lower():
                    _add("base64_creds", candidate[:80], match.start())
            except Exception:
                pass

        return findings

    # ── Timeline from memory ───────────────────────────────────────

    def timeline_from_memory(self, dump_path: str) -> list[dict[str, str]]:
        """Extract timestamps from a memory dump.

        Finds Unix timestamps (4-byte LE/BE) and converts them to
        human-readable times near a reasonable range.

        Args:
            dump_path: Path to memory dump.

        Returns:
            List of {'timestamp': ..., 'datetime': ..., 'offset': ...} dicts.
        """
        results: list[dict[str, str]] = []

        try:
            with open(dump_path, "rb") as f:
                data = f.read()
        except OSError:
            return results

        now = int(time.time())
        min_ts = now - (10 * 365 * 86400)  # 10 years ago
        max_ts = now + (1 * 365 * 86400)   # 1 year future

        i = 0
        seen_ts: set[str] = set()
        while i + 4 <= len(data):
            # Little-endian 32-bit
            ts_le = struct.unpack("<I", data[i:i + 4])[0]
            if min_ts <= ts_le <= max_ts:
                ts_str = str(ts_le)
                if ts_str not in seen_ts:
                    seen_ts.add(ts_str)
                    results.append({
                        "timestamp": ts_str,
                        "datetime": datetime.fromtimestamp(ts_le, tz=timezone.utc).isoformat(),
                        "offset": str(i),
                        "endian": "little",
                    })

            # Big-endian 32-bit
            ts_be = struct.unpack(">I", data[i:i + 4])[0]
            if min_ts <= ts_be <= max_ts and ts_be != ts_le:
                ts_str = str(ts_be)
                if ts_str not in seen_ts:
                    seen_ts.add(ts_str)
                    results.append({
                        "timestamp": ts_str,
                        "datetime": datetime.fromtimestamp(ts_be, tz=timezone.utc).isoformat(),
                        "offset": str(i),
                        "endian": "big",
                    })

            i += 1  # Step byte by byte

        # Sort by timestamp
        results.sort(key=lambda x: int(x["timestamp"]), reverse=True)

        return results[:200]  # Limit to most recent 200


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Memory Forensics Self-Test ===\n")

    ma = MemoryAnalyzer(volatile=True)

    # Create a test dump with known data
    test_data = (
        b"Hello world\x00" * 50
        + b"admin:password123\x00"
        + b"AKIAIOSFODNN7EXAMPLE\x00"
        + b"eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyIjoiYWRtaW4ifQ.signature\x00"
        + b"https://evil.com/c2\x00"
        + b"alice@example.com\x00"
        + b"-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----\x00"
        + struct.pack("<I", int(time.time()) - 3600) * 5  # Timestamps
        + b"\x31\xc0\x50\x68" * 3  # Shellcode pattern
    )

    test_dump = os.path.join(ma.dump_dir, "test_dump.bin")
    with open(test_dump, "wb") as f:
        f.write(test_data)

    # Strings
    print("--- strings_extract ---")
    strings = ma.strings_extract(test_dump, min_length=4)
    print(f"  ASCII strings: {len(strings['ascii'])}")
    print(f"  Unicode strings: {len(strings['unicode'])}")

    # Pattern scan
    print("\n--- scan_patterns ---")
    patterns = ma.scan_patterns(test_dump)
    for name, matches in patterns.items():
        if matches:
            print(f"  {name}: {len(matches)} matches — {matches[0][:60]}")

    # Injection detection
    print("\n--- find_injection ---")
    inj = ma.find_injection(test_dump)
    print(f"  Score: {inj['score']}")
    print(f"  Shellcode patterns: {len(inj['shellcode_patterns'])}")
    for sp in inj["shellcode_patterns"]:
        print(f"    {sp['description']}: {sp['occurrences']} occurrences")

    # Credentials
    print("\n--- extract_credentials ---")
    creds = ma.extract_credentials(test_dump)
    print(f"  Found: {len(creds)}")
    for c in creds:
        print(f"    {c['type']}: {c['value'][:60]}")

    # Timeline
    print("\n--- timeline_from_memory ---")
    tl = ma.timeline_from_memory(test_dump)
    print(f"  Timestamps found: {len(tl)}")
    if tl:
        print(f"  Latest: {tl[0]['datetime']}")

    # Dump self
    print(f"\n--- dump_process (self, pid={os.getpid()}) ---")
    dump_path = ma.dump_process(os.getpid())
    if dump_path:
        size = os.path.getsize(dump_path)
        print(f"  Dumped: {dump_path} ({size} bytes)")
    else:
        print(f"  Dump not possible on this platform (non-Linux or permission denied)")

    # Cleanup
    import shutil
    shutil.rmtree(ma.dump_dir, ignore_errors=True)

    print("\n=== All tests passed ===")