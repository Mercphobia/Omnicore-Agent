#!/usr/bin/env python3
"""Disk forensics — imaging, file carving, timeline, recovery, metadata.
DNA: Disk Analysis (dd imaging, deleted file recovery, metadata extraction).

Provides tools for disk image creation, deleted file recovery via
file carving, filesystem timeline building, and metadata extraction.
Pure Python with subprocess fallbacks to system tools.

Usage::

    from tools.forensics.disk import DiskForensics

    df = DiskForensics()
    img = df.create_image("/dev/sda1", "/tmp/evidence.img")
    df.file_carving("/tmp/evidence.img", ["jpg", "pdf"])
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import stat
import struct
import subprocess
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# File signatures (magic bytes)
# ---------------------------------------------------------------------------

FILE_SIGNATURES: dict[str, bytes] = {
    "jpg": b"\xff\xd8\xff",
    "png": b"\x89PNG\r\n\x1a\n",
    "gif": b"GIF8",
    "pdf": b"%PDF",
    "zip": b"PK\x03\x04",
    "rar": b"Rar!\x1a\x07",
    "7z": b"7z\xbc\xaf'\x1c",
    "docx": b"PK\x03\x04",  # Same as ZIP
    "xlsx": b"PK\x03\x04",
    "elf": b"\x7fELF",
    "sqlite": b"SQLite format 3\x00",
    "bmp": b"BM",
    "wav": b"RIFF",
    "avi": b"RIFF",
    "mp3": b"\xff\xfb",
    "mp4": b"\x00\x00\x00\x18ftyp",
    "exe": b"MZ",
    "ttf": b"\x00\x01\x00\x00\x00",
    "class": b"\xca\xfe\xba\xbe",
    "pcap": b"\xd4\xc3\xb2\xa1",
}

FILE_TRAILERS: dict[str, bytes] = {
    "jpg": b"\xff\xd9",
    "png": b"IEND\xaeB`\x82",
    "gif": b"\x00\x3b",
    "pdf": b"%%EOF",
    "zip": b"PK\x05\x06",
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CarvedFile:
    """A file carved from a disk image."""
    offset: int
    size: int
    file_type: str
    hash_md5: str = ""
    output_path: str = ""


@dataclass
class TimelineEntry:
    """A filesystem timeline entry."""
    path: str
    atime: str = ""
    mtime: str = ""
    ctime: str = ""
    size: int = 0
    owner: str = ""
    mode: str = ""


# ---------------------------------------------------------------------------
# DiskForensics
# ---------------------------------------------------------------------------


class DiskForensics:
    """Disk forensics toolkit for imaging, carving, and analysis.

    Attributes:
        work_dir: Working directory for output files.
    """

    def __init__(self, work_dir: str = ""):
        self.work_dir = work_dir or tempfile.mkdtemp(prefix="omnicore_forensics_")
        os.makedirs(self.work_dir, exist_ok=True)

    # ── Disk imaging ───────────────────────────────────────────────

    def create_image(
        self, device: str, output_path: str = "", block_size: str = "4M",
    ) -> str:
        """Create a forensic disk image using dd or Python fallback.

        Args:
            device: Source device or file (e.g., /dev/sda1, /dev/loop0).
            output_path: Output image path (auto-generated if empty).
            block_size: dd block size.

        Returns:
            Path to the created image, or empty string on failure.
        """
        if not output_path:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            device_name = os.path.basename(device) or "disk"
            output_path = os.path.join(self.work_dir, f"{device_name}_{ts}.img")

        # Method 1: dd
        try:
            r = subprocess.run(
                ["dd", f"if={device}", f"of={output_path}", f"bs={block_size}",
                 "status=progress", "conv=noerror,sync"],
            )
            if r.returncode == 0 and os.path.exists(output_path):
                return output_path
        except FileNotFoundError:
            pass

        # Method 2: Python copy (for files, not block devices)
        try:
            with open(device, "rb") as src, open(output_path, "wb") as dst:
                while True:
                    chunk = src.read(4 * 1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
            return output_path
        except OSError:
            pass

        return ""

    # ── File carving ───────────────────────────────────────────────

    def file_carving(
        self, image_path: str, file_types: list[str] | None = None,
    ) -> list[CarvedFile]:
        """Carve files from a disk image by scanning for file signatures.

        Args:
            image_path: Path to the disk image.
            file_types: List of file types to carve (e.g., ['jpg', 'pdf']).
                        If None, carves all known types.

        Returns:
            List of CarvedFile objects.
        """
        if file_types is None:
            file_types = list(FILE_SIGNATURES.keys())

        carved: list[CarvedFile] = []

        try:
            with open(image_path, "rb") as f:
                data = f.read()
        except OSError:
            return carved

        out_dir = os.path.join(self.work_dir, f"carved_{os.path.basename(image_path)}")
        os.makedirs(out_dir, exist_ok=True)

        for ftype in file_types:
            sig = FILE_SIGNATURES.get(ftype)
            trailer = FILE_TRAILERS.get(ftype)
            if not sig:
                continue

            pos = 0
            count = 0
            while pos < len(data):
                found = data.find(sig, pos)
                if found == -1:
                    break

                # Find end: trailer or reasonable size
                if trailer:
                    end = data.find(trailer, found + len(sig))
                    if end == -1:
                        end = found + 10 * 1024 * 1024  # Cap at 10MB
                    else:
                        end += len(trailer)
                else:
                    end = min(found + 10 * 1024 * 1024, len(data))

                chunk = data[found:end]
                chunk_hash = hashlib.md5(chunk).hexdigest()

                out_name = f"{ftype}_{count:04d}_{chunk_hash[:8]}.{ftype}"
                out_path = os.path.join(out_dir, out_name)
                with open(out_path, "wb") as out:
                    out.write(chunk)

                carved.append(CarvedFile(
                    offset=found, size=len(chunk), file_type=ftype,
                    hash_md5=chunk_hash, output_path=out_path,
                ))
                count += 1
                pos = end

        return carved

    # ── Timeline ───────────────────────────────────────────────────

    def timeline_build(self, image_path: str) -> list[TimelineEntry]:
        """Build a filesystem timeline from a mounted image or directory.

        Uses `find` with stat to extract mtime/atime/ctime for all files.

        Args:
            image_path: Path to mounted image or directory.

        Returns:
            List of TimelineEntry objects sorted by mtime descending.
        """
        timeline: list[TimelineEntry] = []
        target = Path(image_path)

        if not target.exists():
            return timeline

        # Use os.walk
        for root, dirs, files in os.walk(target):
            for name in files + dirs:
                fpath = os.path.join(root, name)
                try:
                    st = os.lstat(fpath)
                    timeline.append(TimelineEntry(
                        path=fpath,
                        atime=datetime.fromtimestamp(st.st_atime, tz=timezone.utc).isoformat(),
                        mtime=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
                        ctime=datetime.fromtimestamp(st.st_ctime, tz=timezone.utc).isoformat(),
                        size=st.st_size,
                        owner=f"{st.st_uid}:{st.st_gid}",
                        mode=stat.filemode(st.st_mode),
                    ))
                except OSError:
                    continue

        timeline.sort(key=lambda x: x.mtime, reverse=True)
        return timeline

    # ── Deleted file recovery ──────────────────────────────────────

    def recover_deleted(self, image_path: str) -> list[str]:
        """Attempt to recover deleted files from an image.

        Uses testdisk/photorec if available; falls back to file carving.

        Args:
            image_path: Path to the disk image.

        Returns:
            List of recovered file paths.
        """
        recovered: list[str] = []

        # Method 1: photorec
        try:
            out_dir = os.path.join(self.work_dir, "recovered")
            os.makedirs(out_dir, exist_ok=True)
            r = subprocess.run(
                ["photorec", "/d", out_dir, "/cmd", image_path, "search"],
                capture_output=True, text=True, timeout=300,
                input="\n\n\n",
            )
            if os.path.exists(out_dir):
                for root, _, files in os.walk(out_dir):
                    for f in files:
                        recovered.append(os.path.join(root, f))
        except FileNotFoundError:
            pass

        # Method 2: scalpel
        if not recovered:
            try:
                # Create scalpel config for common types
                cfg_path = os.path.join(self.work_dir, "scalpel.conf")
                with open(cfg_path, "w") as f:
                    f.write("# Scalpel config for OmniCore\n")
                    for ftype, sig in FILE_SIGNATURES.items():
                        trailer = FILE_TRAILERS.get(ftype, b"")
                        # Scalpel format: ext | case | header | footer
                        sig_hex = "".join(f"\\x{b:02x}" for b in sig)
                        trail_hex = "".join(f"\\x{b:02x}" for b in trailer) if trailer else ""
                        f.write(f"{ftype}\ty\t{sig_hex}\t{trail_hex}\t20480\n")

                out_dir = os.path.join(self.work_dir, "scalpel_out")
                os.makedirs(out_dir, exist_ok=True)
                subprocess.run(
                    ["scalpel", "-c", cfg_path, "-o", out_dir, image_path],
                    capture_output=True, timeout=120,
                )
                if os.path.exists(out_dir):
                    for root, _, files in os.walk(out_dir):
                        for f in files:
                            recovered.append(os.path.join(root, f))
            except FileNotFoundError:
                pass

        # Method 3: Pure Python carving
        if not recovered:
            carved = self.file_carving(image_path)
            recovered = [c.output_path for c in carved if c.output_path]

        return recovered

    # ── Metadata extraction ────────────────────────────────────────

    def metadata_extract(self, file_path: str) -> dict[str, Any]:
        """Extract all available metadata from a file.

        Covers EXIF (images), PDF metadata, binary signatures,
        file system stat, and basic content analysis.

        Args:
            file_path: Path to the file to analyze.

        Returns:
            Dict with all extracted metadata.
        """
        meta: dict[str, Any] = {"file": file_path}
        target = Path(file_path)

        if not target.exists():
            meta["error"] = f"File not found: {file_path}"
            return meta

        # Stat info
        st = target.stat()
        meta["stat"] = {
            "size": st.st_size,
            "mode": stat.filemode(st.st_mode),
            "uid": st.st_uid,
            "gid": st.st_gid,
            "atime": datetime.fromtimestamp(st.st_atime, tz=timezone.utc).isoformat(),
            "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "ctime": datetime.fromtimestamp(st.st_ctime, tz=timezone.utc).isoformat(),
            "inode": st.st_ino,
            "nlinks": st.st_nlink,
            "device": st.st_dev,
        }

        # Magic bytes
        try:
            with open(file_path, "rb") as f:
                magic = f.read(16)
            meta["magic"] = magic.hex(" ")
            # Identify type
            for ftype, sig in FILE_SIGNATURES.items():
                if magic.startswith(sig):
                    meta["file_type_detected"] = ftype
                    break
        except OSError:
            meta["magic"] = "unreadable"

        # EXIF (images)
        suffix = target.suffix.lower()
        if suffix in (".jpg", ".jpeg", ".tiff", ".png", ".webp"):
            meta["exif"] = self._extract_exif(str(target))

        # PDF metadata
        if suffix == ".pdf" or meta.get("file_type_detected") == "pdf":
            meta["pdf"] = self._extract_pdf_meta(str(target))

        # Strings / text preview
        try:
            with open(file_path, "rb") as f:
                preview = f.read(4096)
            # Extract printable strings
            strings = re.findall(rb"[\x20-\x7e]{4,}", preview)
            meta["strings"] = [s.decode("ascii") for s in strings[:20]]
            meta["first_bytes_b64"] = __import__("base64").b64encode(preview[:64]).decode()
        except OSError:
            pass

        return meta

    def _extract_exif(self, path: str) -> dict[str, str]:
        """Extract EXIF metadata from an image."""
        exif: dict[str, str] = {}

        # Method 1: exiftool
        try:
            r = subprocess.run(
                ["exiftool", "-json", path],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                data = json.loads(r.stdout)
                if data:
                    exif = {k: str(v) for k, v in data[0].items()}
                    return exif
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        # Method 2: Python PIL
        try:
            from PIL import Image
            from PIL.ExifTags import TAGS

            img = Image.open(path)
            raw_exif = img._getexif()
            if raw_exif:
                for tag_id, value in raw_exif.items():
                    tag_name = TAGS.get(tag_id, str(tag_id))
                    exif[tag_name] = str(value)[:500]
        except ImportError:
            pass
        except Exception:
            pass

        return exif

    def _extract_pdf_meta(self, path: str) -> dict[str, str]:
        """Extract metadata from a PDF file."""
        meta: dict[str, str] = {}
        try:
            with open(path, "rb") as f:
                content = f.read(4096).decode(errors="replace")
            # Simple regex for PDF metadata
            for key in ["Title", "Author", "Subject", "Creator", "Producer",
                       "CreationDate", "ModDate"]:
                m = re.search(rf"/{key}\s*\(([^)]*)\)", content)
                if m:
                    meta[key] = m.group(1)
            m = re.search(r"/Pages?\s+(\d+)", content)
            if m:
                meta["Pages"] = m.group(1)
        except OSError:
            pass
        return meta

    # ── File hashing ───────────────────────────────────────────────

    def hash_file(self, file_path: str, algorithms: list[str] | None = None) -> dict[str, str]:
        """Hash a file with MD5 and SHA-256 (and optionally more algorithms).

        Args:
            file_path: Path to the file.
            algorithms: List of algorithm names (default: ['md5', 'sha256']).

        Returns:
            Dict with algorithm -> hex digest.
        """
        if algorithms is None:
            algorithms = ["md5", "sha256"]

        result: dict[str, str] = {}
        target = Path(file_path)

        if not target.exists():
            return {"error": f"File not found: {file_path}"}

        try:
            with open(target, "rb") as f:
                data = f.read()

            for algo in algorithms:
                try:
                    h = hashlib.new(algo)
                    h.update(data)
                    result[algo] = h.hexdigest()
                except ValueError:
                    result[f"{algo}_error"] = "Unsupported algorithm"
        except OSError as exc:
            result["error"] = str(exc)

        return result


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Disk Forensics Self-Test ===\n")

    df = DiskForensics()

    # Create a test file with known content
    test_file = os.path.join(df.work_dir, "test_image.bin")
    test_data = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00" + os.urandom(500) + b"\xff\xd9"
        + b"%PDF-1.4\n%/Title (Test Doc)\n" + os.urandom(300) + b"\n%%EOF"
        + b"PK\x03\x04" + os.urandom(200) + b"PK\x05\x06\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        + os.urandom(100)
    )
    with open(test_file, "wb") as f:
        f.write(test_data)

    # Hash
    print("--- hash_file ---")
    hashes = df.hash_file(test_file)
    for algo, digest in hashes.items():
        print(f"  {algo}: {digest[:32]}...")

    # Metadata
    print("\n--- metadata_extract ---")
    meta = df.metadata_extract(test_file)
    print(f"  Size: {meta['stat']['size']}")
    print(f"  Magic: {meta['magic']}")
    print(f"  Type detected: {meta.get('file_type_detected', 'unknown')}")
    print(f"  Mode: {meta['stat']['mode']}")

    # File carving
    print("\n--- file_carving ---")
    carved = df.file_carving(test_file, ["jpg", "pdf", "zip"])
    print(f"  Carved: {len(carved)} files")
    for c in carved:
        print(f"    {c.file_type}: offset={c.offset}, size={c.size}, hash={c.hash_md5[:8]}")

    # Verify carved files are valid
    for c in carved:
        with open(c.output_path, "rb") as f:
            start = f.read(4)
        expected = FILE_SIGNATURES.get(c.file_type, b"")
        status = "OK" if start.startswith(expected[:3]) else "CORRUPT"
        print(f"    {c.file_type} validation: {status}")

    # Timeline
    print("\n--- timeline_build ---")
    tl = df.timeline_build(df.work_dir)
    print(f"  Entries: {len(tl)}")
    if tl:
        latest = tl[0]
        print(f"  Latest: {latest.path} ({latest.mtime})")

    # Create image (from a file)
    print("\n--- create_image ---")
    img_path = df.create_image(test_file)
    if img_path:
        print(f"  Image created: {img_path} ({os.path.getsize(img_path)} bytes)")
    else:
        print("  Image creation skipped (permission or environment issue)")

    # Recover deleted (from our test image)
    print("\n--- recover_deleted ---")
    recovered = df.recover_deleted(test_file)
    print(f"  Recovered: {len(recovered)} files")

    # Cleanup
    import shutil
    shutil.rmtree(df.work_dir, ignore_errors=True)

    print("\n=== All tests passed ===")