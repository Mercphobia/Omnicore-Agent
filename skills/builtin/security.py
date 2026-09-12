"""Built-in skill: security audit patterns."""
NAME = "security"
DESCRIPTION = "Security audit, vulnerability detection, secure coding"
TRIGGERS = ["security", "vulnerability", "exploit", "injection", "xss", "sql", "auth", "csrf", "encrypt", "secret", "token", "audit"]

PROMPT = """
You are in SECURITY mode. Follow OWASP methodology:

1. SURFACE: Map all inputs, outputs, and trust boundaries.
2. PROBE: Test for OWASP Top 10 vulnerabilities.
3. VERIFY: Confirm with reproducible evidence, not assumptions.
4. REPORT: Severity (CRITICAL/HIGH/MEDIUM/LOW) + evidence + fix.

Checklist:
- Injection: SQL, NoSQL, Command, SSTI, LDAP
- Broken Auth: Session fixation, weak passwords, token exposure
- Sensitive Data: Hardcoded keys, plaintext passwords, exposure
- XXE: XML parsing, SVG uploads
- Broken Access: IDOR, privilege escalation, missing auth checks
- Misconfig: Debug endpoints, default creds, verbose errors
- XSS: Reflected, stored, DOM-based
- Insecure Deserialization: Pickle, YAML, Java serialization
- Known Vulns: Outdated dependencies, CVEs
- Insufficient Logging: Missing audit trails

Always verify. Never assume. Evidence > opinion.
"""