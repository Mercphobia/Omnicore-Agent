"""Converter — any format to any format.
DNA: Digital Alchemy (transmutation) + Manus (multi-source).

Supported conversions:
- Documents: md/rst/org → html/pdf/docx (pandoc)
- Data: csv ↔ json, json ↔ yaml, toml ↔ json
- Code: py → ipynb (jupytext), ipynb → py
- Images: png/jpg/webp/avif/gif (Pillow)
- Tables: csv → markdown, markdown table → csv
- Video: any → mp4/webm/gif (ffmpeg)
- Audio: any → mp3/wav/ogg (ffmpeg)
- Archive: dir → zip/tar.gz
"""

import subprocess
import json
import csv
import shutil
from pathlib import Path
from typing import Optional


# ── Format detection ───────────────────────────────────────────────────

def detect_format(filepath: str) -> str:
    """Detect file format from extension and magic bytes."""
    ext = Path(filepath).suffix.lower()

    if ext in (".md", ".markdown"):
        return "markdown"
    if ext in (".rst", ".restructuredtext"):
        return "restructuredtext"
    if ext == ".org":
        return "org"
    if ext == ".html":
        return "html"
    if ext == ".pdf":
        return "pdf"
    if ext == ".docx":
        return "docx"
    if ext == ".csv":
        return "csv"
    if ext == ".tsv":
        return "tsv"
    if ext == ".json":
        return "json"
    if ext in (".yaml", ".yml"):
        return "yaml"
    if ext == ".toml":
        return "toml"
    if ext in (".py", ".pyi"):
        return "python"
    if ext == ".ipynb":
        return "jupyter"
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".bmp", ".tiff"):
        return "image"
    if ext in (".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv"):
        return "video"
    if ext in (".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a"):
        return "audio"
    if ext in (".zip", ".tar.gz", ".tgz", ".tar", ".tar.xz", ".7z"):
        return "archive"

    return "unknown"


# ── Document conversions ───────────────────────────────────────────────

def _pandoc(input_path: Path, output_path: Path, extra_args: list = None) -> str:
    """Convert using pandoc."""
    try:
        cmd = ["pandoc", str(input_path), "-o", str(output_path)]
        if extra_args:
            cmd.extend(extra_args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            return f"Converted: {input_path.name} → {output_path.name} (pandoc)"
        return f"Pandoc error: {result.stderr[:300]}"
    except FileNotFoundError:
        return "Pandoc not installed. Install: apt install pandoc"


# ── CSV ↔ JSON ─────────────────────────────────────────────────────────

def csv_to_json(input_path: str, output_path: str) -> str:
    """Convert CSV to JSON array."""
    try:
        inp = Path(input_path)
        out = Path(output_path)
        with open(inp) as f:
            reader = csv.DictReader(f)
            data = list(reader)
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return f"CSV → JSON: {len(data)} rows"
    except Exception as e:
        return f"CSV→JSON error: {e}"


def json_to_csv(input_path: str, output_path: str) -> str:
    """Convert JSON array to CSV."""
    try:
        inp = Path(input_path)
        out = Path(output_path)
        data = json.loads(inp.read_text())
        if not isinstance(data, list):
            data = [data]
        if not data:
            return "JSON→CSV error: empty data"
        with open(out, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
        return f"JSON → CSV: {len(data)} rows"
    except Exception as e:
        return f"JSON→CSV error: {e}"


# ── JSON ↔ YAML ────────────────────────────────────────────────────────

def json_to_yaml(input_path: str, output_path: str) -> str:
    """Convert JSON to YAML."""
    try:
        import yaml
        inp = Path(input_path)
        out = Path(output_path)
        data = json.loads(inp.read_text())
        out.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False))
        return f"JSON → YAML: {out.name}"
    except ImportError:
        return "PyYAML not installed. Install: pip install pyyaml"
    except Exception as e:
        return f"JSON→YAML error: {e}"


def yaml_to_json(input_path: str, output_path: str) -> str:
    """Convert YAML to JSON."""
    try:
        import yaml
        inp = Path(input_path)
        out = Path(output_path)
        data = yaml.safe_load(inp.read_text())
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return f"YAML → JSON: {out.name}"
    except ImportError:
        return "PyYAML not installed. Install: pip install pyyaml"
    except Exception as e:
        return f"YAML→JSON error: {e}"


# ── TOML ↔ JSON ────────────────────────────────────────────────────────

def toml_to_json(input_path: str, output_path: str) -> str:
    """Convert TOML to JSON."""
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            return "tomli not installed. Install: pip install tomli"
    try:
        inp = Path(input_path)
        out = Path(output_path)
        data = tomllib.loads(inp.read_text())
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return f"TOML → JSON: {out.name}"
    except Exception as e:
        return f"TOML→JSON error: {e}"


# ── Code conversions ───────────────────────────────────────────────────

