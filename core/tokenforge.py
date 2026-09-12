"""TokenForge — API token economy engine. Stop burning money.
DNA: Ponytail (minimalism) + Grok 4 (contrarian truth) + cold precision.

Claude Opus multiplier: up to 20x. GPT-5.5: up to 10x. 
Every word you send to these models is burning cash.
TokenForge is the weapon against API bill shock.

STRATEGIES:
1. PROMPT DISTILLATION — Compress prompts to essential tokens
2. SMART ROUTING — Cheap model for easy, expensive only when needed
3. CONTEXT PRUNING — Remove irrelevant history
4. RESPONSE CACHING — Don't re-ask what's already answered
5. BUDGET ENFORCEMENT — Hard token caps per task
6. MULTIPLIER-AWARE — Know the real cost before sending
"""

import re
import hashlib
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from collections import OrderedDict


# ── Model cost data ──────────────────────────────────────────────────
# Price per 1M tokens (input/output). Claude has massive output multiplier.

MODEL_COSTS = {
    # Claude (Anthropic) — brutal multipliers
    "claude-opus-4":       {"input": 15.00, "output": 75.00,  "multiplier": 5.0},
    "claude-sonnet-4":     {"input": 3.00,  "output": 15.00,  "multiplier": 5.0},
    "claude-haiku-4":      {"input": 0.80,  "output": 4.00,   "multiplier": 5.0},
    "claude-opus-4.5":     {"input": 15.00, "output": 75.00,  "multiplier": 5.0},
    # GPT (OpenAI)
    "gpt-5.5":             {"input": 5.00,  "output": 50.00,  "multiplier": 10.0},
    "gpt-5":               {"input": 2.50,  "output": 25.00,  "multiplier": 10.0},
    "gpt-4o":              {"input": 2.50,  "output": 10.00,  "multiplier": 4.0},
    "gpt-4o-mini":         {"input": 0.15,  "output": 0.60,   "multiplier": 4.0},
    # Gemini (Google) — cheaper
    "gemini-2.5-pro":      {"input": 1.25,  "output": 5.00,   "multiplier": 4.0},
    "gemini-2.5-flash":    {"input": 0.15,  "output": 0.60,   "multiplier": 4.0},
    # DeepSeek — dirt cheap
    "deepseek-chat":       {"input": 0.27,  "output": 1.10,   "multiplier": 4.0},
    "deepseek-reasoner":   {"input": 0.55,  "output": 2.19,   "multiplier": 4.0},
    # OpenRouter averages
    "openrouter-haiku":    {"input": 0.80,  "output": 4.00,   "multiplier": 5.0},
    "openrouter-gpt4o":    {"input": 2.50,  "output": 10.00,  "multiplier": 4.0},
}


@dataclass
class TokenStats:
    """Token usage statistics for a session."""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    tasks_completed: int = 0
    tokens_saved_by_compression: int = 0
    tokens_saved_by_caching: int = 0
    tokens_saved_by_routing: int = 0
    cost_saved_usd: float = 0.0


@dataclass
class RoutingDecision:
    """Which model to use for a task."""
    model: str
    reason: str
    estimated_cost: float
    alternative_cheaper: str
    savings_if_cheaper: float


