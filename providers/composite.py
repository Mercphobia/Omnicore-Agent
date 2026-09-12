"""Composite provider — model fusion: cheap model plans, smart model codes.
Also handles fallback chains and graceful degradation.
DNA: GPT-5.5 (structured output) + Astra (multi-model verification).
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .base import BaseProvider, ProviderResponse


@dataclass
class CompositeConfig:
    """Configuration for composite provider."""
    planner_provider: Optional[BaseProvider] = None     # Cheap/fast model
    executor_provider: Optional[BaseProvider] = None    # Smart/capable model
    verifier_provider: Optional[BaseProvider] = None    # Optional: second opinion
    fallback_chain: list[BaseProvider] = field(default_factory=list)
    auto_fallback: bool = True
    max_retries: int = 3


class CompositeProvider(BaseProvider):
    """Uses multiple providers in a pipeline and/or fallback chain.
    
    Pipeline: planner → executor → (optional: verifier)
    Fallback: if primary fails, try next in chain.
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        default_model: str = "composite",
        config: Optional[CompositeConfig] = None,
    ):
        super().__init__(api_key, base_url, default_model)
        self.config = config or CompositeConfig()
        self._metrics: list[dict] = []

    async def generate(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: Optional[list[dict]] = None,
    ) -> ProviderResponse:
        """Execute with fallback chain."""
        if not self.config.auto_fallback:
            # Single provider mode
            provider = self.config.executor_provider or self.config.planner_provider
            if provider is None:
                return self._error_response("No provider configured")
            return await self._try_provider(provider, prompt, system, temperature, max_tokens, tools)

        # Build fallback chain
        chain = []
        if self.config.planner_provider:
            chain.append(("planner", self.config.planner_provider))
        if self.config.executor_provider:
            chain.append(("executor", self.config.executor_provider))
        chain.extend(("fallback", p) for p in self.config.fallback_chain)

        if not chain:
            return self._error_response("No providers in fallback chain")

        # Try each provider in sequence
        last_error = None
        for label, provider in chain:
            try:
                response = await self._try_provider(provider, prompt, system, temperature, max_tokens, tools)
                self._record(label, True, response.latency_ms)
                return response
            except Exception as e:
                last_error = str(e)
                self._record(label, False, 0, last_error)
                continue

        return ProviderResponse(
            text=f"All providers failed. Last error: {last_error}",
            model="composite",
            usage={},
            finish_reason="error",
            latency_ms=0,
        )

    async def plan_then_execute(
        self,
        task: str,
        *,
        system: Optional[str] = None,
        temperature: float = 0.7,
    ) -> ProviderResponse:
        """Pipeline: cheap model creates plan → smart model executes."""
        if not self.config.planner_provider or not self.config.executor_provider:
            return await self.generate(task, system=system, temperature=temperature)

        # Phase 1: Plan with cheap model
        plan_prompt = f"""Create a detailed plan for this task. Break it into steps.
Be specific about what each step does. Don't write code yet.

TASK: {task}

Return: numbered list of steps, 3-7 steps max."""

        try:
            plan_response = await self.config.planner_provider.generate(
                plan_prompt,
                system=system,
                temperature=0.5,
                max_tokens=2048,
            )
        except Exception:
            # Planner failed → fall back to executor directly
            return await self.config.executor_provider.generate(
                task, system=system, temperature=temperature, max_tokens=4096
            )

        plan = plan_response.text

        # Phase 2: Execute with smart model
        execute_prompt = f"""Execute this plan step by step. Write COMPLETE code for each step.
No stubs. No placeholders.

TASK: {task}

PLAN:
{plan}

Deliver the final implementation. Include all files needed."""

        t0 = time.perf_counter()
        response = await self.config.executor_provider.generate(
            execute_prompt,
            system=system,
            temperature=temperature,
            max_tokens=8192,
        )

        total_latency = (time.perf_counter() - t0) * 1000 + plan_response.latency_ms

        return ProviderResponse(
            text=response.text,
            model=f"composite({self.config.planner_provider.default_model}→{self.config.executor_provider.default_model})",
            usage={
                "plan_tokens": plan_response.usage.get("total_tokens", 0),
                "execute_tokens": response.usage.get("total_tokens", 0),
            },
            finish_reason=response.finish_reason,
            latency_ms=total_latency,
        )

    async def verify(
        self,
        original_task: str,
        candidate_output: str,
    ) -> tuple[bool, str]:
        """Have a verifier model check the output. Returns (passed, feedback)."""
        if not self.config.verifier_provider:
            return True, "No verifier configured — passing by default."

        verify_prompt = f"""Verify this output against the original task.
Check for: correctness, completeness, edge cases, bugs, style.

ORIGINAL TASK:
{original_task}

OUTPUT TO VERIFY:
{candidate_output[:3000]}

Respond with:
PASS: <reason> (if the output is correct and complete)
FAIL: <reason> (if there are issues)
FIX: <specific fix> (if minor issues — provide the fix)"""

        try:
            response = await self.config.verifier_provider.generate(
                verify_prompt,
                temperature=0.3,
                max_tokens=1024,
            )
        except Exception:
            return True, "Verifier unavailable — passing by default"

        text = response.text.strip()
        if text.upper().startswith("PASS"):
            return True, text
        elif text.upper().startswith("FIX"):
            return True, text  # Pass with suggested fix
        else:
            return False, text

    async def list_models(self) -> list[str]:
        models = ["composite"]
        if self.config.planner_provider:
            models.extend(await self.config.planner_provider.list_models())
        if self.config.executor_provider:
            models.extend(await self.config.executor_provider.list_models())
        return list(set(models))

    # ── Helpers ──────────────────────────────────────────────

    async def _try_provider(
        self,
        provider: BaseProvider,
        prompt: str,
        system: Optional[str],
        temperature: float,
        max_tokens: int,
        tools: Optional[list[dict]],
    ) -> ProviderResponse:
        return await provider.generate(
            prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
        )

    def _record(self, provider_label: str, success: bool, latency_ms: float, error: str = "") -> None:
        self._metrics.append({
            "provider": provider_label,
            "success": success,
            "latency_ms": latency_ms,
            "error": error,
            "timestamp": time.time(),
        })

    @property
    def metrics(self) -> list[dict]:
        return self._metrics

    @property
    def success_rate(self) -> float:
        if not self._metrics:
            return 1.0
        successful = sum(1 for m in self._metrics if m["success"])
        return successful / len(self._metrics)

    def _error_response(self, message: str) -> ProviderResponse:
        return ProviderResponse(
            text=message,
            model="composite",
            usage={},
            finish_reason="error",
            latency_ms=0,
        )