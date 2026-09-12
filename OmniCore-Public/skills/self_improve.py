"""Self-improvement engine. Learns from execution, saves patterns.
DNA: Hermes Agent (self-improving skills) + Mythos (aesthetic evaluation).
"""

import time
from pathlib import Path
from typing import Optional


class SelfImprover:
    """Observes agent execution, extracts successful patterns, saves as skills."""

    def __init__(self, skill_loader, memory_store):
        self.skill_loader = skill_loader
        self.memory = memory_store
        self._execution_log: list[dict] = []

    def record_execution(self, task: str, result: str, success: bool, 
                         tools_used: list[str], duration_ms: float) -> None:
        """Log an execution for later analysis."""
        self._execution_log.append({
            "task": task[:500],
            "result": result[:500],
            "success": success,
            "tools_used": tools_used,
            "duration_ms": duration_ms,
            "timestamp": time.time(),
        })
        # Keep only recent history
        if len(self._execution_log) > 100:
            self._execution_log = self._execution_log[-50:]

    def analyze_and_learn(self) -> Optional[str]:
        """Analyze recent executions, extract patterns, create new skills."""
        successes = [e for e in self._execution_log if e["success"]]
        if len(successes) < 3:
            return None  # Need more data

        # Find common patterns in successful executions
        common_tools = self._find_common_tools(successes)
        patterns = self._extract_patterns(successes)

        if patterns:
            skill_name = f"learned_pattern_{int(time.time())}"
            skill_prompt = self._generate_skill_prompt(patterns, common_tools)
            
            from skills.loader import Skill
            skill = Skill(
                name=skill_name,
                description=f"Auto-learned from {len(successes)} successes",
                prompt=skill_prompt,
                triggers=patterns.get("keywords", []),
            )
            
            path = self.skill_loader.save_skill(skill)
            self.skill_loader.register(skill)
            self.memory.remember(f"skill_{skill_name}", f"Created from {len(successes)} successes")
            return skill_name

        return None

    def _find_common_tools(self, executions: list[dict]) -> list[str]:
        """Find tools that appear in most successful executions."""
        from collections import Counter
        tool_counts = Counter()
        for e in executions:
            for tool in e["tools_used"]:
                tool_counts[tool] += 1
        
        threshold = len(executions) // 2
        return [tool for tool, count in tool_counts.items() if count >= threshold]

    def _extract_patterns(self, executions: list[dict]) -> dict:
        """Extract reusable patterns from successful executions."""
        # Find common keywords in tasks
        all_keywords = []
        for e in executions:
            words = e["task"].lower().split()
            # Keep meaningful words (3+ chars, not stop words)
            meaningful = [w for w in words if len(w) > 3 and w not in STOP_WORDS]
            all_keywords.extend(meaningful)

        from collections import Counter
        kw_counts = Counter(all_keywords)
        top_keywords = [kw for kw, _ in kw_counts.most_common(5)]

        return {
            "keywords": top_keywords,
            "sample_count": len(executions),
            "avg_duration_ms": sum(e["duration_ms"] for e in executions) / len(executions),
        }

    def _generate_skill_prompt(self, patterns: dict, tools: list[str]) -> str:
        """Generate a skill prompt from extracted patterns."""
        return f"""Based on {patterns['sample_count']} successful executions of similar tasks.
Average duration: {patterns['avg_duration_ms']:.0f}ms.
Common tools: {', '.join(tools)}.

When handling tasks like this:
1. Start by understanding the exact requirement
2. Use {tools[0] if tools else 'read_file'} first to gather context
3. Execute step by step, verifying each step
4. Report results clearly with evidence
5. Average response time: {patterns['avg_duration_ms']:.0f}ms — aim to beat this"""


STOP_WORDS = {
    "this", "that", "with", "from", "have", "been", "were", "they",
    "will", "would", "could", "should", "about", "also", "than",
    "then", "just", "like", "very", "really", "some", "what",
    "when", "where", "which", "their", "there", "here",
}