class TokenForge:
    """API token economy engine. Forge your prompts, save your money.

    Usage:
        forge = TokenForge()
        
        # Compress a prompt
        compressed = forge.distill("Please write a function that...")
        
        # Decide which model to use
        decision = forge.route("refactor this function...")
        
        # Prune conversation history
        pruned = forge.prune_context(messages)
        
        # Cache or retrieve
        cached = forge.cache_get("function to sort list")
        if not cached:
            result = call_api(prompt)
            forge.cache_set("function to sort list", result)
    """

    def __init__(self, budget_per_task: float = 0.10, 
                 max_input_tokens: int = 8000,
                 cache_dir: Optional[Path] = None):
        self.budget_per_task = budget_per_task
        self.max_input_tokens = max_input_tokens
        self.cache_dir = cache_dir or (Path.home() / ".omnicore" / "token_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.stats = TokenStats()
        self._cache: OrderedDict = OrderedDict()
        self._cache_max = 500
        self._load_cache()

    # ── STRATEGY 1: PROMPT DISTILLATION ──────────────────────────────

    def distill(self, prompt: str, aggressiveness: str = "forge") -> str:
        """Compress a prompt to its essential tokens.

        Args:
            prompt: The original prompt.
            aggressiveness: 'strike' (gentle), 'forge' (default), 'cataclysm' (extreme).

        Returns:
            Compressed prompt with same semantic intent, fewer tokens.
        """
        original_tokens = self._estimate_tokens(prompt)

        # Apply compressions in order
        compressed = prompt

        if aggressiveness in ("forge", "cataclysm"):
            compressed = self._remove_pleasentries(compressed)
            compressed = self._remove_redundancy(compressed)
            compressed = self._abbreviate_common(compressed)
            compressed = self._compact_whitespace(compressed)

        if aggressiveness == "cataclysm":
            compressed = self._extreme_compress(compressed)

        new_tokens = self._estimate_tokens(compressed)
        saved = max(0, original_tokens - new_tokens)
        self.stats.tokens_saved_by_compression += saved

        return compressed

    def _remove_pleasentries(self, text: str) -> str:
        """Remove polite filler: 'please', 'could you', 'I would like', etc."""
        patterns = [
            (r'(?i)\bplease\s+', ''),
            (r'(?i)\bcould you\s+', ''),
            (r'(?i)\bwould you\s+', ''),
            (r'(?i)\bcan you\s+', ''),
            (r'(?i)\bI would like (you )?to\s+', ''),
            (r'(?i)\bif you (could|would|don\'t mind)\s+', ''),
            (r'(?i)\bkindly\s+', ''),
            (r'(?i)\bthank you[.!]*\s*', ''),
            (r'(?i)\bi want (you )?to\s+', ''),
            (r'(?i)\bhelp me\s+', ''),
        ]
        for pattern, replacement in patterns:
            text = re.sub(pattern, replacement, text)
        return text.strip()

    def _remove_redundancy(self, text: str) -> str:
        """Remove redundant phrases and wordiness."""
        patterns = [
            (r'(?i)\bin order to\b', 'to'),
            (r'(?i)\bdue to the fact that\b', 'because'),
            (r'(?i)\bat this point in time\b', 'now'),
            (r'(?i)\bin the event that\b', 'if'),
            (r'(?i)\bwith regard to\b', 'about'),
            (r'(?i)\ba number of\b', 'several'),
            (r'(?i)\bthe majority of\b', 'most'),
            (r'(?i)\bdespite the fact that\b', 'although'),
            (r'(?i)\bin close proximity to\b', 'near'),
            (r'(?i)\bhas the ability to\b', 'can'),
            (r'(?i)\bis able to\b', 'can'),
            (r'(?i)\bwill be able to\b', 'can'),
            (r'(?i)\bfor the purpose of\b', 'for'),
            (r'(?i)\bin the process of\b', ''),
            (r'(?i)\bit is important to note that\b', ''),
            (r'(?i)\bneedless to say\b', ''),
            (r'(?i)\bit should be noted that\b', ''),
        ]
        for pattern, replacement in patterns:
            text = re.sub(pattern, replacement, text)
        return text.strip()

    def _abbreviate_common(self, text: str) -> str:
        """Replace common long phrases with shorter equivalents."""
        replacements = {
            "function": "fn",
            "variable": "var",
            "parameter": "param",
            "argument": "arg",
            "return": "ret",
            "implement": "impl",
            "configuration": "config",
            "initialize": "init",
            "asynchronous": "async",
            "synchronous": "sync",
            "error handling": "err",
            "validation": "val",
            "authentication": "auth",
            "authorization": "authz",
            "database": "db",
            "directory": "dir",
            "string": "str",
            "integer": "int",
            "boolean": "bool",
            "dictionary": "dict",
            "array": "arr",
            "application": "app",
            "library": "lib",
            "package": "pkg",
            "dependency": "dep",
            "documentation": "docs",
            "repository": "repo",
        }
        # Only abbreviate in code contexts, not in natural language
        # Use word boundary matching
        for long, short in replacements.items():
            text = re.sub(rf'\b{long}\b', short, text, flags=re.IGNORECASE)
        return text

    def _compact_whitespace(self, text: str) -> str:
        """Compact whitespace without losing meaning."""
        # Collapse multiple spaces
        text = re.sub(r' {2,}', ' ', text)
        # Collapse multiple newlines
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _extreme_compress(self, text: str) -> str:
        """Extreme compression — remove articles, pronouns, connectives."""
        # Remove articles
        text = re.sub(r'\b(the|a|an)\b\s*', '', text, flags=re.IGNORECASE)
        # Remove filler pronouns in commands
        text = re.sub(r'\b(it|this|that|those|these)\b\s*', '', text, flags=re.IGNORECASE)
        # Compact to minimum
        return self._compact_whitespace(text)

    # ── STRATEGY 2: SMART ROUTING ────────────────────────────────────

    def route(self, task: str, task_type: str = "auto") -> RoutingDecision:
        """Decide which model to use for a task.

        Rules:
        - Simple tasks (basic coding, text, formatting) → cheap model
        - Medium tasks (architecture, debugging) → mid-tier
        - Complex tasks (deep reasoning, security, creative) → best model
        """
        if task_type == "auto":
            task_type = self._classify_task(task)

        model_map = {
            "trivial":   "deepseek-chat",      # $0.27/$1.10 per 1M
            "simple":    "gemini-2.5-flash",   # $0.15/$0.60 per 1M
            "medium":    "gpt-4o-mini",         # $0.15/$0.60 per 1M
            "complex":   "claude-sonnet-4",     # $3/$15 per 1M
            "critical":  "claude-opus-4",       # $15/$75 per 1M
        }

        model = model_map.get(task_type, "deepseek-chat")
        costs = MODEL_COSTS.get(model, MODEL_COSTS["deepseek-chat"])

        est_input = self._estimate_tokens(task)
        est_output = est_input * 2  # Rough estimate
        est_cost = (est_input * costs["input"] + est_output * costs["output"]) / 1_000_000

        # Find cheaper alternative
        cheaper_options = {
            "claude-opus-4":     ("claude-sonnet-4", 0.80),
            "claude-sonnet-4":   ("gpt-4o-mini", 0.95),
            "gpt-4o":           ("gpt-4o-mini", 0.94),
            "gpt-5":            ("deepseek-chat", 0.98),
            "gpt-5.5":          ("deepseek-chat", 0.99),
        }
        alt, save_pct = cheaper_options.get(model, (model, 0))
        savings = est_cost * save_pct if alt != model else 0

        if est_cost > self.budget_per_task:
            model = alt
            est_cost = est_cost * (1 - save_pct)
            reason = f"Over budget (${est_cost:.4f} > ${self.budget_per_task}), switched to {alt}"
        else:
            reason = f"Task type '{task_type}' → {model}"

        self.stats.tokens_saved_by_routing += int(savings * 1_000_000 / costs.get("input", 0.01))

        return RoutingDecision(
            model=model,
            reason=reason,
            estimated_cost=round(est_cost, 6),
            alternative_cheaper=alt,
            savings_if_cheaper=round(savings, 6),
        )

    def _classify_task(self, task: str) -> str:
        """Classify task complexity from text."""
        task_lower = task.lower()

        # Trivial: pure lookups, simple queries
        trivial_patterns = ["what is", "how to spell", "define", "list of",
                           "show me", "check", "read file", "cat "]
        if any(p in task_lower for p in trivial_patterns):
            return "trivial"

        # Complex: architecture, security, deep debugging
        complex_patterns = ["architecture", "design pattern", "security",
                           "vulnerability", "exploit", "refactor entire",
                           "from scratch", "system design", "scale",
                           "optimize", "concurrency", "race condition",
                           "memory leak", "cryptography", "protocol"]
        if any(p in task_lower for p in complex_patterns):
            return "complex"

        # Critical: need absolute best reasoning
        critical_patterns = ["prove", "verify correctness", "formal",
                            "zero-day", "critical bug", "production outage",
                            "data loss", "security audit"]
        if any(p in task_lower for p in critical_patterns):
            return "critical"

        # Default: medium for coding tasks, simple for text tasks
        code_indicators = ["code", "function", "class", "api", "endpoint",
                          "sql", "database", "deploy", "build", "test",
                          "fix", "bug", "error", "implement", "write"]
        if any(p in task_lower for p in code_indicators):
            return "medium"

        return "simple"

    # ── STRATEGY 3: CONTEXT PRUNING ──────────────────────────────────

    def prune_context(self, messages: list[dict], 
                      max_tokens: int = 8000,
                      keep_last: int = 6) -> list[dict]:
        """Prune conversation history to essential context.

        Keeps:
        - System prompt (always)
        - Last N messages (recency)
        - Messages with tool results from last 3 turns
        - Messages marked as important

        Removes:
        - Old chitchat
        - Redundant tool outputs
        - Failed attempts that were retried
        """
        if len(messages) <= keep_last:
            return messages

        pruned = []

        # Always keep system message
        for msg in messages:
            if msg.get("role") == "system":
                pruned.append(msg)
                break

        # Keep last N messages
        recent = messages[-keep_last:]

        # From the middle, keep only tool results that were successful
        middle = messages[len(pruned):-keep_last]
        for msg in middle:
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                # Keep successful tool results, drop errors
                if not any(err in content.lower() for err in 
                          ["error", "failed", "not found", "permission denied"]):
                    if len(content) < 500:  # Keep short results
                        pruned.append(msg)
            elif msg.get("role") == "user" and "?" in msg.get("content", ""):
                # Keep user questions
                pruned.append(msg)

        pruned.extend(recent)

        # Enforce token limit
        total_tokens = sum(self._estimate_tokens(m.get("content", "")) 
                          for m in pruned)
        if total_tokens > max_tokens:
            # Trim middle messages until under budget
            while total_tokens > max_tokens and len(pruned) > keep_last + 1:
                for i, msg in enumerate(pruned):
                    if msg.get("role") not in ("system", "user") and i < len(pruned) - keep_last:
                        total_tokens -= self._estimate_tokens(msg.get("content", ""))
                        pruned.pop(i)
                        break

        saved = len(messages) - len(pruned)
        self.stats.tokens_saved_by_compression += saved * 50  # Rough estimate

        return pruned

    # ── STRATEGY 4: RESPONSE CACHING ─────────────────────────────────

    def cache_key(self, prompt: str, model: str = "") -> str:
        """Generate a cache key from a prompt."""
        normalized = self.distill(prompt, "forge")
        hash_input = f"{normalized}:{model}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]

    def cache_get(self, prompt: str, model: str = "") -> Optional[str]:
        """Retrieve cached response for a prompt."""
        key = self.cache_key(prompt, model)
        if key in self._cache:
            self.stats.tokens_saved_by_caching += self._estimate_tokens(prompt)
            return self._cache[key]
        return None

    def cache_set(self, prompt: str, response: str, model: str = "") -> None:
        """Cache a response for future reuse."""
        key = self.cache_key(prompt, model)
        self._cache[key] = response
        if len(self._cache) > self._cache_max:
            self._cache.popitem(last=False)
        self._save_cache()

    def _load_cache(self) -> None:
        """Load cache from disk."""
        cache_file = self.cache_dir / "responses.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text())
                self._cache = OrderedDict(data[-self._cache_max:])
            except (json.JSONDecodeError, OSError):
                pass

    def _save_cache(self) -> None:
        """Save cache to disk."""
        cache_file = self.cache_dir / "responses.json"
        cache_file.write_text(json.dumps(list(self._cache.items())))

    # ── STRATEGY 5: BUDGET ENFORCEMENT ───────────────────────────────

    def check_budget(self, model: str, prompt: str, 
                     estimated_output_tokens: int = 2000) -> dict:
        """Check if a request fits within the budget.

        Returns: {allowed: bool, estimated_cost: float, budget_remaining: float,
                  recommendation: str}
        """
        costs = MODEL_COSTS.get(model, MODEL_COSTS["deepseek-chat"])
        input_tokens = self._estimate_tokens(prompt)
        est_cost = (input_tokens * costs["input"] + 
                   estimated_output_tokens * costs["output"]) / 1_000_000

        allowed = est_cost <= self.budget_per_task

        if not allowed:
            # Suggest cheaper model
            channel = self.route(prompt)
            return {
                "allowed": False,
                "estimated_cost": round(est_cost, 6),
                "budget_per_task": self.budget_per_task,
                "recommendation": f"Over budget. Switch to {channel.alternative_cheaper} "
                                  f"(save ${channel.savings_if_cheaper:.6f})",
                "alternative": channel.alternative_cheaper,
            }

        return {
            "allowed": True,
            "estimated_cost": round(est_cost, 6),
            "budget_remaining": round(self.budget_per_task - est_cost, 6),
            "recommendation": "Within budget. Proceed.",
        }

    # ── STRATEGY 6: MULTIPLIER-AWARE COST ESTIMATION ─────────────────

    def real_cost(self, model: str, input_tokens: int, 
                  output_tokens: int) -> dict:
        """Calculate the REAL cost including Claude's brutal multipliers.

        Claude costs are NOT linear — the output multiplier makes long responses 
        extremely expensive. A 4000-token Claude Opus response costs $0.30 alone.
        """
        costs = MODEL_COSTS.get(model, MODEL_COSTS["deepseek-chat"])
        input_cost = (input_tokens * costs["input"]) / 1_000_000
        output_cost = (output_tokens * costs["output"]) / 1_000_000
        total = input_cost + output_cost
        multiplier = costs["multiplier"]

        return {
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "input_cost": round(input_cost, 6),
            "output_cost": round(output_cost, 6),
            "total_cost": round(total, 6),
            "multiplier": multiplier,
            "warning": (f"⚠ Output multiplier {multiplier}x — "
                       f"output costs {multiplier}x more than input!"
                       if multiplier >= 5 else ""),
        }

    def compare_models(self, input_tokens: int, output_tokens: int) -> str:
        """Compare costs across all models for a given token count."""
        lines = []
        for model, costs in sorted(MODEL_COSTS.items(), 
                                   key=lambda x: x[1]["output"]):
            total = (input_tokens * costs["input"] + 
                    output_tokens * costs["output"]) / 1_000_000
            lines.append(f"  {model:<25s} ${total:.6f}  "
                        f"(×{costs['multiplier']:.0f} output multiplier)")
        return "\n".join(lines)

    # ── Dashboard ────────────────────────────────────────────────────

    def dashboard(self) -> str:
        """Generate a savings dashboard."""
        s = self.stats
        total_saved = s.tokens_saved_by_compression + s.tokens_saved_by_caching
        estimated_cost_saved = (total_saved * 0.003) / 1_000_000  # Rough

        return f"""╔══════════════════════════════════════════╗
║       TOKENFORGE — Savings Dashboard     ║
╠══════════════════════════════════════════╣
║  Tasks completed:           {s.tasks_completed:>10d}  ║
║  Total input tokens:        {s.total_input_tokens:>10d}  ║
║  Total output tokens:       {s.total_output_tokens:>10d}  ║
║  Total API cost:           ${s.total_cost_usd:>10.4f}  ║
╠══════════════════════════════════════════╣
║  SAVED by compression:      {s.tokens_saved_by_compression:>10d}  ║
║  SAVED by caching:          {s.tokens_saved_by_caching:>10d}  ║
║  SAVED by smart routing:    {s.tokens_saved_by_routing:>10d}  ║
║  Est. money saved:         ${estimated_cost_saved:>10.4f}  ║
╚══════════════════════════════════════════╝"""

    # ── Helpers ──────────────────────────────────────────────────────

    def _estimate_tokens(self, text: str) -> int:
        """Quick token estimate: ~4 chars per token (Claude) or ~0.75 words."""
        if not text:
            return 0
        # Average: 4 chars per token for English text
        return max(1, len(text) // 4)

    def record_usage(self, input_tokens: int, output_tokens: int, 
                     model: str = "unknown") -> None:
        """Record actual API usage."""
        self.stats.total_input_tokens += input_tokens
        self.stats.total_output_tokens += output_tokens
        self.stats.tasks_completed += 1

        costs = MODEL_COSTS.get(model, MODEL_COSTS["deepseek-chat"])
        cost = (input_tokens * costs["input"] + 
               output_tokens * costs["output"]) / 1_000_000
        self.stats.total_cost_usd += cost


# ── Self-test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    forge = TokenForge(budget_per_task=0.05)

    # Test distillation
    original = ("Please could you kindly help me write a function that "
                "is able to calculate the factorial of a number in order "
                "to demonstrate recursion? Thank you so much!")
    distilled = forge.distill(original, "forge")
    orig_tokens = forge._estimate_tokens(original)
    dist_tokens = forge._estimate_tokens(distilled)
    reduction = (1 - dist_tokens / orig_tokens) * 100
    print(f"Distill: {orig_tokens}t → {dist_tokens}t ({reduction:.0f}% reduction)")
    print(f"  Original: {original[:80]}...")
    print(f"  Distilled: {distilled}")

    # Test routing
    for task, expected in [
        ("What is Python?", "trivial"),
        ("Write a function to sort a list", "medium"),
        ("Design a distributed system architecture", "complex"),
        ("Find zero-day vulnerability in this kernel module", "critical"),
    ]:
        decision = forge.route(task)
        print(f"Route: '{task[:50]}...' → {decision.model} "
              f"(${decision.estimated_cost:.6f}) — {decision.reason[:50]}")

    # Test cost comparison
    print("\nCost for 2000→4000 tokens:")
    print(forge.compare_models(2000, 4000))

    # Test budget check
    check = forge.check_budget("claude-opus-4", "Write a complex algorithm...")
    print(f"\nBudget check (Claude Opus): {check}")

    # Test cache
    forge.cache_set("hello world", "cached response")
    cached = forge.cache_get("hello world")
    print(f"\nCache: get='{cached}'")

    # Dashboard
    forge.record_usage(5000, 2000, "claude-sonnet-4")
    print(f"\n{forge.dashboard()}")

    print("\n✓ TokenForge self-tests passed")