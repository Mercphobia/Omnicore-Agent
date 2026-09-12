"""Tool registry — discover, register, validate, execute tools."""

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolDefinition:
    name: str
    description: str
    func: Callable
    parameters: dict = field(default_factory=dict)
    requires_approval: bool = False

    def to_openai_schema(self) -> dict:
        """Convert to OpenAI function-calling schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Central registry for all tools the agent can use."""

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        func: Callable,
        description: str = "",
        parameters: dict | None = None,
        requires_approval: bool = False,
    ) -> None:
        """Register a callable as a tool."""
        if not description:
            description = (func.__doc__ or "").strip().split("\n")[0]
        if parameters is None:
            parameters = self._infer_parameters(func)

        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            func=func,
            parameters=parameters or {
                "type": "object",
                "properties": {},
                "required": [],
            },
            requires_approval=requires_approval,
        )

    def register_many(self, tools: list[tuple]) -> None:
        """Batch register: [(name, func, description?), ...]."""
        for t in tools:
            name = t[0]
            func = t[1]
            desc = t[2] if len(t) > 2 else ""
            approval = t[3] if len(t) > 3 else False
            self.register(name, func, desc, requires_approval=approval)

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list_all(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def get_schemas(self) -> list[dict]:
        """Return all tools as OpenAI-compatible schemas."""
        return [t.to_openai_schema() for t in self._tools.values()]

    def describe(self) -> str:
        """Human-readable tool list for system prompt."""
        lines = []
        for t in self._tools.values():
            approval = " [APPROVAL REQUIRED]" if t.requires_approval else ""
            lines.append(f"- {t.name}: {t.description}{approval}")
        return "\n".join(lines)

    async def execute(self, name: str, **kwargs) -> str:
        """Execute a tool by name with given arguments."""
        tool = self._tools.get(name)
        if not tool:
            return f"Error: tool '{name}' not found. Available: {list(self._tools.keys())}"

        try:
            result = tool.func(**kwargs)
            if inspect.iscoroutine(result):
                result = await result
            return str(result)
        except Exception as e:
            return f"Tool '{name}' failed: {type(e).__name__}: {e}"

    @staticmethod
    def _infer_parameters(func: Callable) -> dict:
        """Build JSON Schema from function signature."""
        try:
            sig = inspect.signature(func)
        except (ValueError, TypeError):
            return {"type": "object", "properties": {}, "required": []}

        properties = {}
        required = []
        for name, param in sig.parameters.items():
            if name in ("self", "cls"):
                continue
            param_type = "string"
            if param.annotation is not inspect.Parameter.empty:
                ann = param.annotation
                if ann is int:
                    param_type = "integer"
                elif ann is float:
                    param_type = "number"
                elif ann is bool:
                    param_type = "boolean"
            properties[name] = {"type": param_type, "description": f"Parameter: {name}"}
            if param.default is inspect.Parameter.empty:
                required.append(name)

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }