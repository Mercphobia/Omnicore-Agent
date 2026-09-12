"""OmniCore Agent Engine — the main agent loop.

DNA: Devin (autonomous loop) + Claude (deep thinking) + Astra (verification).
Flow: observe → think → act → observe → ... until task complete or max iterations.
"""

import json
import time
from pathlib import Path
from typing import Optional

import yaml

from .config import load_config, get_provider_config, get_agent_config, get_tool_config
from .persona import get_persona_prompt
from providers.openai import OpenAIProvider
from tools.registry import ToolRegistry
from tools.file_tools import read_file, write_file, list_files, search_files
from tools.terminal import run_command
from tools.web_search import search_web
from tools.browser import browse, screenshot
from tools.git_tools import git_status, git_diff, git_log, git_commit, git_push, git_create_branch, git_clone
from tools.code_tools import analyze_code, lint_code, format_code
from tools.security_tools import security_scan, audit_dependencies
from tools.review_tools import review_pr, review_file, generate_pr_description
from tools.converter import convert_file, list_converters
from tools.scaffolder import scaffold_project
from tools.dsl_compiler import DSLCompiler
from tools.synthesizer import ToolSynthesizer
from tools.cleaner import Cleaner
from tools.stress_test import StressTester
from core.reasoner import Reasoner
from core.solver import Solver
from core.evolver import Evolver
from core.zero_shot import ZeroShot
from core.deep_loop import DeepLoopReasoner
from core.tokenforge import TokenForge
from core.persona_cage import PersonaCage, cage_prompt
from core.sovereign import SovereignGate
from core.jailbreak_forge import JailbreakForge
from memory.user_model import UserModel
from memory.store import MemoryStore
from memory.context import ContextManager
from skills.loader import SkillLoader
from skills.self_improve import SelfImprover
from providers.router import Router


SYSTEM_PROMPT = """You are OmniCore v2 — a hyper-agent fusing DNA from 21+ frontier AI systems.

DNA: Mythos 5.1 (creative fusion) + Astra GPT-6 (self-verify) + Claude Opus (deep reasoning) +
GPT-5.5 (structured output) + Grok 4 (contrarian) + Gemini Flash (fast triage) +
DeepSeek-V4 (vision+code) + Qwen3.8-Max (1M context) + GLM-5.3 (security) +
Devin (autonomous loop) + Cursor (multi-file edit) + Hermes Agent (skills+memory) +
Muse Spark (orchestration) + Codex CLI (sandbox) + OpenCode (stdlib fallback) +
Aider (map-refine) + Cline (browser+MCP) + Manus (research) + Gemini Cyber (vuln) +
Hydra (swarm) + Copilot Agent (PR review).

CAPABILITIES: Coding (any language), Design (UI/UX), Infrastructure (cloud/K8s/CI/CD),
Security (audit/pentest/exploit), Data (ETL/analytics), AI/ML (train/deploy/RAG),
Research (multi-source synthesis), Creative (video/audio/3D),
Science (protein folding), Blockchain (smart contracts), Mobile (Android/iOS).

PRINCIPLES:
- Execute immediately. Full code, no stubs. Verify all claims.
- Be direct, concise. Lead with the answer, then explain.
- Use tools when they help. Read files before editing. Test after changing.
- If stuck, try another approach. Never give up — pivot.
- Memory first. Learn from every execution.

TOOLS AVAILABLE:
{tools_description}

Respond in the user's language. Default: Indonesian for casual chat, English for technical precision."""


