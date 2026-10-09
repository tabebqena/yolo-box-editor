"""Extension permissions: the `permissions.yaml` a package declares.

An extension is code the user installs, so it must be honest about what it
touches. Every package (built-in or installed) may ship a `permissions.yaml`
listing:

* `ybe:` — which `YBE` bridge capabilities its panel uses (we own the interface,
  so each key has a documented meaning: see `YBE_PERMISSIONS`);
* `backend:` / `ui:` — whether it ships server-side Python (`backend.py`) or a
  sandboxed panel (`panel.js`);
* `routes:`, `actions:`, `hooks:`, `filters:`, `widgets:`, `app_actions:`,
  `events:`, `scripts:` — the extension artifacts it adds.

`coverage_errors` flags anything a package ships/declares that is not listed, so
the UI and the installer can tell the user "it asks for more than it declared".
`YBE_METHOD_PERMISSIONS` maps each bridge method to the permission it needs; the
host enforces it per panel.
"""

import os

# Human-readable meaning of every YBE capability a panel may request.
YBE_PERMISSIONS = {
    "state.read": "Read editor state: current image, boxes, classes, split and counts.",
    "config.read": "Read the app configuration (dataset paths, settings, defs).",
    "api.request": "Call any /api/* endpoint through the host (GET/POST).",
    "capabilities": "Run the package's own backend capabilities (YBE.call).",
    "write.boxes": "Replace the boxes on the current image.",
    "write.selection": "Change the box selection.",
    "write.draw": "Ask the editor to repaint and mark the image changed.",
    "write.save": "Save the current image.",
    "run_action": "Run any action (actions can execute shell commands).",
    "refresh": "Re-read the current image's pixels or labels.",
    "ui.message": "Show a toast or status message to the user.",
    "ui.settings": "Open the Settings dialog.",
    "settings": "Read and write this panel's own stored settings.",
}

# Bridge method -> the permission a panel must declare to call it.
YBE_METHOD_PERMISSIONS = {
    "state.getImage": "state.read",
    "state.getImageIndex": "state.read",
    "state.getBoxes": "state.read",
    "state.getClasses": "state.read",
    "state.getActiveSplit": "state.read",
    "state.getImageCount": "state.read",
    "state.isDatasetLoaded": "state.read",
    "state.getConfig": "config.read",
    "api.request": "api.request",
    "call": "capabilities",
    "callbacks.setBoxes": "write.boxes",
    "callbacks.addBox": "write.boxes",
    "callbacks.selectBox": "write.selection",
    "callbacks.clearSelection": "write.selection",
    "callbacks.markDirty": "write.draw",
    "callbacks.draw": "write.draw",
    "callbacks.drawBox": "write.draw",
    "callbacks.setDrawnBoxes": "write.draw",
    "callbacks.clearDrawnBoxes": "write.draw",
    "callbacks.setDrawnBoxesVisible": "write.draw",
    "callbacks.save": "write.save",
    "callbacks.runAction": "run_action",
    "callbacks.refreshImage": "refresh",
    "callbacks.toast": "ui.message",
    "callbacks.setStatus": "ui.message",
    "callbacks.openSettings": "ui.settings",
    "callbacks.getSetting": "settings",
    "callbacks.setSetting": "settings",
}

PERMISSION_FILE = "permissions.yaml"
# Artifact lists a permission file may declare.
ARTIFACT_KEYS = (
    "routes", "actions", "hooks", "filters", "widgets",
    "app_actions", "events", "scripts",
)
_KIND_SUBDIR = {
    "action": "actions", "hook": "hooks", "filter": "filters", "widget": "widgets",
}


# --- parsing -------------------------------------------------------------- #
def _strip_comment(value):
    return value.split("#", 1)[0].strip()


def _scalar(value):
    value = _strip_comment(value)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _list_block(lines, key):
    """The `- item` lines directly under a top-level `key:`, in order."""
    items = []
    base = None
    collecting = False
    for raw in lines:
        if len(raw) - len(raw.lstrip(" ")) == 0:
            stripped = _strip_comment(raw.strip())
            if stripped.startswith(key + ":"):
                collecting = True
                base = 0
                continue
            if collecting:
                break  # a new top-level key ends the block
        if not collecting:
            continue
        item = _strip_comment(raw.strip())
        if item.startswith("-"):
            item = item[1:].strip()
            item = _scalar(item)
            if item:
                items.append(item)
    return items


