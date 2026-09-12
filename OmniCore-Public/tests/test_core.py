"""Smoke tests for OmniCore core components.
Run: python -m pytest tests/ -v
"""

import pytest
import tempfile
from pathlib import Path


# ── Config tests ───────────────────────────────────────────

def test_config_loads_defaults():
    from core.config import load_config

    # Load with defaults only (no user config)
    config = load_config()

    assert "provider" in config
    assert "agent" in config
    assert "memory" in config
    assert "tools" in config


def test_config_merge():
    from core.config import _deep_merge

    base = {"a": 1, "b": {"x": 1}}
    override = {"b": {"y": 2}, "c": 3}
    _deep_merge(base, override)

    assert base["a"] == 1
    assert base["b"]["x"] == 1
    assert base["b"]["y"] == 2
    assert base["c"] == 3


# ── Tool registry tests ────────────────────────────────────

def test_registry_register():
    from tools.registry import ToolRegistry

    def dummy_func(x: int = 0) -> str:
        """Dummy tool for testing."""
        return f"Got {x}"

    reg = ToolRegistry()
    reg.register("dummy", dummy_func, "A dummy tool")

    tool = reg.get("dummy")
    assert tool is not None
    assert "dummy" in tool.description.lower()
    assert tool.name == "dummy"


def test_registry_schema():
    from tools.registry import ToolRegistry

    def search(query: str, limit: int = 5) -> str:
        return f"Search: {query}"

    reg = ToolRegistry()
    reg.register("search", search)

    schemas = reg.get_schemas()
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "search"
    assert "query" in schemas[0]["function"]["parameters"]["properties"]
    assert "limit" in schemas[0]["function"]["parameters"]["properties"]


def test_registry_describe():
    from tools.registry import ToolRegistry

    reg = ToolRegistry()
    reg.register("tool_a", lambda: None, "Tool A")
    reg.register("tool_b", lambda: None, "Tool B", requires_approval=True)

    desc = reg.describe()
    assert "tool_a" in desc
    assert "Tool A" in desc
    assert "APPROVAL" in desc  # tool_b has approval


def test_registry_unknown_tool():
    from tools.registry import ToolRegistry

    reg = ToolRegistry()
    assert reg.get("nonexistent") is None


# ── Memory tests ───────────────────────────────────────────

def test_memory_facts():
    from memory.store import MemoryStore

    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        store = MemoryStore(tmp.name)
        store.remember("test_key", "test_value")
        assert store.recall("test_key") == "test_value"
        store.forget("test_key")
        assert store.recall("test_key") is None
        store.close()


def test_memory_sessions():
    from memory.store import MemoryStore

    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        store = MemoryStore(tmp.name)
        sid = "test_session_1"
        store.create_session(sid, "Test Session")
        sessions = store.list_sessions()
        assert any(s["id"] == sid for s in sessions)
        store.close()


def test_memory_messages():
    from memory.store import MemoryStore

    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        store = MemoryStore(tmp.name)
        sid = "test_session_msg"
        store.create_session(sid)
        store.save_message(sid, "user", "Hello")
        store.save_message(sid, "assistant", "Hi there!")

        msgs = store.get_messages(sid)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"
        store.close()


# ── Router tests ───────────────────────────────────────────

def test_router_classify():
    from providers.router import Router

    router = Router({})

    assert router._classify("fix the bug in server.py") == "debug"
    assert router._classify("design a landing page") == "design"
    assert router._classify("implement user login API") == "code"
    assert router._classify("refactor to microservices") == "architecture"
    assert router._classify("hi") == "simple"
    assert router._classify("tell me about quantum computing and its applications") == "general"


def test_router_routing():
    from providers.router import Router

    router = Router({})
    # "fix crash" — 2 words, classified as debug but <5 words → fast model
    result = router.route("fix crash")
    # 2 words → short query override to fast model, task_type stays debug
    assert "flash" in result["model"].lower() or "gemini" in result["model"].lower()

    # Longer debug query → smart model
    result2 = router.route("help me fix a critical production bug in the server")
    assert "claude" in result2["model"].lower()
    assert result2["task_type"] == "debug"


# ── Error handler tests ────────────────────────────────────

@pytest.mark.asyncio
async def test_retry_success():
    from core.error_handler import ErrorHandler, RetryConfig

    handler = ErrorHandler(RetryConfig(max_retries=3, base_delay=0.01))
    call_count = 0

    async def flaky_func():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError("Temporary failure")
        return "success"

    result = await handler.retry(flaky_func)
    assert result == "success"
    assert call_count == 3


@pytest.mark.asyncio
async def test_retry_exhausted():
    from core.error_handler import ErrorHandler, RetryConfig

    handler = ErrorHandler(RetryConfig(max_retries=2, base_delay=0.01))

    async def always_fails():
        raise RuntimeError("Always fails")

    with pytest.raises(RuntimeError):
        await handler.retry(always_fails)


# ── File tools tests ───────────────────────────────────────

def test_file_read_write():
    from tools.file_tools import read_file, write_file

    with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as tmp:
        tmp.write("line 1\nline 2\nline 3")
        tmp_path = tmp.name

    result = read_file(tmp_path)
    assert "line 1" in result
    assert "line 2" in result

    write_result = write_file(tmp_path, "new content")
    assert "Written" in write_result

    result2 = read_file(tmp_path)
    assert result2 == "new content"

    Path(tmp_path).unlink()


# ── Persona tests ──────────────────────────────────────────

def test_persona_loads_default():
    from core.persona import get_persona_prompt

    prompt = get_persona_prompt()
    assert "OmniCore" in prompt
    assert "Execute" in prompt or "execute" in prompt.lower()


# ── Think tests ────────────────────────────────────────────

def test_think_classify():
    from core.think import classify_task

    assert classify_task("fix this bug") == "debug"
    assert classify_task("create a new API endpoint") == "code"
    assert classify_task("how do I scale this") == "architecture"
    assert classify_task("what color should I use") == "design"
    assert classify_task("hello") == "general"


def test_think_prompt():
    from core.think import get_thinking_prompt

    for task_type in ("code", "debug", "architecture", "design", "general"):
        prompt = get_thinking_prompt(task_type)
        assert len(prompt) > 50
        assert "step" in prompt.lower()