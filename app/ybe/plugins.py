"""Backend plugins for extension packages.

An extension package may ship a `backend:` Python module that provides:

* **capabilities** — a `{method: callable}` table (returned by `register`),
  reachable from the panel as `YBE.call` and from `/api/extensions/call`;
* **routes** — a module-level `extension_routes` tuple of
  `{"rule": "/api/...", "methods": ["GET"], "handler": fn}` dicts (the host also
  accepts them under a returned `{"routes": [...]}`). Handlers run inside a
  Flask request context, so `request`, `session`, `g` and `current_app` work.

Routes are **not** registered on the Flask app. Instead the app installs one
startup catch-all (`/api/<path:subpath>`) whose view asks this module to
`dispatch` the request against the *currently enabled* packages. That means a
package can be enabled/disabled at runtime (see `enable`/`disable`) without a
restart: nothing is added to Flask's URL map after startup.

Capabilities run in this process, so they are trusted code: only **shipped**
packages' backends are loaded.
"""

import importlib.util
import os
import re
import sys

from flask import Response, abort, jsonify

from ybe import config, extension_flags, state
from ybe.packages import load_packages, package_backend_path, package_route_prefix


class PluginContext:
    """The object passed to a backend plugin's `register(ctx)`."""

    def __init__(self, app, package):
        self.app = app
        self.state = state
        self.config = config
        self.package = package

    def require_writable(self):
        """Raise when the app is in read-only mode (call from mutating code)."""
        if state.STATE["readonly"]:
            raise PermissionError("read-only mode")


# Enabled packages: id -> {package, module, capabilities, routes}.
PLUGIN_REGISTRY = {}
# id -> capability table (kept in sync with PLUGIN_REGISTRY for callers/tests).
PLUGIN_CAPABILITIES = {}

# `<converter>` -> regex for the route rules.
_PARAM_CONVERTERS = {
    "string": "[^/]+", "": "[^/]+", "int": r"\d+",
    "float": r"[-\d.]+", "path": ".+", "uuid": "[0-9a-fA-F-]+",
}
_COMPILED = {}


def _compile_rule(rule):
    """Compile a Flask-style rule (`/api/x/<int:key>`) once into a regex."""
    if rule in _COMPILED:
        return _COMPILED[rule]
    pattern = ""
    i, n = 0, len(rule)
    while i < n:
        if rule[i] == "<":
            j = rule.find(">", i)
            if j < 0:
                pattern += re.escape(rule[i:])
                break
            inner = rule[i + 1:j]
            conv, sep, name = inner.partition(":")
            if not sep:
                name, conv = conv, "string"
            pattern += "(?P<%s>%s)" % (
                re.sub(r"\W", "_", name), _PARAM_CONVERTERS.get(conv, "[^/]+"))
            i = j + 1
        else:
            pattern += re.escape(rule[i])
            i += 1
    compiled = re.compile("^" + pattern + "$")
    _COMPILED[rule] = compiled
    return compiled


def _normalize_routes(raw, prefix):
    """Validate routes, mount them under the package prefix, compile the rules.

    A declared `rule` is relative to `/api/extension/<prefix>` (an empty rule is
    the mount point itself), so package rules can never collide.
    """
    base = config.EXTENSION_ROUTE_PREFIX.rstrip("/") + "/" + prefix
    routes = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        handler = entry.get("handler")
        if not callable(handler):
            continue
        rule = str(entry.get("rule") or "")
        if rule and not rule.startswith("/"):
            rule = "/" + rule
        full = base + rule
        methods = entry.get("methods") or entry.get("method") or ["GET"]
        if isinstance(methods, str):
            methods = [methods]
        routes.append({
            "rule": full,
            "methods": [str(m).upper() for m in methods],
            "handler": handler,
            "regex": _compile_rule(full),
        })
    return routes


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


def _load_backend(app, pkg):
    """Import + register one backend; returns (module, capabilities, routes)."""
    module = _import_module(pkg)
    if module is None:
        return None, {}, []
    capabilities, routes = {}, list(getattr(module, "extension_routes", None) or [])
    register = getattr(module, "register", None)
    if callable(register):
        returned = register(PluginContext(app, pkg)) or {}
        if isinstance(returned, dict):
            if "capabilities" in returned or "routes" in returned:
                capabilities = returned.get("capabilities") or {}
                routes += list(returned.get("routes") or [])
            else:
                capabilities = returned
    if not isinstance(capabilities, dict):
        capabilities = {}
    return module, capabilities, _normalize_routes(routes, package_route_prefix(pkg))


