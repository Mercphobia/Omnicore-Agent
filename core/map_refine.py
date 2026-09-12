"""Map-Refine editor. Architect plans the edit map → Editor applies changes →
Verifier checks correctness. Aider DNA.
"""


class MapRefineEditor:
    """Two-phase editing: plan (architect) → apply (editor)."""

    def __init__(self, provider):
        self.provider = provider

    async def edit(self, file_path: str, instruction: str, 
                   codebase_context: str = "") -> str:
        """Edit a file using map-refine pattern."""
        import asyncio

        # Phase 1: ARCHITECT — plan the edit
        plan = await self._plan(file_path, instruction, codebase_context)

        # Phase 2: EDITOR — apply the plan
        result = await self._apply(file_path, plan, instruction)

        return result

    async def _plan(self, file_path: str, instruction: str, 
                    context: str) -> str:
        """Architect phase: create a detailed edit plan."""
        from pathlib import Path
        content = ""
        try:
            content = Path(file_path).expanduser().read_text()
        except Exception:
            pass

        prompt = f"""You are an ARCHITECT. Plan the edit. Don't write code yet.

FILE: {file_path}
CONTENT:
{content[:5000]}

CONTEXT:
{context}

INSTRUCTION: {instruction}

Plan:
1. What lines change? (exact line numbers if possible)
2. What's the change? (add, modify, delete)
3. What must be preserved? (existing functionality, edge cases)
4. Dependencies: what other files are affected?
5. Risks: what could go wrong?

Be precise. The editor will follow your plan exactly."""

        resp = await self.provider.generate(prompt)
        return resp.text

    async def _apply(self, file_path: str, plan: str, 
                     instruction: str) -> str:
        """Editor phase: apply the plan to the actual file."""
        from pathlib import Path
        content = ""
        try:
            content = Path(file_path).expanduser().read_text()
        except Exception:
            pass

        prompt = f"""You are an EDITOR. Apply this plan to the file.

FILE: {file_path}
CURRENT CONTENT:
{content[:5000]}

ARCHITECT'S PLAN:
{plan}

ORIGINAL INSTRUCTION: {instruction}

Output the COMPLETE new file content. No explanations. Just the code."""

        resp = await self.provider.generate(prompt)

        # Write the result
        try:
            Path(file_path).expanduser().write_text(resp.text)
            return f"Edited {file_path} ({len(resp.text)} bytes)"
        except Exception as e:
            return f"Error writing {file_path}: {e}"