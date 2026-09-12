"""File system tools — read, write, patch, search files."""

from pathlib import Path


def read_file(path: str, offset: int = 0, limit: int = 200) -> str:
    """Read a file. Use offset/limit for large files."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return f"File not found: {path}"
    if p.is_dir():
        return f"'{path}' is a directory. Files: {', '.join(sorted(f.name for f in p.iterdir())[:50])}"

    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Error reading {path}: {e}"

    lines = text.split("\n")
    if offset > 0:
        lines = lines[offset:]
    if limit > 0:
        lines = lines[:limit]

    result = "\n".join(lines)
    if len(lines) < len(text.split("\n")) - offset:
        result += f"\n\n[... {len(text.split('\n')) - offset - len(lines)} more lines]"
    return result


def write_file(path: str, content: str) -> str:
    """Write content to a file. Overwrites existing content."""
    p = Path(path).expanduser().resolve()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Written {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error writing {path}: {e}"


def list_files(directory: str = ".", pattern: str = "*", max_files: int = 100) -> str:
    """List files in a directory, optionally filtered by glob pattern."""
    p = Path(directory).expanduser().resolve()
    if not p.exists():
        return f"Directory not found: {directory}"
    if not p.is_dir():
        return f"'{directory}' is not a directory"

    files = sorted(p.glob(pattern))[:max_files]
    if not files:
        return f"No files matching '{pattern}' in {directory}"

    lines = []
    for f in files:
        suffix = "/" if f.is_dir() else ""
        try:
            size = f.stat().st_size
            lines.append(f"{f.name}{suffix} ({_human_size(size)})")
        except OSError:
            lines.append(f"{f.name}{suffix}")

    return "\n".join(lines)


def search_files(query: str, directory: str = ".", file_pattern: str = "*") -> str:
    """Search for text in files. Returns matching lines with file paths."""
    import fnmatch

    p = Path(directory).expanduser().resolve()
    if not p.exists():
        return f"Directory not found: {directory}"

    results = []
    for f in p.rglob(file_pattern):
        if f.is_file() and f.suffix in (".py", ".md", ".txt", ".json", ".yaml",
                                          ".yml", ".toml", ".js", ".ts", ".html",
                                          ".css", ".kt", ".java", ".rs", ".go"):
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(content.split("\n"), 1):
                    if query.lower() in line.lower():
                        results.append(f"{f}:{i}: {line.strip()[:120]}")
                        if len(results) >= 50:
                            break
            except Exception:
                continue
        if len(results) >= 50:
            break

    if not results:
        return f"No matches for '{query}'"
    return "\n".join(results)


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size}{unit}"
        size //= 1024
    return f"{size}TB"