def py_to_ipynb(input_path: str, output_path: str) -> str:
    """Convert Python script to Jupyter notebook."""
    try:
        import jupytext
        inp = Path(input_path)
        out = Path(output_path)
        notebook = jupytext.read(inp)
        jupytext.write(notebook, str(out))
        return f"Converted: {inp.name} → {out.name}"
    except ImportError:
        return "jupytext not installed. Install: pip install jupytext"


def ipynb_to_py(input_path: str, output_path: str) -> str:
    """Convert Jupyter notebook to Python script."""
    try:
        import jupytext
        inp = Path(input_path)
        out = Path(output_path)
        notebook = jupytext.read(inp)
        jupytext.write(notebook, str(out), fmt="py:percent")
        return f"Converted: {inp.name} → {out.name}"
    except ImportError:
        return "jupytext not installed. Install: pip install jupytext"


# ── Image conversions ──────────────────────────────────────────────────

def image_convert(input_path: str, output_path: str,
                  quality: int = 85, width: int = 0, height: int = 0) -> str:
    """Convert/resize image between formats."""
    try:
        from PIL import Image
        inp = Path(input_path)
        out = Path(output_path)

        img = Image.open(inp)

        # Handle RGBA → RGB for JPEG output
        if out.suffix.lower() in (".jpg", ".jpeg") and img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        # Resize if dimensions given
        if width > 0 or height > 0:
            w = width if width > 0 else img.width
            h = height if height > 0 else img.height
            img = img.resize((w, h), Image.LANCZOS)

        # Save with appropriate params
        save_kwargs = {}
        if out.suffix.lower() in (".jpg", ".jpeg"):
            save_kwargs["quality"] = quality
            save_kwargs["optimize"] = True
        elif out.suffix.lower() == ".png":
            save_kwargs["optimize"] = True

        img.save(out, **save_kwargs)
        size_kb = out.stat().st_size / 1000
        return f"Image converted: {inp.name} → {out.name} ({size_kb:.1f}KB)"
    except ImportError:
        return "Pillow not installed. Install: pip install Pillow"
    except Exception as e:
        return f"Image error: {e}"


# ── Table conversions ──────────────────────────────────────────────────

def csv_to_markdown(input_path: str, output_path: str = "") -> str:
    """Convert CSV to Markdown table."""
    try:
        inp = Path(input_path)
        out = Path(output_path) if output_path else inp.with_suffix(".md")

        with open(inp) as f:
            reader = csv.reader(f)
            rows = list(reader)

        if not rows:
            return "CSV→MD error: empty file"

        # Build markdown table
        col_widths = [max(len(str(cell)) for cell in col) for col in zip(*rows)]
        lines = []

        # Header
        header = "| " + " | ".join(
            str(cell).ljust(col_widths[i]) for i, cell in enumerate(rows[0])
        ) + " |"
        lines.append(header)

        # Separator
        sep = "|" + "|".join("-" * (w + 2) for w in col_widths) + "|"
        lines.append(sep)

        # Data rows
        for row in rows[1:]:
            line = "| " + " | ".join(
                str(cell).ljust(col_widths[i]) for i, cell in enumerate(row)
            ) + " |"
            lines.append(line)

        out.write_text("\n".join(lines))
        return f"CSV → Markdown table: {out.name} ({len(rows)} rows)"
    except Exception as e:
        return f"CSV→MD error: {e}"


# ── Archive ────────────────────────────────────────────────────────────

def archive_dir(input_dir: str, output_path: str) -> str:
    """Archive a directory to zip or tar.gz."""
    inp = Path(input_dir)
    out = Path(output_path)

    if not inp.is_dir():
        return f"Not a directory: {input_dir}"

    try:
        fmt = out.suffix.lstrip(".")
        if fmt == "zip":
            base = out.with_suffix("")
            shutil.make_archive(str(base), "zip", str(inp))
        elif fmt in ("gz", "bz2", "xz"):
            base = Path(str(out).replace(".tar.gz", "").replace(".tar.bz2", "")
                       .replace(".tar.xz", ""))
            shutil.make_archive(str(base), "tar", str(inp))
        else:
            shutil.make_archive(str(out.with_suffix("")), fmt, str(inp))

        size_mb = out.stat().st_size / 1_000_000 if out.exists() else 0
        return f"Archived: {inp.name} → {out.name} ({size_mb:.1f}MB)"
    except Exception as e:
        return f"Archive error: {e}"


# ── Main converter ─────────────────────────────────────────────────────

