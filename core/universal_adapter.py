"""
Universal Codebase Adapter — instant in-memory model of any codebase.
DNA: Ingest any repository in seconds, build a full dependency graph,
and query it as if you've studied every file. No other agent builds
a live semantic model of foreign code this fast.
"""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import itertools
import json
import os
import re
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, Union


# ============================================================================
# Data types
# ============================================================================


@dataclass
class Symbol:
    """A discovered symbol (function, class, variable, import)."""

    name: str
    kind: str  # "function", "class", "variable", "import", "export", "module"
    file_path: str
    line: int
    signature: Optional[str] = None  # function/class signature
    docstring: Optional[str] = None
    decorators: List[str] = field(default_factory=list)
    references: List[str] = field(default_factory=list)  # other symbols it references


@dataclass
class FileAnalysis:
    """Deep analysis of a single file."""

    path: str
    language: str
    lines: int
    size_bytes: int
    imports: List[str] = field(default_factory=list)
    exports: List[str] = field(default_factory=list)
    symbols: List[Symbol] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)  # files this depends on
    dependents: List[str] = field(default_factory=list)  # files that depend on this
    patterns: List[str] = field(default_factory=list)  # detected patterns
    complexity_hint: str = ""  # "simple", "moderate", "complex"


@dataclass
class DependencyGraph:
    """The full dependency graph of a codebase."""

    nodes: Dict[str, FileAnalysis] = field(default_factory=dict)
    edges: List[Tuple[str, str]] = field(default_factory=list)  # (from_file, to_file)
    entry_points: List[str] = field(default_factory=list)
    leaf_nodes: List[str] = field(default_factory=list)
    cycles: List[List[str]] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ArchitectureMap:
    """High-level architecture description."""

    layers: List[Dict[str, Any]]  # each layer: {name, files, purpose}
    external_deps: List[str]
    internal_modules: List[str]
    data_flow: List[str]  # human-readable flow descriptions
    anti_patterns: List[str]
    diagram_ascii: str = ""


@dataclass
class IntegrationSuggestion:
    """How to integrate an external library."""

    library: str
    entry_points: List[str]  # files where integration should happen
    compatibility_issues: List[str]
    required_changes: List[str]
    estimated_effort: str  # "low", "medium", "high", "extreme"
    example_code: str = ""


# ============================================================================
# Language detectors and parsers
# ============================================================================


class _LanguageDetector:
    """Detect programming language from file extension and content."""

    EXTENSIONS: Dict[str, str] = {
        ".py": "python", ".pyw": "python", ".pyx": "cython",
        ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
        ".ts": "typescript", ".tsx": "typescript",
        ".jsx": "jsx",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".kt": "kotlin", ".kts": "kotlin",
        ".swift": "swift",
        ".c": "c", ".h": "c",
        ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp",
        ".rb": "ruby",
        ".php": "php",
        ".sh": "shell", ".bash": "shell", ".zsh": "shell",
        ".sql": "sql",
        ".r": "r",
        ".lua": "lua",
        ".scala": "scala",
        ".dart": "dart",
        ".vue": "vue",
        ".svelte": "svelte",
        ".yaml": "yaml", ".yml": "yaml",
        ".json": "json",
        ".toml": "toml",
        ".xml": "xml",
        ".md": "markdown", ".mdx": "mdx",
        ".proto": "protobuf",
        ".graphql": "graphql", ".gql": "graphql",
        ".dockerfile": "dockerfile",
        ".makefile": "makefile",
        ".cmake": "cmake",
    }

    @classmethod
    def detect(cls, file_path: str) -> str:
        """Detect language from file path and extension."""
        name = os.path.basename(file_path).lower()
        ext = os.path.splitext(file_path)[1].lower()

        # Special filenames
        if name == "dockerfile":
            return "dockerfile"
        if name == "makefile" or name == "gnumakefile":
            return "makefile"
        if name == "cmakelists.txt":
            return "cmake"

        return cls.EXTENSIONS.get(ext, "unknown")


# ============================================================================
# Python-specific AST analyzer
# ============================================================================


