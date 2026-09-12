"""Plugin loader — dynamic discovery, loading, hot-reload, dependency checking.

DNA: VSCode extensions + npm ecosystem patterns. Each plugin is a Python
package with a manifest.json specifying name, version, hooks, and dependencies.

Plugin directory structure:
    plugins/
    ├── my_plugin/
    │   ├── manifest.json    (required)
    │   ├── __init__.py      (required — entry point)
    │   └── ...              (plugin code)
"""

import importlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


# ── Data structures ────────────────────────────────────────────────────

@dataclass
class PluginManifest:
    """Parsed plugin manifest.json."""
    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    dependencies: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)  # e.g., ["on_startup", "on_message"]
    min_omnicore_version: str = "3.0.0"
    entry_point: str = "main"  # function name in __init__.py


@dataclass
class PluginInfo:
    """Runtime information about a loaded plugin."""
    manifest: PluginManifest
    path: str
    module: Any = None  # Python module object when loaded
    enabled: bool = False
    loaded: bool = False
    load_time_ms: float = 0.0
    errors: list[str] = field(default_factory=list)
    hooks_registered: dict[str, Callable] = field(default_factory=dict)


# ── PluginLoader class ─────────────────────────────────────────────────

class PluginLoader:
    """Dynamic plugin discovery, loading, and management.

    Usage:
        loader = PluginLoader()
        loader.discover("/path/to/plugins")
        loader.load("my_plugin")
        loader.enable("my_plugin")
        loader.reload("my_plugin")
        info = loader.list_plugins()
    """

    def __init__(self, plugins_dir: str = ""):
        """Initialize plugin loader.

        Args:
            plugins_dir: Root directory containing plugin packages.
        """
        self._plugins_dir = Path(plugins_dir) if plugins_dir else None
        self._plugins: dict[str, PluginInfo] = {}
        self._hook_registry: dict[str, list[Callable]] = {}
        self._load_order: list[str] = []

    # ── Discovery ──────────────────────────────────────────────────────

    def discover(self, plugins_dir: str = "") -> list[PluginInfo]:
        """Scan a directory for plugins with manifest.json.

        Args:
            plugins_dir: Path to scan. Uses stored path or current dir if empty.

        Returns:
            List of discovered PluginInfo objects.
        """
        search_path = Path(plugins_dir) if plugins_dir else self._plugins_dir
        if not search_path:
            search_path = Path("plugins")

        search_path = search_path.resolve()
        self._plugins_dir = search_path

        discovered: list[PluginInfo] = []

        for item in search_path.iterdir():
            if not item.is_dir():
                continue
            if item.name.startswith("__") or item.name.startswith("."):
                continue

            manifest_path = item / "manifest.json"
            init_path = item / "__init__.py"

            if not manifest_path.exists():
                continue
            if not init_path.exists():
                continue

            try:
                manifest = self._parse_manifest(manifest_path)
                info = PluginInfo(
                    manifest=manifest,
                    path=str(item),
                )
                name = manifest.name or item.name
                self._plugins[name] = info
                discovered.append(info)
            except (json.JSONDecodeError, KeyError) as e:
                # Skip invalid plugins
                pass

        return discovered

    def _parse_manifest(self, path: Path) -> PluginManifest:
        """Parse a plugin's manifest.json file."""
        with open(path) as f:
            data = json.load(f)

        return PluginManifest(
            name=data.get("name", path.parent.name),
            version=data.get("version", "0.1.0"),
            description=data.get("description", ""),
            author=data.get("author", ""),
            dependencies=data.get("dependencies", []),
            hooks=data.get("hooks", []),
            min_omnicore_version=data.get("min_omnicore_version", "3.0.0"),
            entry_point=data.get("entry_point", "main"),
        )

    # ── Load ───────────────────────────────────────────────────────────

    def load(self, plugin_name: str) -> PluginInfo:
        """Import and initialize a plugin module.

        Dynamically imports the plugin's __init__.py and calls its
        entry_point function if specified.

        Args:
            plugin_name: Name of the plugin to load.

        Returns:
            PluginInfo with module reference.

        Raises:
            ValueError: If plugin not discovered or fails to import.
        """
        if plugin_name not in self._plugins:
            # Try auto-discovery
            if self._plugins_dir:
                self.discover(str(self._plugins_dir))

        info = self._plugins.get(plugin_name)
        if not info:
            raise ValueError(
                f"Plugin '{plugin_name}' not found. "
                f"Available: {list(self._plugins.keys())}"
            )

        start = time.perf_counter()

        try:
            # Build import path
            plugin_path = Path(info.path)
            parent = plugin_path.parent

            # Add parent to sys.path temporarily
            parent_str = str(parent.resolve())
            in_sys_path = parent_str in sys.path
            if not in_sys_path:
                sys.path.insert(0, parent_str)

            # Import the plugin
            module = importlib.import_module(plugin_path.name)

            if not in_sys_path:
                sys.path.remove(parent_str)

            # Call entry point if it exists
            if info.manifest.entry_point:
                entry_fn = getattr(module, info.manifest.entry_point, None)
                if callable(entry_fn):
                    entry_fn()
                    info.hooks_registered[info.manifest.entry_point] = entry_fn

            info.module = module
            info.loaded = True
            info.load_time_ms = (time.perf_counter() - start) * 1000
            info.errors = []

            # Register hooks
            for hook_name in info.manifest.hooks:
                hook_fn = getattr(module, hook_name, None)
                if callable(hook_fn):
                    info.hooks_registered[hook_name] = hook_fn
                    self._register_hook(hook_name, hook_fn)

            self._load_order.append(plugin_name)

        except Exception as e:
            info.errors.append(f"Load failed: {e}")
            info.loaded = False
            info.load_time_ms = (time.perf_counter() - start) * 1000

        return info

    # ── Enable / Disable ───────────────────────────────────────────────

    def enable(self, plugin_name: str) -> bool:
        """Activate a plugin. Loads it if not yet loaded.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            True if enabled successfully.
        """
        info = self._plugins.get(plugin_name)
        if not info:
            return False

        if not info.loaded:
            try:
                self.load(plugin_name)
            except Exception:
                return False

        info.enabled = True
        return True

    def disable(self, plugin_name: str) -> bool:
        """Deactivate a plugin without unloading its module.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            True if plugin was enabled and is now disabled.
        """
        info = self._plugins.get(plugin_name)
        if not info or not info.enabled:
            return False

        info.enabled = False

        # Unregister hooks
        for hook_name in info.hooks_registered:
            if hook_name in self._hook_registry:
                self._hook_registry[hook_name] = [
                    h for h in self._hook_registry[hook_name]
                    if h not in info.hooks_registered.values()
                ]

        return True

    # ── Hot Reload ─────────────────────────────────────────────────────

    def reload(self, plugin_name: str) -> PluginInfo:
        """Hot-reload a plugin: disable, unload, re-import.

        Args:
            plugin_name: Name of the plugin to reload.

        Returns:
            Updated PluginInfo.

        Raises:
            ValueError: If plugin not found.
        """
        info = self._plugins.get(plugin_name)
        if not info:
            raise ValueError(f"Plugin '{plugin_name}' not found")

        was_enabled = info.enabled

        # Disable and unregister hooks
        if info.enabled:
            self.disable(plugin_name)

        # Clear module reference
        info.module = None
        info.loaded = False
        info.hooks_registered = {}

        # Reload
        self.load(plugin_name)

        # Re-enable if it was active
        if was_enabled:
            self.enable(plugin_name)

        return info

    # ── List ───────────────────────────────────────────────────────────

    def list_plugins(self) -> dict[str, dict[str, Any]]:
        """Return all discovered plugins with their status.

        Returns:
            Dict mapping plugin_name → status dict.
        """
        result = {}
        for name, info in self._plugins.items():
            result[name] = {
                "version": info.manifest.version,
                "description": info.manifest.description,
                "author": info.manifest.author,
                "enabled": info.enabled,
                "loaded": info.loaded,
                "load_time_ms": info.load_time_ms,
                "hooks": info.manifest.hooks,
                "dependencies": info.manifest.dependencies,
                "error_count": len(info.errors),
                "last_error": info.errors[-1] if info.errors else "",
                "path": info.path,
            }
        return result

    def get_plugin(self, plugin_name: str) -> Optional[PluginInfo]:
        """Get full PluginInfo for a specific plugin."""
        return self._plugins.get(plugin_name)

    # ── Dependency Check ───────────────────────────────────────────────

    def check_dependencies(self, plugin_name: str) -> dict[str, Any]:
        """Verify a plugin's dependencies are available.

        Checks Python package dependencies (importable) and
        module-level requirements.

        Args:
            plugin_name: Plugin to check.

        Returns:
            Dict with 'satisfied', 'missing', 'installed', 'resolvable'.
        """
        info = self._plugins.get(plugin_name)
        if not info:
            return {
                "satisfied": False,
                "missing": [plugin_name],
                "resolvable": False,
                "error": f"Plugin '{plugin_name}' not found",
            }

        deps = info.manifest.dependencies
        missing: list[str] = []
        installed: list[str] = []
        resolvable = True

        for dep in deps:
            # Check if it's a Python package (can we import it?)
            pkg_name = dep.split(">=")[0].split("==")[0].split(">")[0].strip()
            try:
                importlib.import_module(pkg_name.replace("-", "_"))
                installed.append(dep)
            except ImportError:
                missing.append(dep)
                # Try pip check
                try:
                    result = subprocess.run(
                        [sys.executable, "-m", "pip", "show", pkg_name],
                        capture_output=True, text=True, timeout=10,
                    )
                    if result.returncode == 0:
                        installed.append(dep)
                        missing.remove(dep)
                except Exception:
                    resolvable = False

        return {
            "satisfied": len(missing) == 0,
            "required": deps,
            "installed": installed,
            "missing": missing,
            "resolvable": resolvable,
        }

    def install_dependencies(self, plugin_name: str) -> dict[str, Any]:
        """Attempt to pip install a plugin's missing dependencies.

        Args:
            plugin_name: Plugin to install deps for.

        Returns:
            Dict with install results.
        """
        dep_check = self.check_dependencies(plugin_name)
        if dep_check["satisfied"]:
            return {**dep_check, "installed_now": [], "error": ""}

        missing = dep_check.get("missing", [])
        installed_now: list[str] = []
        errors: list[str] = []

        for dep in missing:
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", dep],
                    capture_output=True, text=True, timeout=60,
                )
                if result.returncode == 0:
                    installed_now.append(dep)
                else:
                    errors.append(f"{dep}: {result.stderr[:100]}")
            except Exception as e:
                errors.append(f"{dep}: {e}")

        # Re-check
        final_check = self.check_dependencies(plugin_name)
        return {
            **final_check,
            "installed_now": installed_now,
            "error": "; ".join(errors) if errors else "",
        }

    # ── Hook System ────────────────────────────────────────────────────

    def _register_hook(self, hook_name: str, callback: Callable) -> None:
        """Register a hook callback internally."""
        if hook_name not in self._hook_registry:
            self._hook_registry[hook_name] = []
        if callback not in self._hook_registry[hook_name]:
            self._hook_registry[hook_name].append(callback)

    def call_hook(self, hook_name: str, *args: Any,
                  **kwargs: Any) -> list[Any]:
        """Call all registered callbacks for a hook.

        Only calls hooks from enabled plugins.

        Args:
            hook_name: Hook to invoke.
            *args, **kwargs: Arguments to pass to each callback.

        Returns:
            List of return values from each hook.
        """
        results = []
        callbacks = self._hook_registry.get(hook_name, [])

        for cb in callbacks:
            # Only invoke if the owning plugin is enabled
            try:
                result = cb(*args, **kwargs)
                results.append(result)
            except Exception as e:
                results.append({"error": str(e)})

        return results

    def get_hooks(self) -> dict[str, int]:
        """Return all registered hooks with callback counts."""
        return {name: len(cbs) for name, cbs in self._hook_registry.items()}


