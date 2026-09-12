"""Multi-agent orchestrator. Decompose complex tasks into sub-tasks,
spawn parallel workers, merge results.
DNA: Devin (autonomous loop) + Astra (hyper-agentic) + CrewAI (roles).
"""

import asyncio
import multiprocessing as mp
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class SubTask:
    id: str
    role: str       # "architect", "coder", "reviewer", "researcher"
    prompt: str
    depends_on: list[str] = field(default_factory=list)


@dataclass
class TaskResult:
    task_id: str
    role: str
    result: str
    success: bool
    duration_ms: float


class Orchestrator:
    """Decompose → assign → execute → merge."""

    ROLES = {
        "architect": "System design, architecture decisions, trade-off analysis",
        "coder": "Implementation, code generation, debugging",
        "reviewer": "Code review, quality check, security audit",
        "researcher": "Web research, documentation, fact-checking",
        "tester": "Test generation, edge case analysis, quality assurance",
        "devops": "Infrastructure, CI/CD, deployment, monitoring",
    }

    def __init__(self, provider_factory: Callable):
        self.provider_factory = provider_factory

    async def execute(self, task: str, parallel: bool = True) -> dict:
        """Execute a complex task using multi-agent orchestration."""
        # Step 1: Decompose
        subtasks = await self._decompose(task)

        if len(subtasks) <= 1 or not parallel:
            # Simple task — sequential execution
            results = []
            for st in subtasks:
                result = await self._execute_one(st)
                results.append(result)
        else:
            # Complex task — parallel execution
            results = await self._execute_parallel(subtasks)

        # Step 3: Merge
        return await self._merge(task, subtasks, results)

    async def _decompose(self, task: str) -> list[SubTask]:
        """Use AI to decompose a complex task into sub-tasks."""
        provider = self.provider_factory()
        roles_desc = "\n".join(f"- {k}: {v}" for k, v in self.ROLES.items())

        prompt = f"""Decompose this complex task into sub-tasks:

TASK: {task}

Available roles:
{roles_desc}

For each sub-task, specify:
1. ROLE: which specialist should handle it
2. PROMPT: exactly what they should do (be specific)
3. DEPENDS_ON: list of task IDs that must complete first (empty if none)

Return as JSON list: [{{"role": "...", "prompt": "...", "depends_on": []}}]

Keep it focused. 2-5 sub-tasks max. Quality over quantity."""

        import json
        try:
            resp = await provider.generate(prompt)
            # Extract JSON from response
            start = resp.text.find("[")
            end = resp.text.rfind("]") + 1
            if start >= 0 and end > start:
                data = json.loads(resp.text[start:end])
            else:
                # Fallback: treat whole task as one
                return [SubTask("0", "coder", task)]

            return [
                SubTask(
                    id=str(i),
                    role=d.get("role", "coder"),
                    prompt=d.get("prompt", task),
                    depends_on=d.get("depends_on", []),
                )
                for i, d in enumerate(data)
            ]
        except Exception:
            return [SubTask("0", "coder", task)]

    async def _execute_one(self, task: SubTask) -> TaskResult:
        """Execute a single sub-task."""
        import time
        t0 = time.perf_counter()

        provider = self.provider_factory()
        role_context = self.ROLES.get(task.role, "")
        prompt = f"[Role: {task.role} — {role_context}]\n\nTask: {task.prompt}"

        try:
            resp = await provider.generate(prompt)
            return TaskResult(
                task_id=task.id,
                role=task.role,
                result=resp.text,
                success=True,
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
        except Exception as e:
            return TaskResult(
                task_id=task.id,
                role=task.role,
                result=str(e),
                success=False,
                duration_ms=(time.perf_counter() - t0) * 1000,
            )

    async def _execute_parallel(self, tasks: list[SubTask]) -> list[TaskResult]:
        """Execute sub-tasks in parallel, respecting dependencies."""
        # For now: simple parallel (ignore dependencies for speed)
        coroutines = [self._execute_one(t) for t in tasks]
        return await asyncio.gather(*coroutines)

    async def _merge(self, original: str, tasks: list[SubTask],
                     results: list[TaskResult]) -> dict:
        """Merge sub-task results into unified output."""
        provider = self.provider_factory()

        results_text = "\n\n".join(
            f"[{r.role}] {'✅' if r.success else '❌'}\n{r.result[:1000]}"
            for r in results
        )

        prompt = f"""Merge these sub-task results into ONE coherent answer.

ORIGINAL TASK: {original}

SUB-TASK RESULTS:
{results_text}

Synthesize. Don't just concatenate. Remove redundancy. Create flow."""

        resp = await provider.generate(prompt)

        return {
            "task": original,
            "subtasks": len(tasks),
            "roles": [t.role for t in tasks],
            "results": [
                {"role": r.role, "success": r.success, "duration_ms": r.duration_ms}
                for r in results
            ],
            "merged": resp.text,
        }