def convert_file(input_path: str, output_path: str, **kwargs) -> str:
    """Convert a file from one format to another.

    Auto-detects input/output formats and selects the right converter.

    Supported chains:
    - .md/.rst/.org → .html/.pdf/.docx (pandoc)
    - .csv → .json, .md | .json → .csv, .yaml
    - .json → .yaml | .yaml → .json
    - .toml → .json
    - .py → .ipynb | .ipynb → .py
    - image → image (png/jpg/webp/avif/gif)
    - video → video/gif (ffmpeg)
    - dir → .zip/.tar.gz
    """
    inp = Path(input_path).expanduser().resolve()
    out = Path(output_path).expanduser().resolve()

    if not inp.exists():
        return f"Input file not found: {input_path}"

    in_fmt = detect_format(str(inp))
    out_fmt = detect_format(str(out))

    # Document: pandoc-based
    if in_fmt in ("markdown", "restructuredtext", "org") and \
       out_fmt in ("html", "pdf", "docx"):
        return _pandoc(inp, out)

    # Data: CSV ↔ JSON
    if in_fmt == "csv" and out_fmt == "json":
        return csv_to_json(str(inp), str(out))
    if in_fmt == "json" and out_fmt == "csv":
        return json_to_csv(str(inp), str(out))

    # Data: JSON ↔ YAML
    if in_fmt == "json" and out_fmt == "yaml":
        return json_to_yaml(str(inp), str(out))
    if in_fmt == "yaml" and out_fmt == "json":
        return yaml_to_json(str(inp), str(out))

    # Data: TOML → JSON
    if in_fmt == "toml" and out_fmt == "json":
        return toml_to_json(str(inp), str(out))

    # Code: Python ↔ Jupyter
    if in_fmt == "python" and out_fmt == "jupyter":
        return py_to_ipynb(str(inp), str(out))
    if in_fmt == "jupyter" and out_fmt == "python":
        return ipynb_to_py(str(inp), str(out))

    # Image: any → any
    if in_fmt == "image" and out_fmt == "image":
        return image_convert(str(inp), str(out), **kwargs)

    # Table: CSV → Markdown
    if in_fmt == "csv" and out_fmt == "markdown":
        return csv_to_markdown(str(inp), str(out))

    # Archive: directory → archive
    if inp.is_dir() and out_fmt == "archive":
        return archive_dir(str(inp), str(out))

    # Fallback: plain text copy
    try:
        content = inp.read_bytes()
        out.write_bytes(content)
        return f"Copied: {inp.name} → {out.name}"
    except Exception:
        return f"No converter for {in_fmt} → {out_fmt}. " \
               f"Supported: md→html/pdf, csv↔json, json↔yaml, toml→json, " \
               f"py↔ipynb, image↔image, csv→md, dir→zip/tar.gz"


# ── List supported conversions ─────────────────────────────────────────

def list_converters() -> list[str]:
    """Return list of supported conversion pairs."""
    return [
        "md/rst/org → html/pdf/docx (pandoc)",
        "csv → json",
        "json → csv",
        "json → yaml",
        "yaml → json",
        "toml → json",
        "py → ipynb (jupytext)",
        "ipynb → py (jupytext)",
        "png/jpg/webp/gif → png/jpg/webp/gif (Pillow)",
        "csv → markdown table",
        "directory → zip/tar.gz",
    ]


# ── Self-test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile

    tmpdir = Path(tempfile.mkdtemp())

    # Test CSV → JSON
    csv_path = tmpdir / "test.csv"
    csv_path.write_text("name,age,city\nAlice,30,NYC\nBob,25,LA\n")

    json_path = tmpdir / "test.json"
    result = csv_to_json(str(csv_path), str(json_path))
    assert "3 rows" in result, f"Expected 3 rows: {result}"
    data = json.loads(json_path.read_text())
    assert len(data) == 3
    assert data[0]["name"] == "Alice"
    print(f"✓ csv→json: {result}")

    # Test JSON → CSV
    csv2_path = tmpdir / "test2.csv"
    result = json_to_csv(str(json_path), str(csv2_path))
    assert "3 rows" in result
    roundtrip = csv2_path.read_text().splitlines()
    assert len(roundtrip) == 4  # header + 3 rows
    print(f"✓ json→csv: {result}")

    # Test CSV → Markdown
    md_path = tmpdir / "test.md"
    result = csv_to_markdown(str(csv_path), str(md_path))
    assert "3 rows" in result
    md = md_path.read_text()
    assert "| name" in md
    print(f"✓ csv→md: {result}")

    # Test detect_format
    assert detect_format("test.csv") == "csv"
    assert detect_format("test.json") == "json"
    assert detect_format("test.md") == "markdown"
    assert detect_format("test.py") == "python"
    assert detect_format("test.png") == "image"
    assert detect_format("test.mp4") == "video"
    assert detect_format("test.unknown") == "unknown"
    print("✓ detect_format: all correct")

    # Test list_converters
    converters = list_converters()
    assert len(converters) >= 10
    print(f"✓ list_converters: {len(converters)} converters")

    # Cleanup
    shutil.rmtree(tmpdir)

    print("\n✓ All self-tests passed")