"""Chain-of-thought thinking prompts for different task types."""

THINKING_PROMPTS = {
    "code": """
Think step by step about this coding task:
1. What is the exact requirement? What does "done" look like?
2. What approach? List 2-3 options with pros/cons.
3. Pick the best approach. Why this one?
4. Write the full implementation. No stubs.
5. Verify: does it handle edge cases? Errors? Is it testable?
""",

    "debug": """
Think step by step about this bug:
1. What is the symptom? What SHOULD happen instead?
2. Where could this originate? Trace the data/code flow.
3. What's your hypothesis? What would confirm it?
4. If confirmed: fix. If not: next hypothesis.
5. After fix: how do we prevent this class of bug?
""",

    "architecture": """
Think step by step about this architecture decision:
1. What are the constraints? (scale, budget, time, team)
2. What are the options? List 3+ with trade-offs.
3. What would happen if we chose wrong? What's the cost of reversal?
4. Pick the best option. Justify with data, not opinion.
5. What's the migration path? How do we get there from here?
""",

    "design": """
Think step by step about this design task:
1. Who is the user? What mental model do they have?
2. What's the core interaction? What's the ONE thing they need to do?
3. Sketch the layout. What's the visual hierarchy?
4. How does it feel? Fast? Delightful? Trustworthy?
5. Verify: would a new user understand this in 5 seconds?
""",

    "general": """
Think step by step:
1. What's the real question behind this question?
2. What do I know for certain? What am I assuming?
3. What would a world-class expert do?
4. What's the simplest answer that fully solves it?
5. How can I verify my answer is correct?
""",
}


def get_thinking_prompt(task_type: str = "general") -> str:
    """Return a chain-of-thought prompt for the given task type."""
    return THINKING_PROMPTS.get(task_type, THINKING_PROMPTS["general"])


def classify_task(user_input: str) -> str:
    """Quick heuristic to classify what kind of task this is."""
    text = user_input.lower()

    debug_words = ("bug", "error", "fix", "crash", "fail", "broken", "wrong")
    arch_words = ("architecture", "design pattern", "scale", "migrate", "refactor", "monolith", "microservice")
    design_words = ("ui", "ux", "design", "layout", "color", "style", "css", "look")
    code_words = ("code", "implement", "write", "build", "create", "function", "class", "api")

    if any(w in text for w in debug_words):
        return "debug"
    if any(w in text for w in arch_words):
        return "architecture"
    if any(w in text for w in design_words):
        return "design"
    if any(w in text for w in code_words):
        return "code"
    return "general"