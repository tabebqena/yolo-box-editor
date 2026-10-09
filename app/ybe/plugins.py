"""Backend plugins for extension packages.

An extension package may ship a `backend:` Python module. When the package is
active (and shipped -- user backends are off by default, see below), the module
is imported and its `register(ctx)` is called. `register` may add Flask routes
to `ctx.app` and must return a `{method: callable}` capability table; the host
exposes those methods to the package's sandboxed panel through the `YBE` bridge
(`YBE.call`) and, as a headless fallback, through `/api/extensions/call`.

Capabilities run in this process, so they are trusted code: only the shipped
packages' backends are loaded. The `register` callable must be side-effect free
until a request arrives.
"""

import importlib.util
import os

from ybe import config, extension_flags, state
from ybe.packages import load_packages, package_backend_path


class PluginContext:
    """The object passed to a backend plugin's `register(ctx)`."""

    def __init__(self, app, package):
        self.app = app
        self.state = state
        self.config = config
        self.package = package

    def require_writable(self):
        """Raise when the app is in read-only mode (call from mutating caps)."""
        if state.STATE["readonly"]:
            raise PermissionError("read-only mode")


# package id -> {capability method: callable}
PLUGIN_CAPABILITIES = {}


def _import_module(pkg):
    """Import a package's `backend:` module by absolute path, or None."""
    path = package_backend_path(pkg)
    if not path:
        return None
    mod_name = "ybe_plugin_" + "".join(
        c if c.isalnum() else "_" for c in pkg["id"])
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install(app):
    """Load every active, shipped package's backend plugin.

    Called once at server setup. A backend that fails to import/register is
    skipped so one broken package cannot take the server down.
    """
    # Seed the tags enable/disable flag on first run (covers git-clone users who
    # never go through the installer).
    try:
        extension_flags.ensure_migrated()
    except Exception:  # noqa: BLE001 - migration must never block startup
        pass
    PLUGIN_CAPABILITIES.clear()
    for pkg in load_packages()[0]:
        if not pkg["active"] or not pkg.get("backend"):
            continue
        # Trust boundary: only shipped packages may run in-process code.
        if pkg["source"] != "shipped":
            continue
        try:
            module = _import_module(pkg)
            register = getattr(module, "register", None) if module else None
            if not callable(register):
                continue
            table = register(PluginContext(app, pkg)) or {}
            if isinstance(table, dict):
                PLUGIN_CAPABILITIES[pkg["id"]] = table
        except Exception as exc:  # noqa: BLE001 - a bad plugin must not brick the app
            print(f"[ybe] plugin '{pkg['id']}' failed to load: {exc}", file=__import__("sys").stderr)


def has_capability(package_id, method):
    """True when an active package declares `method` as a backend capability."""
    return method in (PLUGIN_CAPABILITIES.get(package_id) or {})


def call_capability(package_id, method, args):
    """Call a package capability; raises KeyError/TypeError for a bad call."""
    table = PLUGIN_CAPABILITIES.get(package_id) or {}
    fn = table.get(method)
    if not callable(fn):
        raise KeyError(f"unknown capability: {method}")
    return fn(*(args if isinstance(args, list) else []))
