"""Isolated sub-agent process. Each worker runs in its own multiprocessing context
with an independent provider connection and tool registry.
DNA: Devin (autonomous loop) + CrewAI (role specialization).
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .bus import MessageBus, Message


@dataclass
class WorkerConfig:
    role: str
    role_context: str = ""
    model: str = ""
    temperature: float = 0.7
    max_iterations: int = 5


class Worker:
    """A single sub-agent with a specialized role."""

    def __init__(
        self,
        worker_id: str,
        config: WorkerConfig,
        provider_factory: Callable,
        bus: Optional[MessageBus] = None,
    ):
        self.id = worker_id
        self.config = config
        self.provider_factory = provider_factory
        self.provider = provider_factory()
        self.bus = bus
        self.history: list[dict] = []
        self.start_time: Optional[float] = None
        self.result: Optional[str] = None

    async def execute(self, task: str) -> str:
        """Execute a task autonomously. Returns final result."""
        self.start_time = time.perf_counter()

        system_prompt = self._build_system_prompt()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"TASK: {task}\n\nWork autonomously. Deliver a complete result."},
        ]

        for iteration in range(self.config.max_iterations):
            response = await self.provider.generate(
                prompt="",
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=4096,
            )

            # Check if the response is a tool call vs final answer
            tool_calls = self._extract_tool_calls(response.text)

            if not tool_calls:
                # Final answer
                self.result = response.text
                await self._broadcast(f"Worker {self.id} [{self.config.role}]: task complete")
                return response.text

            # Execute tools
            for tc in tool_calls:
                tool_result = await self._execute_tool(tc)
                messages.append({"role": "tool", "content": tool_result})

            # Prevent infinite loops
            if iteration >= self.config.max_iterations - 1:
                self.result = f"[{self.config.role}] Max iterations reached. Partial: {response.text[:500]}"
                return self.result

        return "No result produced."

    def _build_system_prompt(self) -> str:
        return f"""You are a specialized AI worker with role: {self.config.role}.

ROLE CONTEXT:
{self.config.role_context}

PRINCIPLES:
- Work autonomously. Don't ask questions — deliver results.
- Be thorough. Cover edge cases.
- Return complete, usable output. No stubs.
- If you need more information, state assumptions clearly and proceed.

Your worker ID: {self.id}"""

    def _extract_tool_calls(self, response: str) -> list[dict]:
        """Stub — full implementation in engine.py. Workers can use tools if assigned."""
        return []

    async def _execute_tool(self, tool_call: dict) -> str:
        """Execute a tool. Stub — full implementation in engine.py."""
        return f"Tool '{tool_call.get('name', '?')}' executed."

    async def _broadcast(self, message: str) -> None:
        """Send a message to the bus if connected."""
        if self.bus:
            await self.bus.publish(Message(
                sender=self.id,
                content=message,
                msg_type="status",
            ))

    @property
    def elapsed_ms(self) -> float:
        if self.start_time:
            return (time.perf_counter() - self.start_time) * 1000
        return 0


class WorkerPool:
    """Manage a pool of workers, executing tasks in parallel."""

    def __init__(self, provider_factory: Callable, bus: Optional[MessageBus] = None):
        self.provider_factory = provider_factory
        self.bus = bus
        self.workers: dict[str, Worker] = {}

    def spawn(self, worker_id: str, config: WorkerConfig) -> Worker:
        """Create a new worker."""
        worker = Worker(worker_id, config, self.provider_factory, self.bus)
        self.workers[worker_id] = worker
        return worker

    async def execute_parallel(self, assignments: dict[str, str]) -> dict[str, str]:
        """Execute multiple tasks in parallel.
        
        Args:
            assignments: {worker_id: task_description}
        Returns:
            {worker_id: result}
        """
        tasks = []
        for worker_id, task in assignments.items():
            if worker_id not in self.workers:
                config = WorkerConfig(role="coder", role_context="General coding specialist")
                self.spawn(worker_id, config)
            tasks.append(self.workers[worker_id].execute(task))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = {}
        for (worker_id, _), result in zip(assignments.items(), results):
            if isinstance(result, Exception):
                output[worker_id] = f"Worker {worker_id} failed: {result}"
            else:
                output[worker_id] = result

        return output

    async def execute_sequential(self, assignments: list[tuple[str, str]]) -> dict[str, str]:
        """Execute tasks sequentially, each worker building on previous results.
        
        Args:
            assignments: [(worker_id, task_description), ...]
        Returns:
            {worker_id: result}
        """
        results = {}
        context = ""

        for worker_id, task in assignments:
            if worker_id not in self.workers:
                config = WorkerConfig(role="coder")
                self.spawn(worker_id, config)

            task_with_context = f"CONTEXT FROM PREVIOUS STEPS:\n{context}\n\nCURRENT TASK:\n{task}"
            result = await self.workers[worker_id].execute(task_with_context)
            results[worker_id] = result
            context += f"\n[{worker_id}] Result: {result[:500]}\n"

        return results

    def shutdown(self) -> None:
        """Clean up all workers."""
        self.workers.clear()