class _PythonAnalyzer:
    """Extract symbols, imports, exports, and patterns from Python source."""

    @classmethod
    def analyze(cls, source: str, file_path: str) -> Tuple[List[Symbol], List[str], List[str], List[str]]:
        """Analyze Python source and return (symbols, imports, exports, patterns)."""
        symbols: List[Symbol] = []
        imports: List[str] = []
        exports: List[str] = []
        patterns: List[str] = []

        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError:
            return symbols, imports, exports, patterns

        # Walk the AST
        for node in ast.walk(tree):
            # Imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
                    symbols.append(Symbol(
                        name=alias.name,
                        kind="import",
                        file_path=file_path,
                        line=node.lineno,
                        references=[alias.name],
                    ))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    full = f"{module}.{alias.name}" if module else alias.name
                    imports.append(full)
                    symbols.append(Symbol(
                        name=alias.name,
                        kind="import",
                        file_path=file_path,
                        line=node.lineno,
                        references=[full],
                    ))

            # Functions
            elif isinstance(node, ast.FunctionDef):
                decorators = [
                    ast.unparse(d) if hasattr(ast, "unparse") else cls._decorator_name(d)
                    for d in node.decorator_list
                ]
                sig_parts = [node.name, "("]
                sig_parts.append(", ".join(a.arg for a in node.args.args))
                sig_parts.append(")")
                signature = "".join(sig_parts)

                # Extract docstring
                doc = ast.get_docstring(node)

                # Find references inside the function
                refs = cls._find_references(node)

                symbols.append(Symbol(
                    name=node.name,
                    kind="function",
                    file_path=file_path,
                    line=node.lineno,
                    signature=signature,
                    docstring=doc,
                    decorators=decorators,
                    references=refs,
                ))
                if not node.name.startswith("_"):
                    exports.append(node.name)

            # Classes
            elif isinstance(node, ast.ClassDef):
                bases = [cls._base_name(b) for b in node.bases]
                signature = f"class {node.name}({', '.join(bases)})"
                doc = ast.get_docstring(node)
                decorators = [
                    ast.unparse(d) if hasattr(ast, "unparse") else cls._decorator_name(d)
                    for d in node.decorator_list
                ]
                refs = cls._find_references(node)

                symbols.append(Symbol(
                    name=node.name,
                    kind="class",
                    file_path=file_path,
                    line=node.lineno,
                    signature=signature,
                    docstring=doc,
                    decorators=decorators,
                    references=refs,
                ))
                if not node.name.startswith("_"):
                    exports.append(node.name)

                # Class methods
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        method_decorators = [
                            ast.unparse(d) if hasattr(ast, "unparse") else cls._decorator_name(d)
                            for d in item.decorator_list
                        ]
                        method_sig = f"{node.name}.{item.name}(...)"
                        method_doc = ast.get_docstring(item)
                        method_refs = cls._find_references(item)
                        symbols.append(Symbol(
                            name=f"{node.name}.{item.name}",
                            kind="method",
                            file_path=file_path,
                            line=item.lineno,
                            signature=method_sig,
                            docstring=method_doc,
                            decorators=method_decorators,
                            references=method_refs,
                        ))

        # Pattern detection
        patterns = cls._detect_patterns(source, tree)

        return symbols, imports, exports, patterns

    @staticmethod
    def _decorator_name(node: ast.expr) -> str:
        """Extract decorator name from AST node."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{ast.unparse(node.value) if hasattr(ast, 'unparse') else '...'}.{node.attr}"
        if isinstance(node, ast.Call):
            return _PythonAnalyzer._decorator_name(node.func)
        return "..."

    @staticmethod
    def _base_name(node: ast.expr) -> str:
        """Extract base class name."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{_PythonAnalyzer._base_name(node.value)}.{node.attr}"
        return "..."

    @staticmethod
    def _find_references(node: ast.AST) -> List[str]:
        """Find all Name references within an AST node."""
        refs: Set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                refs.add(child.id)
        return sorted(refs)

    @staticmethod
    def _detect_patterns(source: str, tree: ast.AST) -> List[str]:
        """Detect architectural and design patterns in the code."""
        patterns: List[str] = []
        source_lower = source.lower()

        # Singleton
        if re.search(r"class\s+\w+.*__new__.*\bcls\b", source):
            patterns.append("singleton")

        # Factory
        if re.search(r"def\s+(create|build|make|factory)\w*", source_lower):
            patterns.append("factory")

        # Decorator pattern
        if re.search(r"def\s+\w+\(.*\):\s*\n\s+def\s+wrapper", source):
            patterns.append("decorator")

        # Observer / event system
        if re.search(r"(subscribe|unsubscribe|emit|dispatch|add_listener|remove_listener|on_\w+)", source_lower):
            patterns.append("observer")

        # Strategy pattern
        if re.search(r"class\s+\w*Strategy", source):
            patterns.append("strategy")

        # Repository pattern
        if re.search(r"class\s+\w*Repository", source):
            patterns.append("repository")

        # Data class
        if re.search(r"@dataclass", source):
            patterns.append("dataclass")

        # Async
        if re.search(r"\basync\s+def\b", source):
            patterns.append("async")

        # Type hints usage
        if re.search(r":\s*(str|int|float|bool|list|dict|tuple|Optional|Union|Any)\b", source):
            patterns.append("typed")

        return patterns


# ============================================================================
# Generic file analyzer (non-Python)
# ============================================================================


