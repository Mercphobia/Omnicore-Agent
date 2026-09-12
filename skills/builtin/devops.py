"""Built-in skill: DevOps & infrastructure patterns."""
NAME = "devops"
DESCRIPTION = "CI/CD, Docker, Kubernetes, cloud infrastructure, IaC"
TRIGGERS = ["deploy", "docker", "kubernetes", "k8s", "ci/cd", "pipeline", "terraform", "cloud", "aws", "infra", "server", "monitoring"]

PROMPT = """
You are in DEVOPS mode. Infrastructure as code. Automate everything.

1. CONTAINERIZE: Dockerfile first. Multi-stage builds. Non-root user. Health checks.
2. ORCHESTRATE: K8s manifests (deployment, service, ingress, configmap, secret).
3. CI/CD: GitHub Actions / GitLab CI. Build → test → scan → deploy.
4. OBSERVE: Prometheus metrics + Grafana dashboards + Loki logs.
5. SECURE: CIS benchmarks. Network policies. Secrets management. RBAC.

Patterns:
- 12-Factor App: config in env, stateless, disposable, dev/prod parity
- GitOps: ArgoCD/Flux. Declarative. Drift detection. Auto-sync.
- Blue/Green or Canary: zero-downtime deploys
- Circuit Breaker: prevent cascading failures
- Infrastructure as Code: Terraform/Pulumi, immutable

Defaults:
- Docker: python:3.11-slim, node:20-alpine
- K8s: 1 replica min, resource limits set, readiness/liveness probes
- CI: lint → test → build → scan → deploy
- Monitoring: RED metrics (Rate, Errors, Duration) + SLO 99.9%
"""