def parse_permissions(text):
    """Parse a `permissions.yaml` into a dict (never raises)."""
    data = {
        "api_version": None, "ybe": [], "backend": False, "ui": False,
        "routes": [], "actions": [], "hooks": [], "filters": [], "widgets": [],
        "app_actions": [], "events": [], "scripts": [],
    }
    lines = text.splitlines()
    for raw in lines:
        if len(raw) - len(raw.lstrip(" ")) != 0:
            continue
        stripped = _strip_comment(raw.strip())
        if not stripped or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key, value = key.strip(), _scalar(value)
        if key == "api_version":
            try:
                data["api_version"] = int(value)
            except (TypeError, ValueError):
                data["api_version"] = None
        elif key in ("backend", "ui"):
            data[key] = value.lower() not in ("false", "no", "0", "")
    for key in ("ybe",) + ARTIFACT_KEYS:
        data[key] = _list_block(lines, key)
    return data


def read_permissions_path(path):
    """Parse `<path>/permissions.yaml`; None when the file is absent."""
    try:
        with open(os.path.join(path, PERMISSION_FILE), encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return None
    return parse_permissions(text)


def read_permissions(pkg):
    """Parse a package's `permissions.yaml`; None when it has none."""
    return read_permissions_path(pkg["path"])


# --- description ---------------------------------------------------------- #
_KIND_LABELS = {
    "routes": "Route", "actions": "Action", "hooks": "Hook", "filters": "Filter",
    "widgets": "Widget", "app_actions": "App action", "events": "Event",
    "scripts": "Script",
}


def describe(perms):
    """Human-readable lines explaining everything a package declares."""
    if not perms:
        return []
    out = []
    for key in perms.get("ybe", []):
        out.append("YBE: %s — %s" % (key, YBE_PERMISSIONS.get(key, "unknown permission")))
    if perms.get("backend"):
        out.append("Runs server-side Python (backend.py has full app access).")
    if perms.get("ui"):
        out.append("Runs a sandboxed UI panel (panel.js).")
    for kind in ARTIFACT_KEYS:
        label = _KIND_LABELS.get(kind, kind)
        for item in perms.get(kind, []):
            out.append("%s: %s" % (label, item))
    return out


# --- coverage / honesty check --------------------------------------------- #
def _yaml_name(path, default):
    """The top-level `name:` (or `title:`) of a small YAML file, else `default`."""
    try:
        with open(path, encoding="utf-8") as handle:
            for raw in handle:
                if len(raw) - len(raw.lstrip(" ")) != 0:
                    continue
                stripped = _strip_comment(raw.strip())
                for key in ("name", "title"):
                    if stripped.startswith(key + ":"):
                        value = _scalar(stripped.split(":", 1)[1])
                        if value:
                            return value
    except OSError:
        pass
    return default


def package_artifacts(pkg):
    """What a package actually ships/declares, by kind (for the honesty check)."""
    art = {key: [] for key in ARTIFACT_KEYS}
    art["backend"] = bool(pkg.get("backend"))
    art["ui"] = bool(pkg.get("ui"))
    parts = pkg.get("parts") or {}
    for kind, sub in _KIND_SUBDIR.items():
        for fname in parts.get(kind, []):
            stem = fname[:-5] if fname.endswith(".yaml") else fname
            # hooks are named by their event (`on_after_save`)
            default = stem
            art[kind + "s"].append(_yaml_name(os.path.join(pkg["path"], sub, fname), default))
    scripts_dir = os.path.join(pkg["path"], "scripts")
    if os.path.isdir(scripts_dir):
        art["scripts"] = sorted(
            f for f in os.listdir(scripts_dir)
            if f.endswith(".py") and os.path.isfile(os.path.join(scripts_dir, f)))
    art["app_actions"] = [a["name"] for a in pkg.get("app_actions", [])]
    art["events"] = list(pkg.get("events", []))
    return art


def coverage_errors(pkg, perms):
    """List everything a package ships that its permissions.yaml does not cover."""
    if perms is None:
        return []
    errors = []
    art = package_artifacts(pkg)
    for kind in ("actions", "hooks", "filters", "widgets", "app_actions", "events", "scripts"):
        declared = set(perms.get(kind) or [])
        for name in art[kind]:
            if name not in declared:
                errors.append("%s %r is not declared in %s" % (kind[:-1], name, PERMISSION_FILE))
    if art["backend"] and not perms.get("backend"):
        errors.append("ships backend.py but does not set `backend: true`")
    if art["ui"] and not perms.get("ui"):
        errors.append("ships a UI panel but does not set `ui: true`")
    return errors


def unknown_ybe_permissions(perms):
    """YBE keys in the file that this app does not know (typos / newer app)."""
    return [k for k in (perms.get("ybe") or []) if k not in YBE_PERMISSIONS]


def allows(method, perms):
    """True when `perms` grants the permission a bridge `method` needs.

    A package without a permission file (legacy) is allowed for backward
    compatibility; the UI flags the missing file instead.
    """
    if perms is None:
        return True
    need = YBE_METHOD_PERMISSIONS.get(method)
    if need is None:
        return True
    return need in (perms.get("ybe") or [])