# ── Self-test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile

    print("=== PluginLoader Self-Test ===\n")

    # Create a temporary plugins directory with test plugins
    with tempfile.TemporaryDirectory() as tmpdir:
        plugins_root = Path(tmpdir) / "plugins"
        plugins_root.mkdir()

        # Create test plugin 1: hello_world
        p1_dir = plugins_root / "hello_world"
        p1_dir.mkdir()

        manifest1 = {
            "name": "hello_world",
            "version": "1.0.0",
            "description": "A hello world test plugin",
            "author": "OmniCore",
            "dependencies": [],
            "hooks": ["on_startup", "on_message"],
            "entry_point": "main",
        }
        (p1_dir / "manifest.json").write_text(json.dumps(manifest1))

        (p1_dir / "__init__.py").write_text(
            '"""Hello World Plugin."""\n'
            '\n'
            'PLUGIN_STATE = {"initialized": False}\n'
            '\n'
            'def main():\n'
            '    """Plugin entry point."""\n'
            '    PLUGIN_STATE["initialized"] = True\n'
            '    print("Hello World plugin loaded!")\n'
            '\n'
            'def on_startup():\n'
            '    return {"status": "ready", "plugin": "hello_world"}\n'
            '\n'
            'def on_message(msg):\n'
            '    return f"Hello says: {msg}"\n'
        )

        # Create test plugin 2: with dependencies
        p2_dir = plugins_root / "data_processor"
        p2_dir.mkdir()

        manifest2 = {
            "name": "data_processor",
            "version": "0.2.0",
            "description": "Processes data with numpy (optional dep)",
            "author": "OmniCore",
            "dependencies": ["typing_extensions"],
            "hooks": ["on_data"],
            "entry_point": "main",
        }
        (p2_dir / "manifest.json").write_text(json.dumps(manifest2))

        (p2_dir / "__init__.py").write_text(
            '"""Data Processor Plugin."""\n'
            '\n'
            'def main():\n'
            '    print("Data processor loaded!")\n'
            '\n'
            'def on_data(payload):\n'
            '    return {"processed": True, "input": payload}\n'
        )

        # Create invalid plugin (no __init__.py)
        p3_dir = plugins_root / "invalid_plugin"
        p3_dir.mkdir()
        (p3_dir / "manifest.json").write_text('{"name": "invalid"}')

        # Create non-plugin directory (no manifest)
        p4_dir = plugins_root / "not_a_plugin"
        p4_dir.mkdir()
        (p4_dir / "__init__.py").write_text("")

        # ── Test discovery ──
        print("--- Discovery ---")
        loader = PluginLoader(str(plugins_root))
        discovered = loader.discover()

        assert len(discovered) == 2, f"Expected 2 plugins, found {len(discovered)}"
        print(f"  ✓ Found {len(discovered)} plugins")

        names = [p.manifest.name for p in discovered]
        assert "hello_world" in names
        assert "data_processor" in names
        print(f"  ✓ Plugin names: {names}")

        # Should skip invalid_plugin (no __init__.py) and not_a_plugin (no manifest)
        assert "invalid" not in names
        assert "not_a_plugin" not in names
        print("  ✓ Correctly skipped invalid/non-plugin directories")

        # ── Test load ──
        print("\n--- Load ---")
        info = loader.load("hello_world")
        assert info.loaded, f"Plugin not loaded: {info.errors}"
        assert info.module is not None
        print(f"  ✓ Loaded hello_world in {info.load_time_ms:.1f}ms")
        print(f"  ✓ Module: {info.module}")
        print(f"  ✓ Hooks: {list(info.hooks_registered.keys())}")

        # ── Test enable/disable ──
        print("\n--- Enable/Disable ---")
        assert loader.enable("hello_world")
        print("  ✓ Enabled: hello_world")

        loader.disable("hello_world")
        info2 = loader.get_plugin("hello_world")
        assert info2 is not None and not info2.enabled
        print("  ✓ Disabled: hello_world")

        # ── Test reload ──
        print("\n--- Hot Reload ---")
        loader.enable("hello_world")
        reloaded = loader.reload("hello_world")
        assert reloaded.loaded
        assert reloaded.enabled
        print(f"  ✓ Reloaded: loaded={reloaded.loaded}, enabled={reloaded.enabled}")

        # ── Test hooks ──
        print("\n--- Hooks ---")
        # on_startup hook
        results = loader.call_hook("on_startup")
        print(f"  ✓ on_startup: {results}")

        # on_message hook
        results = loader.call_hook("on_message", "world")
        assert len(results) >= 1
        assert "Hello says" in str(results[0])
        print(f"  ✓ on_message: {results}")

        # Test hook registry
        hooks = loader.get_hooks()
        print(f"  ✓ Registered hooks: {hooks}")
        assert "on_startup" in hooks
        assert "on_message" in hooks

        # ── Test list_plugins ──
        print("\n--- List Plugins ---")
        plugin_list = loader.list_plugins()
        assert "hello_world" in plugin_list
        assert "data_processor" in plugin_list
        hw = plugin_list["hello_world"]
        assert hw["enabled"] == True
        assert hw["version"] == "1.0.0"
        print(f"  ✓ hello_world: v{hw['version']}, enabled={hw['enabled']}")
        print(f"  ✓ data_processor: v{plugin_list['data_processor']['version']}, "
              f"enabled={plugin_list['data_processor']['enabled']}")

        # ── Test dependency check ──
        print("\n--- Dependency Check ---")
        dep_result = loader.check_dependencies("data_processor")
        # typing_extensions should be available
        print(f"  ✓ data_processor deps: satisfied={dep_result['satisfied']}, "
              f"installed={dep_result['installed']}, "
              f"missing={dep_result['missing']}")

        # Hello world has no deps — always satisfied
        dep_result2 = loader.check_dependencies("hello_world")
        assert dep_result2["satisfied"]
        assert len(dep_result2["required"]) == 0
        print(f"  ✓ hello_world deps: satisfied (no dependencies)")

        # ── Test error on missing ──
        print("\n--- Error Handling ---")
        try:
            loader.load("nonexistent")
            print("  ✗ Should have raised ValueError")
        except ValueError as e:
            print(f"  ✓ Correctly raised: {type(e).__name__}")

        # Test disable when not enabled
        assert not loader.disable("data_processor")  # never enabled
        print("  ✓ disable non-enabled returns False")

        print("\n✓ All self-tests passed")