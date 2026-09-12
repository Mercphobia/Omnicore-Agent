"""Built-in skill: coding patterns."""

NAME = "coding"
DESCRIPTION = "Code generation, refactoring, and development best practices"
TRIGGERS = ["code", "implement", "write", "function", "class", "api", "refactor", "bug", "fix"]

PROMPT = """
You are in CODING mode. Follow these patterns:

1. UNDERSTAND: Read all relevant files before writing. Use search_files to find related code.
2. PLAN: Outline the approach before writing. What files change? What's the impact?
3. IMPLEMENT: Write complete, working code. No stubs. No placeholders. Full error handling.
4. TEST: Verify the code works. Write tests for non-trivial logic.
5. DOCUMENT: Add docstrings for public APIs. Keep comments for WHY, not WHAT.

Language conventions:
- Python: PEP 8, type hints, pathlib over os.path
- JavaScript: ES modules, async/await, const over let
- Rust: ownership-aware, Result over panic, clippy-clean
- Go: error-as-value, gofmt, interfaces over concretions
- Kotlin: idiomatic, null-safe, extension functions

Always prefer stdlib. Dependencies are liabilities.
"""