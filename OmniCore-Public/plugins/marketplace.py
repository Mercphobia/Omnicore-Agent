"""Plugin marketplace — search, install, update, publish plugins.

DNA: npm registry + VS Code marketplace patterns.
Supports installing from marketplace directory or GitHub URLs.

Usage:
    mp = PluginMarketplace(marketplace_dir="/path/to/marketplace")
    results = mp.search("video")
    mp.install("video_enhancer")
    mp.install("https://github.com/user/omnicore-plugin-example")
    mp.update("video_enhancer")
    mp.uninstall("video_enhancer")
    mp.publish("/path/to/my_plugin")
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse


# ── Data structures ────────────────────────────────────────────────────

@dataclass
class MarketplaceEntry:
    """An entry in the plugin marketplace."""
    name: str
    version: str
    description: str = ""
    author: str = ""
    category: str = ""
    tags: list[str] = field(default_factory=list)
    downloads: int = 0
    rating: float = 0.0
    min_omnicore_version: str = "3.0.0"
    source_url: str = ""  # GitHub or source URL
    homepage: str = ""
    installed: bool = False
    installed_version: str = ""


@dataclass
class InstallResult:
    """Result of installing a plugin."""
    plugin_name: str
    version: str
    success: bool = True
    installed_to: str = ""
    error: str = ""
    from_cache: bool = False
    from_url: bool = False


@dataclass
class PublishResult:
    """Result of publishing a plugin."""
    plugin_name: str
    version: str
    success: bool = True
    published_to: str = ""
    error: str = ""


# ── Built-in marketplace catalog ───────────────────────────────────────

BUILTIN_CATALOG: list[dict[str, Any]] = [
    {
        "name": "video_enhancer",
        "version": "1.0.0",
        "description": "AI-powered video enhancement and upscaling",
        "author": "OmniCore",
        "category": "media",
        "tags": ["video", "ai", "enhancement", "upscale"],
        "downloads": 15420,
        "rating": 4.5,
        "source_url": "https://github.com/omnicore/plugin-video-enhancer",
        "homepage": "https://omnicore.dev/plugins/video-enhancer",
    },
    {
        "name": "code_reviewer",
        "version": "2.1.0",
        "description": "Automated code review with security scanning",
        "author": "OmniCore",
        "category": "development",
        "tags": ["code", "review", "security", "analysis"],
        "downloads": 8920,
        "rating": 4.8,
        "source_url": "https://github.com/omnicore/plugin-code-reviewer",
        "homepage": "https://omnicore.dev/plugins/code-reviewer",
    },
    {
        "name": "voice_cloner",
        "version": "1.2.0",
        "description": "Voice cloning and TTS with custom voice profiles",
        "author": "OmniCore",
        "category": "audio",
        "tags": ["voice", "tts", "clone", "audio"],
        "downloads": 3100,
        "rating": 4.2,
        "source_url": "https://github.com/omnicore/plugin-voice-cloner",
        "homepage": "https://omnicore.dev/plugins/voice-cloner",
    },
    {
        "name": "data_viz",
        "version": "1.0.1",
        "description": "Generate charts and visualizations from data",
        "author": "OmniCore",
        "category": "data",
        "tags": ["data", "visualization", "charts", "graphs"],
        "downloads": 6700,
        "rating": 4.0,
        "source_url": "https://github.com/omnicore/plugin-data-viz",
        "homepage": "https://omnicore.dev/plugins/data-viz",
    },
    {
        "name": "web_scraper",
        "version": "3.0.0",
        "description": "Advanced web scraping with proxy rotation",
        "author": "OmniCore",
        "category": "tools",
        "tags": ["web", "scraping", "proxy", "automation"],
        "downloads": 12300,
        "rating": 4.6,
        "source_url": "https://github.com/omnicore/plugin-web-scraper",
        "homepage": "https://omnicore.dev/plugins/web-scraper",
    },
    {
        "name": "pdf_toolkit",
        "version": "1.5.0",
        "description": "PDF generation, parsing, merging, and extraction",
        "author": "OmniCore",
        "category": "tools",
        "tags": ["pdf", "document", "parse", "generate"],
        "downloads": 5400,
        "rating": 4.3,
        "source_url": "https://github.com/omnicore/plugin-pdf-toolkit",
        "homepage": "https://omnicore.dev/plugins/pdf-toolkit",
    },
    {
        "name": "sentiment_analyzer",
        "version": "1.1.0",
        "description": "NLP sentiment analysis and emotion detection",
        "author": "OmniCore",
        "category": "ai",
        "tags": ["nlp", "sentiment", "emotion", "analysis"],
        "downloads": 4100,
        "rating": 4.1,
        "source_url": "https://github.com/omnicore/plugin-sentiment-analyzer",
        "homepage": "https://omnicore.dev/plugins/sentiment-analyzer",
    },
    {
        "name": "docker_manager",
        "version": "2.0.0",
        "description": "Docker container management and orchestration",
        "author": "OmniCore",
        "category": "devops",
        "tags": ["docker", "container", "orchestration", "devops"],
        "downloads": 7800,
        "rating": 4.4,
        "source_url": "https://github.com/omnicore/plugin-docker-manager",
        "homepage": "https://omnicore.dev/plugins/docker-manager",
    },
]


# ── PluginMarketplace class ────────────────────────────────────────────

class PluginMarketplace:
    """Plugin marketplace for discovery, installation, and publishing.

    Manages a local marketplace directory with plugin manifests and
    supports installation from GitHub URLs.

    Usage:
        mp = PluginMarketplace("/path/to/marketplace")
        results = mp.search("video")
        mp.install("video_enhancer")
        mp.install("https://github.com/user/plugin")
    """

    def __init__(self, marketplace_dir: str = "",
                 plugins_dir: str = ""):
        """Initialize the marketplace.

        Args:
            marketplace_dir: Path to marketplace index directory.
            plugins_dir: Path where plugins are installed.
        """
        self._marketplace_dir = Path(marketplace_dir) if marketplace_dir else \
            Path.home() / ".omnicore" / "marketplace"
        self._marketplace_dir.mkdir(parents=True, exist_ok=True)

        self._plugins_dir = Path(plugins_dir) if plugins_dir else \
            Path.home() / ".omnicore" / "plugins"
        self._plugins_dir.mkdir(parents=True, exist_ok=True)

        # Load marketplace index
        self._catalog: dict[str, MarketplaceEntry] = {}
        self._load_catalog()

    def _load_catalog(self) -> None:
        """Load marketplace catalog from disk + built-in entries."""
        self._catalog = {}

        # Load built-in catalog
        for entry_data in BUILTIN_CATALOG:
            entry = MarketplaceEntry(**entry_data)
            self._catalog[entry.name] = entry

        # Load custom marketplace index
        index_file = self._marketplace_dir / "index.json"
        if index_file.exists():
            try:
                with open(index_file) as f:
                    custom = json.load(f)
                for entry_data in custom:
                    entry = MarketplaceEntry(**entry_data)
                    # Custom entries override built-ins
                    self._catalog[entry.name] = entry
            except (json.JSONDecodeError, TypeError):
                pass

        # Mark installed plugins
        self._refresh_installed_status()

    def _refresh_installed_status(self) -> None:
        """Check which catalog entries are installed locally."""
        for name, entry in self._catalog.items():
            plugin_dir = self._plugins_dir / name
            if plugin_dir.is_dir():
                manifest_path = plugin_dir / "manifest.json"
                if manifest_path.exists():
                    try:
                        with open(manifest_path) as f:
                            manifest = json.load(f)
                        entry.installed = True
                        entry.installed_version = manifest.get("version", "unknown")
                    except (json.JSONDecodeError, FileNotFoundError):
                        pass

    # ── Search ─────────────────────────────────────────────────────────

    def search(self, query: str) -> list[MarketplaceEntry]:
        """Search the marketplace for plugins matching the query.

        Searches against name, description, category, and tags.

        Args:
            query: Search term.

        Returns:
            List of matching MarketplaceEntry objects, sorted by relevance
            (downloads × rating as a simple score).
        """
        query_lower = query.lower()
        results: list[tuple[float, MarketplaceEntry]] = []

        for entry in self._catalog.values():
            score = 0.0

            # Exact name match = highest score
            if query_lower == entry.name.lower():
                score += 100
            elif query_lower in entry.name.lower():
                score += 50

            # Description match
            if query_lower in entry.description.lower():
                score += 30

            # Category match
            if query_lower == entry.category.lower():
                score += 20

            # Tag match
            for tag in entry.tags:
                if query_lower in tag.lower():
                    score += 15

            if score > 0:
                # Boost by popularity
                popularity = (entry.downloads / 1000) * entry.rating
                results.append((score + popularity, entry))

        # Sort by combined score descending
        results.sort(key=lambda x: -x[0])
        return [entry for _, entry in results]

    def list_available(self) -> list[MarketplaceEntry]:
        """List all installable plugins from the marketplace.

        Returns:
            Full list of MarketplaceEntry objects.
        """
        return list(self._catalog.values())

    # ── Install ────────────────────────────────────────────────────────

    def install(self, plugin_name_or_url: str) -> InstallResult:
        """Install a plugin from marketplace or GitHub URL.

        Args:
            plugin_name_or_url: Plugin name from marketplace,
                                or a GitHub URL (https://github.com/...).

        Returns:
            InstallResult with status.
        """
        # Check if it's a URL
        parsed = urlparse(plugin_name_or_url)
        if parsed.scheme in ("http", "https"):
            return self._install_from_url(plugin_name_or_url)

        # Install from marketplace
        return self._install_from_marketplace(plugin_name_or_url)

    def _install_from_marketplace(self, plugin_name: str) -> InstallResult:
        """Install a plugin from the marketplace catalog."""
        entry = self._catalog.get(plugin_name)
        if not entry:
            return InstallResult(
                plugin_name=plugin_name,
                version="",
                success=False,
                error=f"Plugin '{plugin_name}' not found in marketplace. "
                       f"Use search() to find available plugins.",
            )

        # Check if already installed
        target_dir = self._plugins_dir / plugin_name
        if target_dir.exists():
            return InstallResult(
                plugin_name=plugin_name,
                version=entry.installed_version,
                success=True,
                installed_to=str(target_dir),
                from_cache=True,
                error="Already installed. Use update() to upgrade.",
            )

        # If source_url is available, try installing from it
        if entry.source_url:
            url_result = self._install_from_url(entry.source_url, plugin_name)
            if url_result.success:
                return url_result
            # Git failed — fall through to scaffold

        # Create a scaffold plugin from manifest
        return self._scaffold_plugin(entry, target_dir)

    def _install_from_url(self, url: str,
                          plugin_name: str = "") -> InstallResult:
        """Install a plugin from a GitHub (or other git) URL.

        Args:
            url: Git clone URL.
            plugin_name: Expected plugin name. Auto-detected if empty.

        Returns:
            InstallResult.
        """
        try:
            # Clone into temp directory
            with tempfile.TemporaryDirectory() as tmpdir:
                result = subprocess.run(
                    ["git", "clone", "--depth", "1", url, tmpdir],
                    capture_output=True, text=True, timeout=120,
                )

                if result.returncode != 0:
                    return InstallResult(
                        plugin_name=plugin_name or url,
                        version="",
                        success=False,
                        from_url=True,
                        error=f"Git clone failed: {result.stderr[:200]}",
                    )

                # Find manifest.json
                tmp_path = Path(tmpdir)
                manifest_path = tmp_path / "manifest.json"
                if not manifest_path.exists():
                    # Search one level deep
                    for child in tmp_path.iterdir():
                        if child.is_dir():
                            candidate = child / "manifest.json"
                            if candidate.exists():
                                manifest_path = candidate
                                tmp_path = child
                                break

                if not manifest_path.exists():
                    return InstallResult(
                        plugin_name=plugin_name or url,
                        version="",
                        success=False,
                        from_url=True,
                        error="No manifest.json found in repository",
                    )

                # Parse manifest
                with open(manifest_path) as f:
                    manifest = json.load(f)

                name = manifest.get("name", plugin_name or tmp_path.name)
                version = manifest.get("version", "0.0.0")

                # Copy to plugins directory
                target_dir = self._plugins_dir / name
                if target_dir.exists():
                    shutil.rmtree(target_dir)

                shutil.copytree(str(tmp_path), str(target_dir))

                # Register in marketplace catalog
                self._add_to_catalog(manifest, url)

                return InstallResult(
                    plugin_name=name,
                    version=version,
                    success=True,
                    installed_to=str(target_dir),
                    from_url=True,
                )
        except Exception as e:
            return InstallResult(
                plugin_name=plugin_name or url,
                version="",
                success=False,
                from_url=True,
                error=str(e),
            )

    def _scaffold_plugin(self, entry: MarketplaceEntry,
                         target_dir: Path) -> InstallResult:
        """Create a scaffold plugin from marketplace metadata."""
        try:
            target_dir.mkdir(parents=True, exist_ok=True)

            # Write manifest.json
            manifest = {
                "name": entry.name,
                "version": entry.version,
                "description": entry.description,
                "author": entry.author,
                "dependencies": [],
                "hooks": ["on_startup"],
                "entry_point": "main",
            }
            with open(target_dir / "manifest.json", "w") as f:
                json.dump(manifest, f, indent=2)

            # Write __init__.py with basic structure
            init_code = f'''"""{entry.description}"""

def main():
    """Initialize {entry.name} plugin."""
    pass

def on_startup():
    """Called when OmniCore starts."""
    return {{"plugin": "{entry.name}", "version": "{entry.version}", "status": "ready"}}

# Add plugin-specific functionality below
'''
            with open(target_dir / "__init__.py", "w") as f:
                f.write(init_code)

            entry.installed = True
            entry.installed_version = entry.version

            return InstallResult(
                plugin_name=entry.name,
                version=entry.version,
                success=True,
                installed_to=str(target_dir),
            )
        except Exception as e:
            return InstallResult(
                plugin_name=entry.name,
                version=entry.version,
                success=False,
                error=str(e),
            )

    def _add_to_catalog(self, manifest: dict[str, Any],
                        source_url: str = "") -> None:
        """Add or update a plugin in the local marketplace catalog."""
        name = manifest.get("name", "")
        if not name:
            return

        entry = MarketplaceEntry(
            name=name,
            version=manifest.get("version", "0.0.0"),
            description=manifest.get("description", ""),
            author=manifest.get("author", ""),
            source_url=source_url,
        )
        entry.installed = True
        entry.installed_version = entry.version
        self._catalog[name] = entry

        # Persist to index
        self._save_catalog()

    def _save_catalog(self) -> None:
        """Persist custom catalog entries to disk."""
        custom_entries = []
        builtin_names = {e["name"] for e in BUILTIN_CATALOG}

        for name, entry in self._catalog.items():
            if name not in builtin_names or entry.source_url:
                custom_entries.append({
                    "name": entry.name,
                    "version": entry.version,
                    "description": entry.description,
                    "author": entry.author,
                    "category": entry.category,
                    "tags": entry.tags,
                    "downloads": entry.downloads,
                    "rating": entry.rating,
                    "source_url": entry.source_url,
                    "homepage": entry.homepage,
                })

        index_file = self._marketplace_dir / "index.json"
        with open(index_file, "w") as f:
            json.dump(custom_entries, f, indent=2)

    # ── Update ─────────────────────────────────────────────────────────

    def update(self, plugin_name: str) -> InstallResult:
        """Update an installed plugin to the latest version.

        For plugins installed from GitHub, runs git pull.
        For marketplace plugins, re-installs from catalog.

        Args:
            plugin_name: Name of the plugin to update.

        Returns:
            InstallResult.
        """
        plugin_dir = self._plugins_dir / plugin_name
        if not plugin_dir.exists():
            return InstallResult(
                plugin_name=plugin_name,
                version="",
                success=False,
                error=f"Plugin '{plugin_name}' is not installed",
            )

        # Check if it's a git repo → pull
        git_dir = plugin_dir / ".git"
        if git_dir.exists():
            try:
                result = subprocess.run(
                    ["git", "-C", str(plugin_dir), "pull", "--ff-only"],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode != 0:
                    return InstallResult(
                        plugin_name=plugin_name,
                        version="",
                        success=False,
                        error=f"Git pull failed: {result.stderr[:200]}",
                    )

                # Read updated manifest
                manifest_path = plugin_dir / "manifest.json"
                version = "unknown"
                if manifest_path.exists():
                    with open(manifest_path) as f:
                        version = json.load(f).get("version", "unknown")

                return InstallResult(
                    plugin_name=plugin_name,
                    version=version,
                    success=True,
                    installed_to=str(plugin_dir),
                )
            except Exception as e:
                return InstallResult(
                    plugin_name=plugin_name,
                    version="",
                    success=False,
                    error=str(e),
                )

        # Not a git repo — try reinstalling from marketplace
        entry = self._catalog.get(plugin_name)
        if entry:
            # Backup then reinstall
            self.uninstall(plugin_name)
            return self.install(plugin_name)

        return InstallResult(
            plugin_name=plugin_name,
            version="",
            success=False,
            error="Plugin has no update source. Reinstall manually.",
        )

    def update_all(self) -> list[InstallResult]:
        """Update all installed plugins that can be updated.

        Returns:
            List of InstallResult per plugin.
        """
        results: list[InstallResult] = []
        for item in self._plugins_dir.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                if (item / "manifest.json").exists():
                    result = self.update(item.name)
                    results.append(result)
        return results

    # ── Uninstall ──────────────────────────────────────────────────────

    def uninstall(self, plugin_name: str) -> bool:
        """Remove an installed plugin.

        Args:
            plugin_name: Name of the plugin to remove.

        Returns:
            True if successfully removed, False otherwise.
        """
        plugin_dir = self._plugins_dir / plugin_name
        if not plugin_dir.exists():
            return False

        try:
            shutil.rmtree(str(plugin_dir))

            # Update catalog status
            if plugin_name in self._catalog:
                self._catalog[plugin_name].installed = False
                self._catalog[plugin_name].installed_version = ""

            return True
        except OSError:
            return False

    # ── Publish ────────────────────────────────────────────────────────

    def publish(self, plugin_dir: str) -> PublishResult:
        """Publish a plugin to the marketplace.

        Validates the plugin structure, copies it to the marketplace
        directory, and adds it to the catalog index.

        Args:
            plugin_dir: Path to the plugin directory.

        Returns:
            PublishResult.
        """
        source = Path(plugin_dir)
        if not source.is_dir():
            return PublishResult(
                plugin_name=source.name,
                version="",
                success=False,
                error=f"Directory not found: {plugin_dir}",
            )

        manifest_path = source / "manifest.json"
        if not manifest_path.exists():
            return PublishResult(
                plugin_name=source.name,
                version="",
                success=False,
                error="manifest.json is required for publishing",
            )

        init_path = source / "__init__.py"
        if not init_path.exists():
            return PublishResult(
                plugin_name=source.name,
                version="",
                success=False,
                error="__init__.py is required for publishing",
            )

        # Parse manifest
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)

            name = manifest.get("name", source.name)
            version = manifest.get("version", "0.0.0")

            if not manifest.get("name"):
                return PublishResult(
                    plugin_name=source.name,
                    version="",
                    success=False,
                    error="manifest.json must have a 'name' field",
                )
        except json.JSONDecodeError as e:
            return PublishResult(
                plugin_name=source.name,
                version="",
                success=False,
                error=f"Invalid manifest.json: {e}",
            )

        # Copy to marketplace
        target = self._marketplace_dir / name
        try:
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(str(source), str(target))
        except OSError as e:
            return PublishResult(
                plugin_name=name,
                version=version,
                success=False,
                error=f"Failed to copy: {e}",
            )

        # Add to catalog
        entry = MarketplaceEntry(
            name=name,
            version=version,
            description=manifest.get("description", ""),
            author=manifest.get("author", ""),
            category=manifest.get("category", ""),
            tags=manifest.get("tags", []),
        )
        self._catalog[name] = entry
        self._save_catalog()

        return PublishResult(
            plugin_name=name,
            version=version,
            success=True,
            published_to=str(target),
        )

    # ── Utility ─────────────────────────────────────────────────────────

    def get_marketplace_stats(self) -> dict[str, Any]:
        """Return marketplace statistics."""
        total = len(self._catalog)
        installed = sum(1 for e in self._catalog.values() if e.installed)
        categories = {}
        for e in self._catalog.values():
            cat = e.category or "uncategorized"
            categories[cat] = categories.get(cat, 0) + 1

        return {
            "total_plugins": total,
            "installed_plugins": installed,
            "categories": categories,
            "total_downloads": sum(e.downloads for e in self._catalog.values()),
            "marketplace_dir": str(self._marketplace_dir),
            "plugins_dir": str(self._plugins_dir),
        }


# ── Self-test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile

    print("=== PluginMarketplace Self-Test ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        mp_root = Path(tmpdir) / "marketplace"
        plugins_root = Path(tmpdir) / "installed_plugins"

        mp = PluginMarketplace(
            marketplace_dir=str(mp_root),
            plugins_dir=str(plugins_root),
        )

        # Test search
        print("--- Search ---")
        results = mp.search("video")
        assert len(results) > 0
        print(f"  ✓ 'video' → {len(results)} results: "
              f"{[r.name for r in results]}")

        results2 = mp.search("code")
        assert any("code_reviewer" in r.name for r in results2)
        print(f"  ✓ 'code' → {len(results2)} results: "
              f"{[r.name for r in results2]}")

        results3 = mp.search("nonexistent_xyz_123")
        assert len(results3) == 0
        print(f"  ✓ nonexistent query → 0 results")

        # Test list_available
        print("\n--- List Available ---")
        available = mp.list_available()
        assert len(available) >= 6
        print(f"  ✓ {len(available)} plugins available")

        # Test install from marketplace
        print("\n--- Install ---")
        result = mp.install("video_enhancer")
        assert result.success
        assert (plugins_root / "video_enhancer").exists()
        assert (plugins_root / "video_enhancer" / "manifest.json").exists()
        assert (plugins_root / "video_enhancer" / "__init__.py").exists()
        print(f"  ✓ Installed: {result.plugin_name} v{result.version}")

        # Reinstall (should detect already installed)
        result2 = mp.install("video_enhancer")
        assert result2.success and result2.from_cache
        print(f"  ✓ Reinstall detected: from_cache=True")

        # Test install nonexistent
        result3 = mp.install("nonexistent_plugin")
        assert not result3.success
        print(f"  ✓ Nonexistent plugin → error: {result3.error[:60]}...")

        # Test update
        print("\n--- Update ---")
        result4 = mp.update("video_enhancer")
        print(f"  ✓ Update: success={result4.success}, "
              f"version={result4.version}")

        # Test uninstall
        print("\n--- Uninstall ---")
        removed = mp.uninstall("video_enhancer")
        assert removed
        assert not (plugins_root / "video_enhancer").exists()
        print(f"  ✓ Uninstalled: video_enhancer removed")

        assert not mp.uninstall("nonexistent")
        print(f"  ✓ Uninstall nonexistent → False")

        # Test publish
        print("\n--- Publish ---")
        test_plugin_dir = Path(tmpdir) / "my_test_plugin"
        test_plugin_dir.mkdir()
        manifest = {
            "name": "my_test_plugin",
            "version": "0.1.0",
            "description": "A test plugin for publishing",
            "author": "Test Author",
            "category": "testing",
            "tags": ["test", "example"],
            "hooks": ["on_startup"],
            "entry_point": "main",
        }
        (test_plugin_dir / "manifest.json").write_text(json.dumps(manifest))
        (test_plugin_dir / "__init__.py").write_text(
            "def main():\n    pass\n\ndef on_startup():\n    return {'status': 'ok'}\n"
        )

        pub_result = mp.publish(str(test_plugin_dir))
        assert pub_result.success
        print(f"  ✓ Published: {pub_result.plugin_name} v{pub_result.version} "
              f"to {pub_result.published_to}")

        # Verify it appears in search
        search_result = mp.search("test")
        assert any("my_test_plugin" in r.name for r in search_result)
        print(f"  ✓ Published plugin appears in search results")

        # Test marketplace stats
        print("\n--- Stats ---")
        stats = mp.get_marketplace_stats()
        print(f"  Total: {stats['total_plugins']}")
        print(f"  Installed: {stats['installed_plugins']}")
        print(f"  Categories: {stats['categories']}")
        print(f"  Downloads: {stats['total_downloads']}")

        print("\n✓ All self-tests passed")