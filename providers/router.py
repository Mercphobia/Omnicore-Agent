"""Provider router — auto-select best model per task type.
DNA: Astra (hyper-agentic routing) + Gemini Flash (fast triage).
"""


ROUTING_RULES = {
    "code": {
        "primary": "anthropic/claude-sonnet",
        "fallback": "openai/gpt-4o",
        "reason": "Claude excels at code generation and reasoning",
    },
    "debug": {
        "primary": "anthropic/claude-sonnet", 
        "fallback": "openai/gpt-4o",
        "reason": "Deep reasoning for debugging",
    },
    "architecture": {
        "primary": "anthropic/claude-sonnet",
        "fallback": "openai/gpt-4o",
        "reason": "Extended thinking for architecture decisions",
    },
    "design": {
        "primary": "openai/gpt-4o",
        "fallback": "anthropic/claude-sonnet",
        "reason": "GPT-4o has strong visual design capabilities",
    },
    "simple": {
        "primary": "google/gemini-2.5-flash",
        "fallback": "deepseek/deepseek-chat",
        "reason": "Fast + cheap for simple queries",
    },
    "research": {
        "primary": "anthropic/claude-sonnet",
        "fallback": "openai/gpt-4o",
        "reason": "Long context for research synthesis",
    },
    "general": {
        "primary": "anthropic/claude-sonnet",
        "fallback": "openai/gpt-4o",
        "reason": "Best all-rounder",
    },
}


class Router:
    """Routes tasks to the optimal model based on task type and context."""

    def __init__(self, config: dict):
        self.config = config
        self.router_config = config.get("router", {})
        self.smart_model = self.router_config.get("smart_model", "anthropic/claude-sonnet")
        self.fast_model = self.router_config.get("fast_model", "google/gemini-2.5-flash")
        self.cheap_model = self.router_config.get("cheap_model", "deepseek/deepseek-chat")
        self.auto_select = self.router_config.get("auto_select", True)

    def route(self, user_input: str, task_type: str | None = None) -> dict:
        """Return the best model for this task."""
        if not self.auto_select:
            return {"model": self.smart_model, "reason": "Auto-select disabled"}

        # Classify task
        if task_type is None:
            task_type = self._classify(user_input)

        # Check routing rules
        rule = ROUTING_RULES.get(task_type, ROUTING_RULES["general"])
        model = rule["primary"]

        # Override with cheap model for very simple queries
        if len(user_input.split()) < 5:
            model = self.fast_model
            rule["reason"] = "Short query → fast model"

        return {
            "model": model,
            "fallback": rule["fallback"],
            "reason": rule["reason"],
            "task_type": task_type,
        }

    def _classify(self, text: str) -> str:
        """Classify task type from user input."""
        t = text.lower()

        # Heuristic classification
        code_words = {"code", "implement", "function", "class", "api", "write", "build", "create"}
        debug_words = {"bug", "error", "fix", "crash", "broken", "debug", "trace"}
        arch_words = {"architecture", "design pattern", "scale", "refactor", "monolith", "microservice"}
        design_words = {"ui", "ux", "design", "layout", "color", "css", "style", "look"}
        research_words = {"research", "analyze", "compare", "review", "survey", "benchmark"}

        scores = {
            "code": sum(1 for w in code_words if w in t),
            "debug": sum(1 for w in debug_words if w in t),
            "architecture": sum(1 for w in arch_words if w in t),
            "design": sum(1 for w in design_words if w in t),
            "research": sum(1 for w in research_words if w in t),
        }

        best = max(scores, key=scores.get)
        if scores[best] > 0:
            return best

        # Short queries → simple
        if len(text.split()) < 5:
            return "simple"

        return "general"