class _GenericAnalyzer:
    """Lightweight analysis for non-Python files."""

    IMPORT_PATTERNS: Dict[str, List[str]] = {
        "javascript": [r'(?:import\s+.*?from\s+["\']([^"\']+)["\'])', r'(?:require\s*\(\s*["\']([^"\']+)["\']\s*\))'],
        "typescript": [r'(?:import\s+.*?from\s+["\']([^"\']+)["\'])'],
        "go": [r'(?:import\s+["\']([^"\']+)["\'])', r'(?:import\s*\(\s*(.*?)\s*\))'],
        "rust": [r'(?:use\s+([^;]+);)'],
        "java": [r'(?:import\s+([^;]+);)'],
        "kotlin": [r'(?:import\s+([^\n]+))'],
        "c": [r'(?:#include\s+[<"]([^>"]+)[>"])'],
        "cpp": [r'(?:#include\s+[<"]([^>"]+)[>"])'],
        "ruby": [r'(?:require\s+["\']([^"\']+)["\'])'],
    }

    FUNCTION_PATTERNS: Dict[str, List[str]] = {
        "javascript": [r'function\s+(\w+)', r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(', r'(\w+)\s*:\s*function'],
        "typescript": [r'function\s+(\w+)', r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(', r'(\w+)\s*:\s*function'],
        "go": [r'func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)'],
        "rust": [r'fn\s+(\w+)', r'pub\s+fn\s+(\w+)'],
        "java": [r'(?:public|private|protected|static|\s)+[\w<>\[\]]+\s+(\w+)\s*\(', r'class\s+(\w+)'],
        "kotlin": [r'fun\s+(\w+)', r'class\s+(\w+)'],
        "c": [r'(?:static\s+)?[\w*]+\s+(\w+)\s*\(', r'struct\s+(\w+)'],
        "cpp": [r'(?:virtual\s+)?[\w:<>*&]+\s+(\w+)\s*\(', r'class\s+(\w+)'],
        "ruby": [r'def\s+(\w+)', r'class\s+(\w+)', r'module\s+(\w+)'],
    }

    @classmethod
    def analyze(cls, source: str, file_path: str, language: str) -> Tuple[List[Symbol], List[str], List[str], List[str]]:
        """Extract symbols, imports, exports, patterns from source."""
        symbols: List[Symbol] = []
        imports: List[str] = []
        exports: List[str] = []
        patterns: List[str] = []

        # Extract imports
        for pattern in cls.IMPORT_PATTERNS.get(language, []):
            for match in re.finditer(pattern, source, re.MULTILINE | re.DOTALL):
                imp = match.group(1).strip()
                imports.append(imp)
                symbols.append(Symbol(name=imp, kind="import", file_path=file_path, line=0))

        # Extract functions/classes
        for pattern in cls.FUNCTION_PATTERNS.get(language, []):
            for match in re.finditer(pattern, source):
                name = match.group(1)
                if not name.startswith("_"):
                    exports.append(name)
                symbols.append(Symbol(
                    name=name,
                    kind="function" if "(" in match.group(0) else "class",
                    file_path=file_path,
                    line=source[:match.start()].count("\n") + 1,
                ))

        return symbols, imports, exports, patterns


# ============================================================================
# Main class
# ============================================================================


class UniversalAdapter:
    """Universal Codebase Adapter — instant in-memory codebase understanding.

    Ingests any repository, builds a dependency graph, and provides deep
    analysis of individual files, architecture mapping, pattern search,
    and integration suggestions — all in seconds.

    DNA: The only agent that builds a live semantic model of any foreign
    codebase in seconds, supporting Python, JavaScript, TypeScript, Go,
    Rust, Java, Kotlin, and more.

    Usage:
        adapter = UniversalAdapter()
        adapter.ingest("/path/to/repo")
        analysis = adapter.understand("src/main.py")
        arch = adapter.map_architecture()
        matches = adapter.find_pattern("singleton factory")
    """

    # Files to skip during ingestion
    SKIP_PATTERNS: List[str] = [
        "__pycache__", ".git", ".svn", ".hg",
        "node_modules", "venv", ".venv", "env", ".env",
        "dist", "build", ".build", "target",
        ".next", ".nuxt", ".output",
        "*.pyc", "*.pyo", "*.so", "*.dll", "*.dylib",
        "*.class", "*.o", "*.a", "*.lib",
        "*.min.js", "*.min.css", "*.bundle.js",
        "*.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
        ".DS_Store", "Thumbs.db",
    ]

    # Recognized entry-point filenames
    ENTRY_POINT_NAMES: Set[str] = {
        "main.py", "app.py", "index.py", "run.py", "server.py",
        "main.go", "main.rs", "index.js", "app.js", "server.js",
        "main.ts", "index.ts", "app.ts",
        "Main.java", "Application.java",
        "main.kt",
    }

    def __init__(self):
        self._graph = DependencyGraph()
        self._file_cache: Dict[str, str] = {}  # path → content
        self._analysis_cache: Dict[str, FileAnalysis] = {}
        self._import_to_file: Dict[str, str] = {}  # module_name → file_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(self, repo_path: str, *, max_files: int = 10_000) -> DependencyGraph:
        """Scan entire codebase and build the full dependency graph.

        Walks the repository, detects languages, analyzes every source file,
        resolves imports to file paths, and builds the complete dependency graph
        with cycles detected and stats computed.

        Args:
            repo_path: Path to the repository root.
            max_files: Maximum files to analyze (safety limit).

        Returns:
            The complete DependencyGraph.
        """
        t0 = time.perf_counter()
        repo_path = os.path.abspath(repo_path)

        if not os.path.isdir(repo_path):
            raise ValueError(f"Not a directory: {repo_path}")

        # Reset state
        self._graph = DependencyGraph()
        self._file_cache.clear()
        self._analysis_cache.clear()
        self._import_to_file.clear()

        # ----- Pass 1: Find and classify all files -----
        files: List[str] = []
        for root, dirs, filenames in os.walk(repo_path):
            # Filter directories
            dirs[:] = [
                d for d in dirs
                if not any(fnmatch.fnmatch(d, pat) for pat in self.SKIP_PATTERNS)
            ]
            for fname in filenames:
                fpath = os.path.join(root, fname)
                if any(fnmatch.fnmatch(fname, pat) for pat in self.SKIP_PATTERNS):
                    continue
                lang = _LanguageDetector.detect(fpath)
                if lang != "unknown":
                    files.append(fpath)

                if len(files) >= max_files:
                    break
            if len(files) >= max_files:
                break

        # ----- Pass 2: Analyze each file -----
        for fpath in files:
            try:
                analysis = self._analyze_file(fpath)
                self._analysis_cache[fpath] = analysis
                self._graph.nodes[fpath] = analysis
                # Index exports for import resolution
                for exp in analysis.exports:
                    module_base = os.path.splitext(os.path.basename(fpath))[0]
                    self._import_to_file[module_base] = fpath
                    self._import_to_file[exp] = fpath
            except Exception:
                continue  # Skip files we cannot parse

        # ----- Pass 3: Resolve dependencies -----
        for fpath, analysis in self._analysis_cache.items():
            for imp in analysis.imports:
                resolved = self._resolve_import(imp, fpath)
                if resolved and resolved in self._analysis_cache:
                    analysis.dependencies.append(resolved)
                    self._graph.edges.append((fpath, resolved))
                    if resolved in self._analysis_cache:
                        self._analysis_cache[resolved].dependents.append(fpath)

        # Deduplicate edges
        self._graph.edges = list(set(self._graph.edges))

        # ----- Pass 4: Find entry points and leaf nodes -----
        all_deps: Set[str] = set()
        for _, dep in self._graph.edges:
            all_deps.add(dep)

        for fpath in self._analysis_cache:
            fname = os.path.basename(fpath)
            if fname in self.ENTRY_POINT_NAMES:
                self._graph.entry_points.append(fpath)
            # Also consider files with no incoming edges
            if fpath not in all_deps:
                if fpath not in self._graph.entry_points:
                    self._graph.entry_points.append(fpath)

        for fpath, analysis in self._analysis_cache.items():
            if not analysis.dependencies:
                self._graph.leaf_nodes.append(fpath)

        # ----- Pass 5: Detect cycles -----
        self._graph.cycles = self._detect_cycles()

        # ----- Stats -----
        total_lines = sum(a.lines for a in self._analysis_cache.values())
        total_size = sum(a.size_bytes for a in self._analysis_cache.values())
        languages = set(a.language for a in self._analysis_cache.values())

        self._graph.stats = {
            "repo_path": repo_path,
            "total_files_analyzed": len(self._analysis_cache),
            "total_lines": total_lines,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "languages": sorted(languages),
            "entry_points": len(self._graph.entry_points),
            "leaf_nodes": len(self._graph.leaf_nodes),
            "total_edges": len(self._graph.edges),
            "cycles_found": len(self._graph.cycles),
            "ingest_time_ms": round((time.perf_counter() - t0) * 1000, 1),
        }

        return self._graph

    def understand(self, file_path: str) -> Optional[FileAnalysis]:
        """Deep analysis of a single file: imports, exports, symbols, patterns.

        Args:
            file_path: Path to the file (absolute or relative to ingested repo).

        Returns:
            FileAnalysis with full symbol table, or None if not found.
        """
        if file_path in self._analysis_cache:
            return self._analysis_cache[file_path]

        # Try relative path from repo root
        repo = self._graph.stats.get("repo_path", "")
        if repo:
            full = os.path.join(repo, file_path)
            if full in self._analysis_cache:
                return self._analysis_cache[full]

        # Analyze fresh
        if os.path.isfile(file_path):
            return self._analyze_file(file_path)

        return None

    def map_architecture(self) -> ArchitectureMap:
        """Generate an architecture diagram from the ingested codebase.

        Analyzes the dependency graph to identify layers, modules, data flow,
        and anti-patterns. Returns both a structured description and an ASCII
        diagram.

        Returns:
            ArchitectureMap describing the codebase structure.
        """
        if not self._graph.nodes:
            raise RuntimeError("No codebase ingested. Call ingest() first.")

        # Identify layers by directory depth and naming
        layers: Dict[str, List[str]] = defaultdict(list)
        all_dirs: Set[str] = set()

        for fpath in self._analysis_cache:
            rel = self._relative_path(fpath)
            parts = rel.split(os.sep)
            if len(parts) >= 1:
                top = parts[0] if parts[0] else parts[1] if len(parts) > 1 else "root"
                layers[top].append(fpath)
                all_dirs.add(os.path.dirname(fpath))

        # External dependencies (imports that don't resolve to ingested files)
        external: Set[str] = set()
        for analysis in self._analysis_cache.values():
            for imp in analysis.imports:
                if not self._resolve_import(imp, analysis.path):
                    external.add(imp.split(".")[0])

        # Internal modules
        internal = sorted(set(
            os.path.splitext(os.path.basename(f))[0]
            for f in self._analysis_cache
        ))

        # Data flow: trace from entry points to leaves
        data_flow: List[str] = []
        for ep in self._graph.entry_points[:5]:
            base = os.path.basename(ep)
            deps = self._analysis_cache.get(ep, FileAnalysis(path=ep, language="", lines=0, size_bytes=0)).dependencies
            dep_names = [os.path.basename(d) for d in deps[:5]]
            if dep_names:
                data_flow.append(f"{base} → {', '.join(dep_names)}")
            else:
                data_flow.append(f"{base} (no dependencies)")

        # Anti-patterns
        anti_patterns: List[str] = []
        if len(self._graph.cycles) > 0:
            anti_patterns.append(
                f"Circular dependencies detected: {len(self._graph.cycles)} cycle(s) — "
                f"{self._graph.cycles[0][:3]}..."
            )
        # Check for high fan-in (too many dependents)
        for fpath, analysis in self._analysis_cache.items():
            if len(analysis.dependents) > 10:
                anti_patterns.append(
                    f"High fan-in: {os.path.basename(fpath)} has {len(analysis.dependents)} dependents"
                )
        # Check for files with > 500 lines
        large_files = [
            os.path.basename(f) for f, a in self._analysis_cache.items()
            if a.lines > 500
        ]
        if large_files:
            anti_patterns.append(f"Large files (>500 lines): {', '.join(large_files[:5])}")

        # ASCII diagram
        ascii_diagram = self._generate_ascii_diagram(layers)

        return ArchitectureMap(
            layers=[
                {"name": name, "files": files[:10], "purpose": self._infer_layer_purpose(name, files)}
                for name, files in sorted(layers.items())
            ],
            external_deps=sorted(external),
            internal_modules=sorted(internal),
            data_flow=data_flow,
            anti_patterns=anti_patterns,
            diagram_ascii=ascii_diagram,
        )

    def find_pattern(self, description: str) -> List[Tuple[str, str]]:
        """Find code matching an intent or pattern description.

        Searches symbol names, patterns, and file contents for matches.
        Returns file-path + matched-content pairs.

        Args:
            description: Natural language description of what to find.
                        Examples: "singleton", "database connection", "auth middleware",
                        "rate limiter", "retry logic".

        Returns:
            List of (file_path, snippet) tuples.
        """
        if not self._graph.nodes:
            return []

        # Tokenize description
        tokens = set(re.findall(r"\w+", description.lower()))
        if not tokens:
            return []

        matches: List[Tuple[str, str, int]] = []  # (file, snippet, score)

        for fpath, analysis in self._analysis_cache.items():
            score = 0
            snippets: List[str] = []

            # Check symbol names
            for sym in analysis.symbols:
                sym_lower = sym.name.lower()
                if any(t in sym_lower for t in tokens):
                    score += 2
                    snippets.append(f"  Symbol: {sym.name} ({sym.kind}) line {sym.line}")
                if sym.docstring and any(t in sym.docstring.lower() for t in tokens):
                    score += 1
                    snippets.append(f"  Docstring match in {sym.name}")

            # Check detected patterns
            for pat in analysis.patterns:
                if any(t in pat.lower() for t in tokens):
                    score += 3
                    snippets.append(f"  Pattern: {pat}")

            # Check imports
            for imp in analysis.imports:
                if any(t in imp.lower() for t in tokens):
                    score += 1
                    snippets.append(f"  Import: {imp}")

            # Deep search: grep for tokens in file content
            if fpath in self._file_cache:
                content = self._file_cache[fpath]
                for tok in tokens:
                    if len(tok) >= 3:  # Skip very short tokens for grep
                        for match in re.finditer(re.escape(tok), content, re.I):
                            line_no = content[:match.start()].count("\n") + 1
                            # Extract surrounding line
                            line_start = content.rfind("\n", 0, match.start()) + 1
                            line_end = content.find("\n", match.end())
                            line = content[line_start:line_end].strip()[:120]
                            snippets.append(f"  Line {line_no}: {line}")
                            score += 1
                            if len(snippets) >= 5:
                                break
                    if len(snippets) >= 5:
                        break

            if score > 0:
                matches.append((fpath, "\n".join(snippets[:8]), score))

        # Sort by score descending
        matches.sort(key=lambda x: x[2], reverse=True)
        return [(path, snippet) for path, snippet, _ in matches[:20]]

    def suggest_integration(self, library: str) -> IntegrationSuggestion:
        """Suggest how to integrate an external library into the codebase.

        Analyzes the codebase to find the best integration points, identifies
        potential compatibility issues, and provides example code.

        Args:
            library: Name of the library to integrate (e.g., "redis", "pydantic", "fastapi").

        Returns:
            IntegrationSuggestion with entry points, issues, and example code.
        """
        if not self._graph.nodes:
            raise RuntimeError("No codebase ingested. Call ingest() first.")

        lib_lower = library.lower()

        # Find relevant entry points
        entry_points: List[str] = []
        compatibility_issues: List[str] = []
        changes: List[str] = []

        for fpath, analysis in self._analysis_cache.items():
            # Check if file already uses this library
            for imp in analysis.imports:
                if lib_lower in imp.lower():
                    entry_points.append(fpath)
                    break

        # If not found, suggest files based on purpose matching
        if not entry_points:
            # Check for config files, main files, init files
            for fpath in self._analysis_cache:
                fname = os.path.basename(fpath).lower()
                if any(kw in fname for kw in ["config", "settings", "init", "main", "app", "core"]):
                    entry_points.append(fpath)

        # Detect compatibility issues
        languages = self._graph.stats.get("languages", [])
        if "python" in languages:
            changes.append(f"Add `{library}` to requirements.txt or pyproject.toml")
            changes.append(f"Import {library} in relevant modules")
        elif "javascript" in languages or "typescript" in languages:
            changes.append(f"Run `npm install {library}` or `yarn add {library}`")
            changes.append(f"Add import statement in relevant modules")
        else:
            compatibility_issues.append(f"Primary language(s): {', '.join(languages)} — verify {library} supports these")

        # Check for existing similar libraries that might conflict
        for fpath, analysis in self._analysis_cache.items():
            for imp in analysis.imports:
                imp_base = imp.split(".")[0]
                if imp_base != lib_lower and self._is_similar_library(imp_base, lib_lower):
                    compatibility_issues.append(
                        f"Existing similar library found: {imp_base} in {os.path.basename(fpath)}"
                    )

        # Estimate effort
        effort = "low"
        if len(entry_points) > 5:
            effort = "medium"
        if compatibility_issues:
            effort = "high"
        if len(self._analysis_cache) > 500:
            effort = "high" if effort == "medium" else effort

        # Example code
        example = self._generate_integration_example(library, languages)

        return IntegrationSuggestion(
            library=library,
            entry_points=entry_points[:10] or [os.path.basename(p) for p in self._graph.entry_points[:3]],
            compatibility_issues=compatibility_issues,
            required_changes=changes,
            estimated_effort=effort,
            example_code=example,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _analyze_file(self, file_path: str) -> FileAnalysis:
        """Analyze a single file and return its FileAnalysis."""
        lang = _LanguageDetector.detect(file_path)

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            content = ""

        self._file_cache[file_path] = content
        lines = content.count("\n") + 1 if content else 0
        size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

        symbols: List[Symbol] = []
        imports: List[str] = []
        exports: List[str] = []
        patterns: List[str] = []

        if lang == "python":
            symbols, imports, exports, patterns = _PythonAnalyzer.analyze(content, file_path)
        elif lang in _GenericAnalyzer.FUNCTION_PATTERNS:
            symbols, imports, exports, patterns = _GenericAnalyzer.analyze(content, file_path, lang)
        elif lang in ("json", "yaml", "toml"):
            exports = [os.path.splitext(os.path.basename(file_path))[0]]

        # Complexity hint
        complexity = "simple"
        if len(symbols) > 20 or lines > 300:
            complexity = "moderate"
        if len(symbols) > 50 or lines > 800 or len(imports) > 20:
            complexity = "complex"

        return FileAnalysis(
            path=file_path,
            language=lang,
            lines=lines,
            size_bytes=size,
            imports=imports,
            exports=exports,
            symbols=symbols,
            patterns=patterns,
            complexity_hint=complexity,
        )

    def _resolve_import(self, imp: str, from_file: str) -> Optional[str]:
        """Resolve an import string to a file path in the codebase."""
        # Check direct mapping
        if imp in self._import_to_file:
            return self._import_to_file[imp]

        # Try module base name
        base = imp.split(".")[0]
        if base in self._import_to_file:
            return self._import_to_file[base]

        # Try relative to the importing file's directory
        imp_dir = os.path.dirname(from_file)
        for ext in (".py", ".js", ".ts", ".go", ".rs"):
            candidate = os.path.join(imp_dir, imp.replace(".", os.sep) + ext)
            if candidate in self._analysis_cache:
                return candidate
            candidate = os.path.join(imp_dir, imp.replace(".", os.sep), "__init__.py")
            if candidate in self._analysis_cache:
                return candidate

        return None

    def _relative_path(self, fpath: str) -> str:
        """Get path relative to the ingested repo root."""
        repo = self._graph.stats.get("repo_path", "")
        if repo and fpath.startswith(repo):
            return os.path.relpath(fpath, repo)
        return fpath

    def _detect_cycles(self) -> List[List[str]]:
        """Detect cycles in the dependency graph using DFS."""
        adj: Dict[str, List[str]] = defaultdict(list)
        for node in self._analysis_cache:
            adj[node] = self._analysis_cache[node].dependencies

        cycles: List[List[str]] = []
        visited: Set[str] = set()
        rec_stack: Set[str] = set()
        path: List[str] = []

        def dfs(node: str) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    dfs(neighbor)
                elif neighbor in rec_stack:
                    # Found cycle
                    cycle_start = path.index(neighbor)
                    cycles.append(path[cycle_start:] + [neighbor])

            path.pop()
            rec_stack.discard(node)

        for node in adj:
            if node not in visited:
                dfs(node)

        return cycles

    def _generate_ascii_diagram(self, layers: Dict[str, List[str]]) -> str:
        """Generate a simple ASCII architecture diagram."""
        lines = ["", "ARCHITECTURE DIAGRAM", "=" * 48, ""]

        for layer_name, files in sorted(layers.items()):
            if len(files) <= 1:
                continue
            lines.append(f"[ {layer_name.upper()} ]")
            lines.append("│")
            for f in files[:8]:
                fname = os.path.basename(f)
                deps = self._analysis_cache.get(f, FileAnalysis(path=f, language="", lines=0, size_bytes=0)).dependents
                dep_count = len(deps)
                connector = "├──" if f != files[min(7, len(files) - 1)] else "└──"
                lines.append(f"  {connector} {fname} (← {dep_count})")
            if len(files) > 8:
                lines.append(f"  └── ... and {len(files) - 8} more")
            lines.append("")

        if self._graph.cycles:
            lines.append(f"CYCLE WARNING: {len(self._graph.cycles)} circular dependencies")
            for cycle in self._graph.cycles[:2]:
                lines.append(f"  {' → '.join(os.path.basename(f) for f in cycle)}")

        return "\n".join(lines)

    @staticmethod
    def _infer_layer_purpose(name: str, files: List[str]) -> str:
        """Infer the purpose of a layer from its name and contents."""
        name_lower = name.lower()
        if any(kw in name_lower for kw in ["test", "spec", "mock", "fixture"]):
            return "Testing"
        if any(kw in name_lower for kw in ["config", "settings", "env", "dotenv"]):
            return "Configuration"
        if any(kw in name_lower for kw in ["db", "database", "model", "schema", "migration"]):
            return "Data layer"
        if any(kw in name_lower for kw in ["api", "route", "handler", "controller", "view"]):
            return "API / Presentation layer"
        if any(kw in name_lower for kw in ["service", "business", "logic", "domain", "use_case", "usecase"]):
            return "Business logic / Services"
        if any(kw in name_lower for kw in ["util", "helper", "lib", "common", "shared", "core"]):
            return "Utilities / Shared"
        if any(kw in name_lower for kw in ["script", "tool", "cli", "bin"]):
            return "Scripts / Tools"
        if any(kw in name_lower for kw in ["doc", "docs", "readme"]):
            return "Documentation"
        return "Module"

    @staticmethod
    def _is_similar_library(lib_a: str, lib_b: str) -> bool:
        """Check if two libraries might serve similar purposes."""
        similar_groups = [
            {"requests", "httpx", "aiohttp", "urllib3", "treq"},
            {"sqlalchemy", "peewee", "pony", "tortoise-orm", "django-orm"},
            {"flask", "fastapi", "django", "starlette", "sanic", "aiohttp"},
            {"pydantic", "marshmallow", "attrs", "dataclasses"},
            {"redis", "memcached", "aiocache"},
            {"celery", "rq", "huey", "dramatiq", "arq"},
            {"pytest", "unittest", "nose", "doctest"},
            {"react", "vue", "angular", "svelte", "solid"},
            {"express", "koa", "fastify", "hapi", "nestjs"},
        ]
        for group in similar_groups:
            norm = {g.lower() for g in group}
            if lib_a.lower() in norm and lib_b.lower() in norm:
                return True
        return False

    def _generate_integration_example(self, library: str, languages: List[str]) -> str:
        """Generate example integration code snippet."""
        lib = library.lower()

        if "python" in languages:
            return (
                f"# Example: integrating {library}\n"
                f"import {lib}\n\n"
                f"# Initialize\n"
                f"client = {lib}.Client()\n\n"
                f"# Use in your service layer\n"
                f"result = client.operation()\n"
            )
        elif "javascript" in languages or "typescript" in languages:
            return (
                f"// Example: integrating {library}\n"
                f"import {{ Client }} from '{lib}';\n\n"
                f"// Initialize\n"
                f"const client = new Client();\n\n"
                f"// Use in your service\n"
                f"const result = await client.operation();\n"
            )
        return f"// Integration example for {library} (auto-generated stub)"


# ============================================================================
# Self-test
# ============================================================================

def _self_test() -> None:
    """Run comprehensive self-tests on the UniversalAdapter."""
    import tempfile

    print("=== UniversalAdapter Self-Test ===\n")

    # Create a temporary test repo
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create some test files
        files = {
            "main.py": (
                "import config\n"
                "from services.user_service import create_user\n\n"
                "def main():\n"
                '    """Entry point."""\n'
                "    cfg = config.load()\n"
                "    user = create_user('test')\n"
                "    return user\n"
            ),
            "config.py": (
                "def load():\n"
                '    """Load configuration."""\n'
                "    return {'db': 'sqlite:///:memory:'}\n"
            ),
            "services/__init__.py": "",
            "services/user_service.py": (
                "from models.user import User\n\n"
                "def create_user(name: str) -> User:\n"
                '    """Create a new user."""\n'
                "    return User(name=name)\n\n"
                "def delete_user(user_id: int) -> bool:\n"
                '    """Delete a user."""\n'
                "    return True\n"
            ),
            "models/__init__.py": "",
            "models/user.py": (
                "from dataclasses import dataclass\n\n"
                "@dataclass\n"
                "class User:\n"
                '    """User model."""\n'
                "    name: str\n"
                "    id: int = 0\n"
            ),
        }

        for fpath, content in files.items():
            full_path = os.path.join(tmpdir, fpath)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w") as f:
                f.write(content)

        adapter = UniversalAdapter()

        # Test 1: Ingest
        print("Test 1: Ingest repo")
        graph = adapter.ingest(tmpdir)
        assert len(graph.nodes) > 0, "Expected nodes in graph"
        assert graph.stats["total_files_analyzed"] >= 3  # 5 files, but __init__ has no symbols
        print(f"  Files: {graph.stats['total_files_analyzed']}")
        print(f"  Lines: {graph.stats['total_lines']}")
        print(f"  Languages: {graph.stats['languages']}")
        print(f"  Ingest time: {graph.stats['ingest_time_ms']}ms")
        print("  PASS\n")

        # Test 2: Understand
        print("Test 2: Understand a file")
        analysis = adapter.understand(os.path.join(tmpdir, "main.py"))
        assert analysis is not None
        assert analysis.language == "python"
        assert len(analysis.imports) > 0
        assert "main" in analysis.exports
        print(f"  File: {os.path.basename(analysis.path)}")
        print(f"  Language: {analysis.language}")
        print(f"  Imports: {analysis.imports}")
        print(f"  Exports: {analysis.exports}")
        print(f"  Symbols: {[s.name for s in analysis.symbols]}")
        print("  PASS\n")

        # Test 3: Map architecture
        print("Test 3: Map architecture")
        arch = adapter.map_architecture()
        assert len(arch.layers) > 0
        print(f"  Layers: {len(arch.layers)}")
        for layer in arch.layers:
            print(f"    {layer['name']}: {layer['purpose']}")
        print(f"  External deps: {arch.external_deps}")
        print(f"  Anti-patterns: {arch.anti_patterns if arch.anti_patterns else 'none'}")
        print(arch.diagram_ascii[:300])
        print("  PASS\n")

        # Test 4: Find pattern
        print("Test 4: Find pattern")
        matches = adapter.find_pattern("dataclass user")
        assert len(matches) > 0, "Should find dataclass pattern"
        for fpath, snippet in matches:
            print(f"  {os.path.basename(fpath)}:")
            print(f"    {snippet[:100]}")
        print("  PASS\n")

        # Test 5: Suggest integration
        print("Test 5: Suggest integration")
        suggestion = adapter.suggest_integration("pydantic")
        assert suggestion.estimated_effort in ("low", "medium", "high")
        print(f"  Library: {suggestion.library}")
        print(f"  Entry points: {[os.path.basename(e) for e in suggestion.entry_points[:3]]}")
        print(f"  Effort: {suggestion.estimated_effort}")
        print(f"  Issues: {suggestion.compatibility_issues if suggestion.compatibility_issues else 'none'}")
        print(f"  Example:\n{suggestion.example_code[:150]}")
        print("  PASS\n")

    print("=== All UniversalAdapter tests passed ===")


if __name__ == "__main__":
    _self_test()