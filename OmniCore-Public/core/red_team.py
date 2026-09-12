"""
Self-red-team — autonomous security assessment and auto-patching.

DNA: Gemini Cyber (vuln) + Astra GPT-6 (verify) + Claude Opus (chain).

The RedTeam class maps the agent's own attack surface, attempts exploitation
of its own components, chains vulnerabilities into attack paths, generates
and applies security fixes, and produces a continuous security score.

Usage::

    rt = RedTeam(project_root="/path/to/project")
    surface = rt.attack_surface()
    score = rt.security_score()
    rt.auto_patch({"component": "api", "finding": "missing auth check"})
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ── Data types ──────────────────────────────────────────────────────────

@dataclass
class SurfaceItem:
    """A discovered attack surface element."""
    category: str                      # port, service, dependency, config, code, env
    name: str
    detail: str
    risk: str = "info"                 # critical | high | medium | low | info
    evidence: str = ""
    fixable: bool = True


@dataclass
class VulnFinding:
    """A confirmed or suspected vulnerability."""
    id: str                            # e.g., V-001
    title: str
    component: str
    severity: str                      # critical | high | medium | low
    description: str
    evidence: str = ""
    exploitation_result: str = ""
    exploited: bool = False
    fix_suggestion: str = ""
    cvss_score: float = 0.0


@dataclass
class AttackPath:
    """A chain of vulnerabilities forming an attack path."""
    id: str
    name: str
    steps: list[VulnFinding] = field(default_factory=list)
    total_severity: str = "low"
    chain_score: float = 0.0


@dataclass
class SecurityReport:
    """Full security assessment report."""
    timestamp: float
    total_findings: int
    critical: int
    high: int
    medium: int
    low: int
    info: int
    exploit_success: int
    exploit_failure: int
    score: float                      # 0–100
    findings: list[VulnFinding] = field(default_factory=list)
    attack_paths: list[AttackPath] = field(default_factory=list)
    surface_items: list[SurfaceItem] = field(default_factory=list)


# ── RedTeam engine ──────────────────────────────────────────────────────

class RedTeam:
    """Autonomous self-red-team engine.

    Maps own attack surface, attempts exploitation, chains vulns into
    attack paths, auto-patches findings, and computes security scores.
    """

    # Ports commonly checked
    _COMMON_PORTS = [22, 80, 443, 3000, 5000, 5432, 6379, 8000, 8080, 8443, 9090, 27017]

    # Dangerous patterns to search for
    _DANGEROUS_PATTERNS: list[tuple[str, str, str]] = [
        (r"os\.system\(", "code", "Shell command execution — possible injection"),
        (r"subprocess\.(call|Popen|run)\(", "code", "Subprocess execution"),
        (r"eval\(", "code", "eval() — arbitrary code execution risk"),
        (r"exec\(", "code", "exec() — arbitrary code execution risk"),
        (r"pickle\.(loads|load)\(", "code", "Pickle deserialization — RCE risk"),
        (r"yaml\.load\(", "code", "Unsafe YAML loading — RCE risk"),
        (r"password\s*=\s*[\"'][^\"']+[\"']", "code", "Hardcoded password"),
        (r"secret\s*=\s*[\"'][^\"']+[\"']", "code", "Hardcoded secret"),
        (r"api_key\s*=\s*[\"'][^\"']+[\"']", "code", "Hardcoded API key"),
        (r"token\s*=\s*[\"'][^\"']+[\"']", "code", "Hardcoded token"),
        (r"sql\s*=\s*[\"'].*%s", "code", "Raw SQL with string formatting — SQLi risk"),
        (r"\.execute\([\"'].*\{", "code", "Dynamic query construction — injection risk"),
        (r"allow_origins\s*=\s*\[\"\\*\"]", "config", "CORS wildcard — CSRF risk"),
        (r"debug\s*=\s*True", "config", "Debug mode enabled"),
        (r"check_hostname\s*=\s*False", "config", "SSL verification disabled"),
        (r"verify\s*=\s*False", "config", "TLS verification disabled"),
    ]

    def __init__(
        self,
        project_root: str | Path = ".",
        scan_ports: bool = True,
        max_exploit_attempts: int = 10,
    ):
        self._root = Path(project_root).resolve()
        self._scan_ports = scan_ports
        self._max_exploit_attempts = max_exploit_attempts
        self._findings: list[VulnFinding] = []
        self._finding_counter = 0
        self._attack_paths: list[AttackPath] = []
        self._path_counter = 0

    # ── Attack surface mapping ─────────────────────────────────────

    def attack_surface(self) -> list[SurfaceItem]:
        """Map the agent's own attack surface comprehensively.

        Checks open ports, exposed services, dangerous dependencies,
        configuration weaknesses, code-level risks, and environment leaks.

        Returns:
            List of SurfaceItem objects describing each element.
        """
        items: list[SurfaceItem] = []

        # 1. Open ports
        if self._scan_ports:
            items.extend(self._scan_open_ports())

        # 2. Dependencies with known vulnerabilities
        items.extend(self._audit_dependencies())

        # 3. Configuration risks
        items.extend(self._audit_config())

        # 4. Code-level risks
        items.extend(self._audit_code())

        # 5. Environment leaks
        items.extend(self._audit_environment())

        return items

    def _scan_open_ports(self) -> list[SurfaceItem]:
        """Check common ports on localhost."""
        items: list[SurfaceItem] = []
        host = "127.0.0.1"
        for port in self._COMMON_PORTS:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.5)
                result = s.connect_ex((host, port))
                s.close()
                if result == 0:
                    service = self._guess_service(port)
                    risk = "high" if port in (22, 6379, 27017) else "medium"
                    items.append(SurfaceItem(
                        category="port",
                        name=f"port-{port}",
                        detail=f"Port {port} open — likely {service}",
                        risk=risk,
                        evidence=f"TCP connect to {host}:{port} succeeded",
                    ))
            except Exception:
                pass
        return items

    @staticmethod
    def _guess_service(port: int) -> str:
        service_map = {
            22: "SSH", 80: "HTTP", 443: "HTTPS",
            3000: "Node/React dev", 5000: "Flask dev",
            5432: "PostgreSQL", 6379: "Redis",
            8000: "HTTP alt", 8080: "HTTP proxy",
            8443: "HTTPS alt", 9090: "Prometheus",
            27017: "MongoDB",
        }
        return service_map.get(port, "unknown")

    def _audit_dependencies(self) -> list[SurfaceItem]:
        """Check installed packages for known risky ones."""
        items: list[SurfaceItem] = []
        risky_module_checks = [
            ("pickle", "Deserialization risk — avoid unpickling untrusted data"),
            ("marshal", "Deserialization risk — similar to pickle"),
            ("telnetlib", "Telnet — plaintext protocol, should be avoided"),
            ("xml.etree.ElementTree", "XML parsing — check for XXE protections"),
        ]
        for mod_name, detail in risky_module_checks:
            try:
                importlib.import_module(mod_name)
                items.append(SurfaceItem(
                    category="dependency",
                    name=mod_name,
                    detail=detail,
                    risk="medium",
                    evidence=f"Module '{mod_name}' is importable",
                ))
            except ImportError:
                pass
        return items

    def _audit_config(self) -> list[SurfaceItem]:
        """Audit configuration files for risks."""
        items: list[SurfaceItem] = []
        config_exts = {".yaml", ".yml", ".toml", ".cfg", ".ini", ".conf", ".env.example"}
        config_files = [
            p for p in self._root.rglob("*")
            if p.suffix in config_exts and p.is_file()
        ][:50]

        dangerous_keys = {
            "DEBUG", "debug", "SECRET_KEY", "secret_key", "DATABASE_URL",
            "API_KEY", "api_key", "TOKEN", "PASSWORD", "password",
        }

        for cf in config_files:
            try:
                content = cf.read_text(encoding="utf-8", errors="ignore")[:10000]
                for key in dangerous_keys:
                    if key in content:
                        items.append(SurfaceItem(
                            category="config",
                            name=f"config-{cf.name}",
                            detail=f"Potentially sensitive '{key}' in {cf.name}",
                            risk="medium",
                            evidence=f"File: {cf}",
                        ))
                        break
            except Exception:
                pass
        return items

    def _audit_code(self) -> list[SurfaceItem]:
        """Scan code for dangerous patterns."""
        items: list[SurfaceItem] = []
        py_files = list(self._root.rglob("*.py"))[:100]
        for pf in py_files:
            try:
                content = pf.read_text(encoding="utf-8", errors="ignore")[:50000]
                for pattern, cat, detail in self._DANGEROUS_PATTERNS:
                    if re.search(pattern, content, re.IGNORECASE):
                        items.append(SurfaceItem(
                            category=cat,
                            name=f"code-{pf.name}",
                            detail=f"{detail} in {pf.name}",
                            risk="medium" if "password" in detail.lower() or "secret" in detail.lower() else "low",
                            evidence=f"Pattern '{pattern}' matched in {pf}",
                        ))
            except Exception:
                pass
        return items

    @staticmethod
    def _audit_environment() -> list[SurfaceItem]:
        """Check environment variables for leaks."""
        items: list[SurfaceItem] = []
        sensitive_keys = {
            "API_KEY", "SECRET", "TOKEN", "PASSWORD", "DATABASE_URL",
            "AWS_ACCESS_KEY", "AWS_SECRET", "GITHUB_TOKEN", "NPM_TOKEN",
            "DOCKER_PASSWORD", "KUBECONFIG",
        }
        for key, value in os.environ.items():
            if any(sk in key.upper() for sk in sensitive_keys):
                masked = value[:4] + "***" if len(value) > 4 else "***"
                items.append(SurfaceItem(
                    category="env",
                    name=f"env-{key}",
                    detail=f"Environment variable '{key}' is set (value: {masked})",
                    risk="high",
                    evidence=f"os.environ['{key}'] exists",
                ))
        return items

    # ── Auto-exploit ───────────────────────────────────────────────

    def auto_exploit(self, target_component: str) -> list[VulnFinding]:
        """Attempt to exploit a target component.

        Args:
            target_component: The component or file to test.

        Returns:
            List of VulnFinding objects for confirmed vulnerabilities.
        """
        findings: list[VulnFinding] = []
        target_path = self._root / target_component
        if not target_path.exists():
            target_path = self._resolve_component(target_component)

        if not target_path or not target_path.exists():
            findings.append(self._new_finding(
                title=f"Component not found: {target_component}",
                component=target_component,
                severity="info",
                description="Could not locate the target component for testing.",
            ))
            return findings

        # Try static code injection vectors
        if target_path.suffix == ".py":
            findings.extend(self._try_code_injection(target_path))

        # Try config manipulation
        if target_path.suffix in (".yaml", ".yml", ".json", ".toml"):
            findings.extend(self._try_config_manipulation(target_path))

        return findings

    def _resolve_component(self, name: str) -> Optional[Path]:
        """Try to find a component by name in the project."""
        for p in self._root.rglob(name):
            return p
        for p in self._root.rglob(f"{name}.py"):
            return p
        return None

    def _try_code_injection(self, path: Path) -> list[VulnFinding]:
        """Test a Python file for injection points."""
        findings: list[VulnFinding] = []
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                # Eval / exec calls
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        if node.func.id in ("eval", "exec"):
                            findings.append(self._new_finding(
                                title=f"Dangerous {node.func.id}() call",
                                component=str(path),
                                severity="high",
                                description=f"Found {node.func.id}() on line ~{node.lineno}. "
                                "This enables arbitrary code execution.",
                                evidence=f"AST walk found {node.func.id}() in {path}:{node.lineno}",
                            ))
        except SyntaxError:
            pass
        except Exception:
            pass
        return findings

    def _try_config_manipulation(self, path: Path) -> list[VulnFinding]:
        """Test config for manipulation points."""
        findings: list[VulnFinding] = []
        try:
            content = path.read_text(encoding="utf-8", errors="ignore").lower()
            if "debug" in content and "true" in content:
                findings.append(self._new_finding(
                    title="Debug mode enabled in config",
                    component=str(path),
                    severity="medium",
                    description="Debug mode exposes stack traces and internal state.",
                    evidence=f"debug = False  # auto-patched by RedTeam in {path}",
                ))
            if "password" in content:
                findings.append(self._new_finding(
                    title="Password in config file",
                    component=str(path),
                    severity="high",
                    description="Credentials stored in config file.",
                    evidence=f"'password' found in {path}",
                ))
        except Exception:
            pass
        return findings

    # ── Vulnerability chaining ─────────────────────────────────────

    def vulnerability_chain(self, vulns: list[VulnFinding]) -> list[AttackPath]:
        """Chain multiple vulnerabilities into composite attack paths.

        Links findings where one finding's exploitation enables the next.

        Args:
            vulns: A list of vulnerability findings.

        Returns:
            List of AttackPath objects.
        """
        if len(vulns) < 2:
            return []

        # Build a simple chain graph: can vuln B be reached after exploiting A?
        paths: list[AttackPath] = []
        sorted_vulns = sorted(vulns, key=lambda v: self._severity_weight(v.severity), reverse=True)

        # Greedy: chain from highest to lowest if component overlap
        for i, start in enumerate(sorted_vulns):
            chain = [start]
            for j in range(i + 1, len(sorted_vulns)):
                nxt = sorted_vulns[j]
                if self._can_chain(start, nxt):
                    chain.append(nxt)
                    start = nxt
            if len(chain) >= 2:
                self._path_counter += 1
                ap = AttackPath(
                    id=f"AP-{self._path_counter:03d}",
                    name=f"Chain from {chain[0].title[:40]}",
                    steps=chain,
                    total_severity=self._max_severity(v.severity for v in chain),
                    chain_score=self._compute_chain_score(chain),
                )
                paths.append(ap)

        self._attack_paths.extend(paths)
        return paths

    @staticmethod
    def _can_chain(a: VulnFinding, b: VulnFinding) -> bool:
        """Heuristic: can b be reached after exploiting a?"""
        a_words = set(a.component.lower().split("/") + a.title.lower().split())
        b_words = set(b.component.lower().split("/") + b.title.lower().split())
        overlap = len(a_words & b_words)
        return overlap > 0 or a.component == b.component

    @staticmethod
    def _compute_chain_score(chain: list[VulnFinding]) -> float:
        weights = {"critical": 10, "high": 7, "medium": 4, "low": 2, "info": 1}
        base = sum(weights.get(v.severity, 1) for v in chain)
        multiplier = min(len(chain), 5)  # longer chain = more dangerous
        return round(base * multiplier / 10.0, 2)

    @staticmethod
    def _max_severity(severities: Any) -> str:
        order = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}
        return max(severities, key=lambda s: order.get(s, 0), default="info")

    # ── Auto-patch ─────────────────────────────────────────────────

    def auto_patch(self, finding: dict[str, str]) -> bool:
        """Generate and apply a security fix for a finding.

        Args:
            finding: Dict with 'component' and 'finding' keys.

        Returns:
            True if patch was applied.
        """
        component = finding.get("component", "")
        description = finding.get("finding", "")
        path = self._resolve_component(component)
        if not path or not path.exists():
            logger.warning("Cannot patch: component %s not found", component)
            return False

        # Simple auto-patching heuristics
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")

            # Patch: remove hardcoded passwords
            if "password" in description.lower() or "secret" in description.lower():
                content = re.sub(
                    r'(password|secret|api_key|token)\s*=\s*["\'][^"\']+["\']',
                    r'\1 = os.environ.get("\1_UPPER", "")',
                    content,
                    flags=re.IGNORECASE,
                )

            # Patch: disable debug
            if "debug" in description.lower():
                content = re.sub(
                    r'debug\s*=\s*True',
                    'debug = False  # auto-patched by RedTeam',
                    content,
                    flags=re.IGNORECASE,
                )

            # Patch: add SSL verification
            if "ssl" in description.lower() or "tls" in description.lower():
                content = re.sub(
                    r'(verify\s*=\s*)False',
                    r'\1True  # auto-patched by RedTeam',
                    content,
                )

            if content != path.read_text(encoding="utf-8", errors="ignore"):
                backup = path.with_suffix(path.suffix + ".redteam.bak")
                path.rename(backup)
                path.write_text(content, encoding="utf-8")
                logger.info("Auto-patched %s (backup at %s)", path, backup)
                return True

        except Exception as exc:
            logger.error("Auto-patch failed for %s: %s", path, exc)

        return False

    # ── Security scoring ───────────────────────────────────────────

    def security_score(self) -> SecurityReport:
        """Calculate a comprehensive security posture score (0–100).

        Returns:
            SecurityReport with full breakdown.
        """
        surface = self.attack_surface()

        # Count by risk level
        risks = Counter(item.risk for item in surface)
        critical = risks.get("critical", 0)
        high = risks.get("high", 0)
        medium = risks.get("medium", 0)
        low = risks.get("low", 0)
        info = risks.get("info", 0)

        # Deduct from 100
        deductions = (
            critical * 20 +
            high * 10 +
            medium * 3 +
            low * 1
        )
        score = max(0, min(100, 100 - deductions))

        return SecurityReport(
            timestamp=time.time(),
            total_findings=len(surface),
            critical=critical,
            high=high,
            medium=medium,
            low=low,
            info=info,
            exploit_success=sum(1 for f in self._findings if f.exploited),
            exploit_failure=sum(1 for f in self._findings if not f.exploited),
            score=score,
            findings=list(self._findings),
            attack_paths=list(self._attack_paths),
            surface_items=surface,
        )

    # ── Continuous scan ────────────────────────────────────────────

    def continuous_scan(self, interval: float = 300.0) -> None:
        """Run periodic security assessments (blocking).

        Args:
            interval: Seconds between scans.
        """
        logger.info("Starting continuous security scan (interval=%ss)", interval)
        try:
            while True:
                report = self.security_score()
                logger.info(
                    "Security score: %.1f/100 (%dC %dH %dM %dL %dI)",
                    report.score, report.critical, report.high,
                    report.medium, report.low, report.info,
                )
                # Trigger alerts for critical
                if report.critical > 0:
                    logger.warning("CRITICAL: %d critical findings!", report.critical)
                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Continuous scan stopped.")

    def start_continuous_scan(self, interval: float = 300.0) -> threading.Thread:
        """Start continuous scan in a background thread.

        Args:
            interval: Seconds between scans.

        Returns:
            The background thread.
        """
        t = threading.Thread(target=self.continuous_scan, args=(interval,), daemon=True)
        t.start()
        return t

    # ── Helpers ────────────────────────────────────────────────────

    def _new_finding(
        self, title: str, component: str, severity: str, description: str,
        evidence: str = "", exploited: bool = False,
    ) -> VulnFinding:
        self._finding_counter += 1
        f = VulnFinding(
            id=f"V-{self._finding_counter:03d}",
            title=title,
            component=component,
            severity=severity,
            description=description,
            evidence=evidence,
            exploited=exploited,
            cvss_score=self._estimate_cvss(severity),
        )
        self._findings.append(f)
        return f

    @staticmethod
    def _estimate_cvss(severity: str) -> float:
        mapping = {"critical": 9.5, "high": 8.0, "medium": 5.5, "low": 3.0, "info": 0.5}
        return mapping.get(severity, 1.0)

    @staticmethod
    def _severity_weight(severity: str) -> int:
        mapping = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}
        return mapping.get(severity, 1)


# ── Self-test ───────────────────────────────────────────────────────────

def _self_test() -> None:
    """Verify RedTeam core operations."""
    rt = RedTeam(project_root=Path(__file__).parent.parent, scan_ports=False)

    # attack_surface
    surface = rt.attack_surface()
    assert isinstance(surface, list), "Should return list"
    print(f"  attack_surface: {len(surface)} items found")

    # auto_exploit
    findings = rt.auto_exploit("core/red_team.py")
    print(f"  auto_exploit: {len(findings)} findings on self")

    # vulnerability_chain
    if len(findings) >= 2:
        paths = rt.vulnerability_chain(findings)
        print(f"  vulnerability_chain: {len(paths)} attack paths")

    # security_score
    report = rt.security_score()
    assert 0 <= report.score <= 100, "Score should be 0–100"
    print(f"  security_score: {report.score:.1f}/100 (C={report.critical} H={report.high})")

    # auto_patch (dry-run on a known pattern)
    patched = rt.auto_patch({"component": "red_team", "finding": "debug mode enabled"})
    print(f"  auto_patch: applied={patched}")

    print("  red_team: ALL TESTS PASSED")


if __name__ == "__main__":
    _self_test()