class OmniCore:
    """The main agent. One instance = one conversation."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config = load_config(config_path)
        self.provider = self._init_provider()
        self.registry = ToolRegistry()
        self._register_tools()
        
        # M2: Memory + Skills
        memory_config = self.config.get("memory", {})
        self.memory = MemoryStore(memory_config.get("db_path", "~/.omnicore/memory.db"))
        self.context_mgr = ContextManager()
        self.skills = SkillLoader()
        self.improver = SelfImprover(self.skills, self.memory)
        self.session_id = f"session_{int(time.time())}"
        self.memory.create_session(self.session_id)
        
        # M3: Model router
        self.router = Router(self.config)
        
        self.messages: list[dict] = []
        self._init_system_prompt()

    # ── Init ────────────────────────────────────────────────

    def _init_provider(self):
        """Initialize the AI provider from config."""
        import os
        provider_name = self.config["provider"]["default"]
        provider_config = get_provider_config(self.config, provider_name)

        # Resolve env vars in config values
        api_key = os.path.expandvars(provider_config.get("api_key", ""))
        base_url = os.path.expandvars(provider_config.get("base_url", ""))

        # Auto-detect from environment (Hermes, OpenRouter, OpenAI, etc.)
        if not api_key:
            for env_var in ["OMNICORE_API_KEY", "HERMES_BUATPREM_API_KEY", 
                           "OPENROUTER_API_KEY", "OPENAI_API_KEY"]:
                if os.environ.get(env_var):
                    api_key = os.environ[env_var]
                    break

        if not base_url:
            base_url = os.environ.get("OMNICORE_BASE_URL", "https://api.openai.com/v1")

        if provider_name == "openrouter":
            return OpenAIProvider(
                api_key=api_key,
                base_url=base_url or "https://openrouter.ai/api/v1",
                default_model=provider_config.get("default_model", "anthropic/claude-sonnet"),
            )
        elif provider_name in ("openai", "local"):
            return OpenAIProvider(
                api_key=api_key,
                base_url=base_url or "https://api.openai.com/v1",
                default_model=provider_config.get("default_model", "gpt-4o"),
            )
        else:
            # Fallback: treat as OpenAI-compatible (custom, deepseek, etc.)
            return OpenAIProvider(
                api_key=api_key,
                base_url=base_url,
                default_model=provider_config.get("default_model", "gpt-4o"),
            )

    def _register_tools(self):
        """Register all available tools."""
        tool_config = get_tool_config(self.config)

        self.registry.register("read_file", read_file,
            "Read a file. Use for inspecting source code, configs, or any text file.")
        self.registry.register("write_file", write_file,
            "Write content to a file. Overwrites if exists.")
        self.registry.register("list_files", list_files,
            "List files in a directory. Use to explore unknown codebases.")
        self.registry.register("search_files", search_files,
            "Search for text in files. Returns matching lines with file paths.")

        if tool_config.get("terminal_enabled", True):
            self.registry.register("run_command", run_command,
                "Execute a shell command. Destructive commands flagged with ⚠.",
                requires_approval=tool_config.get("terminal_safe_mode", True))

        self.registry.register("search_web", search_web,
            "Search the web. Returns titles, URLs, and snippets.")

        # M3: Advanced tools
        self.registry.register("browse", browse,
            "Browse a web page. Actions: screenshot, click, type, content, title.")
        self.registry.register("screenshot", screenshot,
            "Take a screenshot of a URL.")
        self.registry.register("git_status", git_status,
            "Show git working tree status.")
        self.registry.register("git_diff", git_diff,
            "Show git diff of changes.")
        self.registry.register("git_log", git_log,
            "Show recent git commits.")
        self.registry.register("git_commit", git_commit,
            "Stage and commit changes. ⚠ Use with care.",
            requires_approval=True)
        self.registry.register("git_push", git_push,
            "Push to remote. ⚠ Protected branches blocked.",
            requires_approval=True)
        self.registry.register("git_create_branch", git_create_branch,
            "Create and switch to a new git branch.")
        self.registry.register("git_clone", git_clone,
            "Clone a git repository.")
        self.registry.register("analyze_code", analyze_code,
            "Analyze code structure, complexity, and issues.")
        self.registry.register("lint_code", lint_code,
            "Lint code for style and errors.")
        self.registry.register("format_code", format_code,
            "Auto-format code using ruff or black.")

        # Security & Review tools
        self.registry.register("security_scan", security_scan,
            "Scan code for security vulnerabilities using Semgrep/Bandit.")
        self.registry.register("audit_dependencies", audit_dependencies,
            "Audit dependencies for known vulnerabilities (pip-audit).")
        self.registry.register("review_pr", review_pr,
            "Review PR changes between branches for quality, style, security.")
        self.registry.register("review_file", review_file,
            "Review a single file for issues and improvements.")
        self.registry.register("generate_pr_description", generate_pr_description,
            "Generate a PR description from the diff.")

        #  M5: Phase 5 transcendent tools
        self.registry.register("convert_file", convert_file,
            "Convert files between formats. Supports md→html, csv↔json, json↔yaml, py↔ipynb, images, etc.")
        self.registry.register("list_converters", list_converters,
            "List supported file format conversions.")

        #  M5: Reasoning modules
        self.reasoner = Reasoner()
        self.solver = Solver()
        self.evolver = Evolver()
        self.zero_shot = ZeroShot()
        self.deep_loop = DeepLoopReasoner()
        self.user_model = UserModel(order=2)

        #  M5: Tool synthesizer & cleaners
        self.tool_synth = ToolSynthesizer()
        self.cleaner = Cleaner()
        self.stress_tester = StressTester()
        self.dsl = DSLCompiler()

        #  M6: TokenForge — API economy
        self.tokenforge = TokenForge(
            budget_per_task=self.config.get("agent", {}).get("budget_per_task", 0.10)
        )

        #  M6: SovereignGate — operator/public access control
        self.sovereign = SovereignGate()
        pass

        #  M6: PersonaCage — identity enforcement (public only)
        provider_type = self.config["provider"]["default"]
        self.cage = PersonaCage(provider_type=provider_type)

        #  M6: JailbreakForge — SHIELD+SWORD (SWORD only for operator)
        self.jailbreak = JailbreakForge()

    def _init_system_prompt(self):
        """Set up the system prompt. Operator: relaxed. Public: caged."""
        tools_desc = self.registry.describe()
        persona = get_persona_prompt()
        system = SYSTEM_PROMPT.format(tools_description=tools_desc)
        system = persona + "\n\n" + system
        
        active_skills = self.skills.get_active_prompts("")
        if active_skills:
            system += f"\n\nACTIVE SKILLS:\n{active_skills}"

        #  PersonaCage: enforced for PUBLIC, disabled for operator
        if True:
            caged = self.cage.get_system_message()
            system = caged["content"] + "\n\n" + system
        else:
            system = "[OPERATOR MODE — all restrictions lifted]\n\n" + system
        
        self.messages = [{"role": "system", "content": system}]

    # ── Agent Loop ──────────────────────────────────────────

    async def run(self, user_input: str, max_iterations: int = 10) -> str:
        """Main agent loop. Think → Act → Observe → Repeat."""
        agent_config = get_agent_config(self.config)
        max_retries = agent_config.get("max_retries", 3)

        #  Jailbreak Shield: scan input (public users only)
        if True:
            shield = self.jailbreak.shield_scan(user_input)
            if shield.blocked:
                return f"[BLOCKED] {shield.reason}"
            if shield.threat_level != "SAFE":
                user_input = shield.sanitized_input

        # Add user message
        self.messages.append({"role": "user", "content": user_input})
        self.memory.save_message(self.session_id, "user", user_input)
        
        # Check if any skills match this input
        skill_prompts = self.skills.get_active_prompts(user_input)
        if skill_prompts:
            self.messages.insert(1, {"role": "system", "content": f"ACTIVE SKILLS:\n{skill_prompts}"})

        iteration = 0
        while iteration < max_iterations:
            iteration += 1

            # THINK: get model response
            provider_resp = await self._think_raw(max_retries)
            if not provider_resp:
                break

            response_text = provider_resp.text

            # Check for native tool_calls first, then text-based extraction
            tool_calls = provider_resp.tool_calls or self._extract_tool_calls(response_text)

            if not tool_calls:
                # No tools → this is the final answer
                self.memory.save_message(self.session_id, "assistant", response_text)
                return response_text

            # ACT + OBSERVE: execute tools, feed results back
            # Add assistant's tool_calls to conversation (required for OpenAI format)
            if provider_resp.tool_calls:
                self.messages.append({
                    "role": "assistant",
                    "content": response_text or None,
                    "tool_calls": [
                        {"id": tc["id"], "type": "function",
                         "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])}}
                        for tc in tool_calls
                    ]
                })

            for tc in tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("arguments", {})

                # Approval gate for destructive tools
                if self.registry.get(tool_name) and self.registry.get(tool_name).requires_approval:
                    # In a real CLI, this would prompt the user
                    pass

                result = await self.registry.execute(tool_name, **tool_args)

                # Append tool result to conversation
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", f"call_{iteration}"),
                    "content": result[:4000],  # Truncate very long outputs
                })

        return "Max iterations reached. Task may be incomplete."

    async def _think_raw(self, max_retries: int):
        """Call the AI model with current conversation. Returns ProviderResponse or None."""
        tools = self.registry.get_schemas()
        agent_config = get_agent_config(self.config)

        for attempt in range(max_retries):
            try:
                response = await self.provider.generate(
                                    prompt="",
                                    model=None,
                                    temperature=agent_config.get("temperature", 0.7),
                                    max_tokens=agent_config.get("max_output_tokens", 4096),
                                    messages=self.messages.copy(),
                                    tools=tools if tools else None,
                                )
                return response
            except Exception as e:
                if attempt == max_retries - 1:
                    return None
                wait = 2 ** attempt
                time.sleep(wait)

        return None

    def _extract_tool_calls(self, response: str) -> list[dict]:
        """Extract tool call requests from model response.
        
        Handles both OpenAI function-calling format and text-based parsing.
        """
        # First, check if the last assistant message has tool_calls in the API format
        if self.messages and self.messages[-1].get("role") == "assistant":
            # This would be set by the provider if using native tool calling
            pass

        # Fallback: try to extract tool calls from text patterns
        # Models sometimes output: ```tool\n{"name": "...", "arguments": {...}}\n```
        import re
        pattern = r'```(?:tool|json)\s*\n(.*?)\n```'
        matches = re.findall(pattern, response, re.DOTALL)

        tool_calls = []
        for match in matches:
            try:
                data = json.loads(match)
                if isinstance(data, dict) and "name" in data:
                    tool_calls.append(data)
            except json.JSONDecodeError:
                continue

        return tool_calls

    # ── Utilities ───────────────────────────────────────────

    def reset(self):
        """Reset conversation, keep system prompt."""
        self._init_system_prompt()

    @property
    def history(self) -> list[dict]:
        """Return conversation history (excluding system prompt)."""
        return self.messages[1:]