def enable(app, package_id):
    """Load one package's backend into the live registry (idempotent).

    Returns True when the package is enabled (already or just now), False when
    there is no loadable shipped backend.
    """
    if package_id in PLUGIN_REGISTRY:
        return True
    pkg = next((p for p in load_packages()[0] if p["id"] == package_id), None)
    if pkg is None or pkg["source"] != "shipped" or not pkg.get("backend"):
        return False
    # Route prefixes must be unique: refuse a package whose prefix is already
    # claimed by an earlier package (first one in discovery order wins).
    prefix = package_route_prefix(pkg)
    for other in load_packages()[0]:
        if other["id"] == pkg["id"]:
            break
        if package_route_prefix(other) == prefix:
            print("[ybe] plugin '%s' not enabled: route prefix '%s' already used by '%s'"
                  % (package_id, prefix, other["id"]), file=sys.stderr)
            return False
    try:
        module, capabilities, routes = _load_backend(app, pkg)
    except Exception as exc:  # noqa: BLE001 - a bad plugin must not brick the app
        print("[ybe] plugin '%s' failed to load: %s" % (package_id, exc), file=sys.stderr)
        return False
    if module is None:
        return False
    PLUGIN_REGISTRY[package_id] = {
        "package": pkg, "module": module,
        "capabilities": capabilities, "routes": routes,
    }
    PLUGIN_CAPABILITIES[package_id] = capabilities
    return True


def disable(package_id):
    """Remove a package's backend from the live registry (teardown optional)."""
    entry = PLUGIN_REGISTRY.pop(package_id, None)
    PLUGIN_CAPABILITIES.pop(package_id, None)
    if entry is None:
        return False
    teardown = getattr(entry["module"], "teardown", None)
    if callable(teardown):
        try:
            teardown()
        except Exception:  # noqa: BLE001
            pass
    return True


def is_loaded(package_id):
    """True when a package's backend is currently in the live registry."""
    return package_id in PLUGIN_REGISTRY


def loaded_packages():
    """The ids of every package whose backend is currently enabled."""
    return sorted(PLUGIN_REGISTRY)


def install(app):
    """Enable every active, shipped package backend at startup."""
    # Seed the tags enable/disable flag on first run (covers git-clone users who
    # never go through the installer).
    try:
        extension_flags.ensure_migrated()
    except Exception:  # noqa: BLE001 - migration must never block startup
        pass
    PLUGIN_REGISTRY.clear()
    PLUGIN_CAPABILITIES.clear()
    for pkg in load_packages()[0]:
        if pkg["active"] and pkg.get("backend"):
            enable(app, pkg["id"])


def has_capability(package_id, method):
    """True when an enabled package declares `method` as a capability."""
    return method in (PLUGIN_CAPABILITIES.get(package_id) or {})


def call_capability(package_id, method, args):
    """Call a package capability; raises KeyError for an unknown method."""
    table = PLUGIN_CAPABILITIES.get(package_id) or {}
    fn = table.get(method)
    if not callable(fn):
        raise KeyError("unknown capability: %s" % method)
    return fn(*(args if isinstance(args, list) else []))


def _normalize_result(result):
    """Coerce a handler's return value into something Flask accepts."""
    if isinstance(result, Response) or hasattr(result, "get_data"):
        return result
    if isinstance(result, tuple):
        return result
    if result is None:
        return "", 204
    if isinstance(result, (dict, list)):
        return jsonify(result)
    if isinstance(result, str):
        return result
    return jsonify(result)


def dispatch(method, path):
    """Route an `/api/...` request to an enabled package's declared handler.

    Called by the startup catch-all view. Matching is against the live registry,
    so enabling/disabling a package takes effect immediately. Raises 404 when no
    enabled package owns the path.
    """
    method = (method or "GET").upper()
    for entry in PLUGIN_REGISTRY.values():
        for route in entry["routes"]:
            if method not in route["methods"]:
                continue
            match = route["regex"].match(path)
            if not match:
                continue
            try:
                return _normalize_result(route["handler"](**match.groupdict()))
            except Exception as exc:  # noqa: BLE001 - surface the handler's error
                print("[ybe] extension route %s failed: %s" % (path, exc), file=sys.stderr)
                return jsonify({"ok": False, "error": str(exc)}), 500
    abort(404)
