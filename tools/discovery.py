"""Tool Discovery — lazy-load tools on demand, search by capability.

DNA: Hermes tool_search + tool_describe.

Instead of loading all tools at startup, discover them lazily.
Search for tools by capability keywords, load only what's needed.
"""

import importlib
import pkgutil
from pathlib import Path
from typing import Optional


class ToolDiscovery:
    """Discover, search, and lazy-load tools.

    Usage:
        td = ToolDiscovery()
        
        # Search for tools
        results = td.search("sql injection")
        # → [{"name": "tools.pentest.exploit", "relevance": 0.9, ...}]
        
        # Load a tool
        tool_fn = td.load("tools.pentest.exploit.sqli_test")
        
        # List all discoverable tools
        tools = td.catalog()
    """

    def __init__(self, tools_root: Optional[Path] = None):
        if tools_root is None:
            tools_root = Path(__file__).parent
        self.tools_root = Path(tools_root)
        self._catalog: dict[str, dict] = {}
        self._loaded: dict[str, any] = {}
        self._build_catalog()

    def _build_catalog(self):
        """Scan tools directory and build a searchable catalog."""
        for py_file in self.tools_root.rglob("*.py"):
            if py_file.name.startswith("_"):
                continue

            module_path = self._module_path(py_file)
            functions = self._extract_functions(py_file)
            description = self._extract_docstring(py_file)

            for func_name in functions:
                full_name = f"{module_path}.{func_name}"
                self._catalog[full_name] = {
                    "name": full_name,
                    "module": module_path,
                    "function": func_name,
                    "description": description or f"Function in {module_path}",
                    "keywords": self._extract_keywords(func_name, description or ""),
                }

    def _module_path(self, filepath: Path) -> str:
        """Convert file path to Python module path."""
        rel = filepath.relative_to(self.tools_root.parent)
        parts = list(rel.parts)
        parts[-1] = parts[-1].replace(".py", "")
        return ".".join(parts)

    def _extract_functions(self, filepath: Path) -> list[str]:
        """Extract public function names from a Python file."""
        try:
            content = filepath.read_text()
            functions = []
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("def ") and not line.startswith("def _"):
                    name = line[4:].split("(")[0].strip()
                    functions.append(name)
                elif line.startswith("class ") and not line.startswith("class _"):
                    name = line[6:].split("(")[0].split(":")[0].strip()
                    functions.append(name)
            return functions
        except Exception:
            return []

    def _extract_docstring(self, filepath: Path) -> Optional[str]:
        """Extract module docstring."""
        try:
            content = filepath.read_text()
            if content.startswith('"""') or content.startswith("'''"):
                end = content.find(content[:3], 3)
                if end > 0:
                    return content[3:end].strip().split("\n")[0][:120]
        except Exception:
            pass
        return None

    def _extract_keywords(self, name: str, description: str) -> list[str]:
        """Extract search keywords from function name and description."""
        # Convert CamelCase/snake_case to words
        words = []
        # camelCase split
        current = ""
        for c in name:
            if c.isupper() and current:
                words.append(current.lower())
                current = c
            else:
                current += c
        if current:
            words.append(current.lower())

        # Add description words
        words.extend(description.lower().split()[:10])

        # Remove duplicates, short words, common words
        stop = {"the", "a", "an", "in", "of", "to", "and", "for", "is", "on", "or"}
        keywords = list(set(w for w in words if len(w) > 2 and w not in stop))
        return keywords[:20]

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search for tools matching a capability query.

        Args:
            query: Natural language query (e.g., "sql injection", "port scan")
            limit: Max results to return

        Returns:
            List of matching tools with relevance scores.
        """
        query_words = set(query.lower().split())
        results = []

        for name, info in self._catalog.items():
            keywords = set(info["keywords"])
            # Calculate relevance: % of query words matching tool keywords
            matches = query_words & keywords
            if matches:
                relevance = len(matches) / len(query_words)
                results.append({
                    **info,
                    "relevance": round(relevance, 2),
                    "matched_keywords": list(matches),
                })

        results.sort(key=lambda r: r["relevance"], reverse=True)
        return results[:limit]

    def load(self, full_name: str):
        """Load a specific tool function or class by its full name.

        Args:
            full_name: e.g., 'tools.pentest.recon.port_scan'

        Returns:
            The function/class, or None if not found.
        """
        if full_name in self._loaded:
            return self._loaded[full_name]

        if full_name not in self._catalog:
            return None

        info = self._catalog[full_name]
        try:
            module = importlib.import_module(info["module"])
            obj = getattr(module, info["function"], None)
            self._loaded[full_name] = obj
            return obj
        except (ImportError, AttributeError):
            return None

    def catalog(self) -> list[dict]:
        """List all discoverable tools."""
        return list(self._catalog.values())

    def by_category(self) -> dict[str, list[str]]:
        """Group tools by category (module path)."""
        categories: dict[str, list[str]] = {}
        for name in self._catalog:
            parts = name.split(".")
            cat = ".".join(parts[1:-1]) if len(parts) > 3 else parts[1]
            categories.setdefault(cat, []).append(name)
        return categories

    def suggest(self, task_description: str, max_suggestions: int = 5) -> list[str]:
        """Suggest tools for a task description."""
        results = self.search(task_description, limit=max_suggestions)
        return [r["name"] for r in results]


# ── Self-test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    td = ToolDiscovery()

    # Catalog
    total = len(td.catalog())
    print(f"Total discoverable tools: {total}")
    assert total > 20, f"Expected 20+ tools, got {total}"

    # Search
    results = td.search("sql injection")
    print(f"Search 'sql injection': {len(results)} results")
    for r in results[:3]:
        print(f"  {r['name']} (relevance: {r['relevance']})")

    results = td.search("file read write")
    print(f"Search 'file read write': {len(results)} results")

    # Load
    fn = td.load("tools.file_tools.read_file")
    if fn:
        print(f"Loaded: read_file")
    else:
        print("read_file not found (expected if catalog name differs)")

    # Categories
    cats = td.by_category()
    print(f"Categories: {len(cats)}")
    for cat, tools in sorted(cats.items())[:5]:
        print(f"  {cat}: {len(tools)} tools")

    # Suggest
    suggestions = td.suggest("scan network ports on a target")
    print(f"Suggestions for 'scan network ports': {suggestions}")

    print("\n✓ ToolDiscovery self-tests passed")