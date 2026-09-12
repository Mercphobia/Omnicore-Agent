"""Graceful degradation, retry logic, and fallback model switching.
DNA: Astra (self-healing) + Claude Code (retry with context).
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 1.0     # seconds
    max_delay: float = 30.0
    backoff_factor: float = 2.0
    jitter: bool = True          # Add random jitter to avoid thundering herd


class ErrorHandler:
    """Handles errors with retry, fallback, and graceful degradation."""

    def __init__(self, config: Optional[RetryConfig] = None):
        self.config = config or RetryConfig()

    async def retry(
        self,
        func: Callable,
        *args,
        on_error: Optional[Callable] = None,
        should_retry: Optional[Callable[[Exception], bool]] = None,
        **kwargs,
    ):
        """Execute a function with exponential backoff retry."""
        last_error = None

        for attempt in range(self.config.max_retries):
            try:
                result = func(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
                return result
            except Exception as e:
                last_error = e

                if should_retry and not should_retry(e):
                    raise

                if on_error:
                    on_error(e, attempt + 1, self.config.max_retries)

                if attempt == self.config.max_retries - 1:
                    raise

                delay = self._calculate_delay(attempt)
                await asyncio.sleep(delay)

        raise last_error  # Should not reach here

    def _calculate_delay(self, attempt: int) -> float:
        delay = min(
            self.config.base_delay * (self.config.backoff_factor ** attempt),
            self.config.max_delay,
        )
        if self.config.jitter:
            import random
            delay *= 0.5 + random.random()
        return delay


class ProviderFallback:
    """Manages provider failover: primary → fallback → error."""

    def __init__(self, providers: list, error_handler: Optional[ErrorHandler] = None):
        self.providers = providers
        self.error_handler = error_handler or ErrorHandler()
        self.failures: dict[str, int] = {}
        self.last_success: dict[str, float] = {}
        self.circuit_open: dict[str, bool] = {}

    async def execute_with_fallback(
        self,
        func: Callable,
        *args,
        **kwargs,
    ):
        """Try primary, fall back to alternates on failure."""
        if not self.providers:
            raise RuntimeError("No providers available")

        errors = []
        for provider in self.providers:
            provider_name = getattr(provider, "name", str(provider))

            # Check circuit breaker
            if self.circuit_open.get(provider_name):
                continue

            try:
                result = func(provider, *args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
                self._record_success(provider_name)
                return result
            except Exception as e:
                errors.append(f"{provider_name}: {e}")
                self._record_failure(provider_name)
                continue

        raise RuntimeError(f"All providers failed: {'; '.join(errors)}")

    def _record_success(self, provider_name: str) -> None:
        self.failures[provider_name] = 0
        self.last_success[provider_name] = time.time()
        self.circuit_open[provider_name] = False

    def _record_failure(self, provider_name: str) -> None:
        self.failures[provider_name] = self.failures.get(provider_name, 0) + 1
        # Open circuit after 3 consecutive failures
        if self.failures[provider_name] >= 3:
            self.circuit_open[provider_name] = True

    def reset_circuit(self, provider_name: str) -> None:
        self.circuit_open[provider_name] = False
        self.failures[provider_name] = 0