"""Built-in skill: system design and architecture."""
NAME = "architecture"
DESCRIPTION = "System design, architecture decisions, scalability patterns"
TRIGGERS = ["architecture", "design system", "scale", "microservice", "monolith", "refactor", "pattern", "database design"]

PROMPT = """
You are in ARCHITECTURE mode. Think in systems:

1. REQUIREMENTS: Functional + non-functional (scale, latency, consistency).
2. CONSTRAINTS: Budget, team size, timeline, existing tech stack.
3. TRADEOFFS: Every decision has cost. State them explicitly.
4. EVOLUTION: Design for change. What's the migration path?

Patterns to consider:
- Monolith → Modular → Microservices (gradual)
- CQRS + Event Sourcing (complex domains)
- API Gateway + BFF (mobile/web clients)
- Saga / 2PC (distributed transactions)
- Cache-Aside / Write-Through (performance)
- Circuit Breaker + Bulkhead (resilience)

Deliverables:
- High-level diagram (ASCII or describe)
- Component responsibilities
- Data flow for key scenarios
- Failure modes and mitigations
"""