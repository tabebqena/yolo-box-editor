"""Extension packages: a folder that groups actions, hooks, filters and widgets.

An extension is a folder with an `extension.yaml` manifest and optional
`actions/`, `hooks/`, `filters/` and `widgets/` subfolders. This is an additive
layer: the flat `actions/`, `hooks/`, `filters/` and `widgets/` folders keep
working exactly as before, and the loaders simply also scan each active package's
subfolders (a flat file wins over a package file of the same name/source).

The manifest may also declare a `settings:` block (rendered as a Settings >
Extensions subtab) in the same shape as a widget's controls, and an `events:`
list of extra event names the package emits. No function here executes anything.
"""

import os

from ybe import config, extension_flags, permissions
from ybe.parsing import (
    _parse_api_version,
    _read_text,
    _strip_comment,
    _yaml_scalar,
)


def _indented_block(text, key):
    """Return the block under a top-level `key:`, relative indentation kept.

    Unlike `parsing._extract_yaml_block` (which flattens a names list), the
    result is dedented by the block's own minimum indentation, so a nested
    `settings:` block can be re-parsed as a widget.
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if len(line) - len(line.lstrip(" ")) == 0 and line.strip().startswith(key + ":"):
            start = i
            break
    if start is None:
        return None
    base = len(lines[start]) - len(lines[start].lstrip(" "))
    collected = []
    for line in lines[start + 1:]:
        if not line.strip():
            collected.append("")
            continue
        if len(line) - len(line.lstrip(" ")) <= base:
            break
        collected.append(line)
    while collected and not collected[0].strip():
        collected.pop(0)
    while collected and not collected[-1].strip():
        collected.pop()
    if not collected:
        return None
    indents = [len(l) - len(l.lstrip(" ")) for l in collected if l.strip()]
    cut = min(indents)
    return "\n".join(l[cut:] if l.strip() else "" for l in collected)

# Which subfolder holds each extension kind.
_KIND_SUBDIR = {"action": "actions", "hook": "hooks", "filter": "filters", "widget": "widgets"}
# The flat (loose-file) folders per source and kind.
_FLAT_DIRS = {
    "shipped": {
        "action": lambda: config.ACTIONS_DIR,
        "hook": lambda: config.HOOKS_DIR,
        "filter": lambda: config.FILTERS_DIR,
        "widget": lambda: config.WIDGETS_DIR,
    },
    "user": {
        "action": lambda: config.USER_ACTIONS_DIR,
        "hook": lambda: config.USER_HOOKS_DIR,
        "filter": lambda: config.USER_FILTERS_DIR,
        "widget": lambda: config.USER_WIDGETS_DIR,
    },
}


def _parse_manifest(text):
    """Parse an `extension.yaml` into a dict of its keys."""
    data = {
        "id": None, "name": None, "description": None, "version": None,
        "author": None, "active": True, "api_version": None, "prefix": None,
        "settings": None, "events": [], "ui": None,
        "backend": None, "app_actions": [],
    }
    lines = text.splitlines(keepends=True)
    for raw in lines:
        if len(raw) - len(raw.lstrip(" ")) != 0:
            continue  # only top-level keys
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key, value = key.strip(), _strip_comment(value)
        if key == "api_version":
            data["api_version"] = _parse_api_version(value)
        elif key in ("id", "name", "description", "version", "author", "backend", "prefix"):
            if value:
                data[key] = _yaml_scalar(value)
        elif key == "active":
            if value:
                data["active"] = value.lower() not in ("false", "no", "0")

    actions_block = _indented_block(text, "app_actions")
    if actions_block:
        data["app_actions"] = _parse_app_actions(actions_block)

    # `settings:` is a widget-shaped block (title + controls); reuse the widget
    # parser/validator so both share one control format.
    settings_block = _indented_block(text, "settings")
    if settings_block:
        from ybe.widgets import _parse_widget_file, _validate_widget
        parsed = _parse_widget_file(settings_block)
        widget, _errors = _validate_widget("settings.yaml", parsed)
        if widget is not None:
            data["settings"] = {
                "title": widget["title"],
                "controls": widget["controls"],
            }

    events_block = _indented_block(text, "events")
    if events_block:
        for line in events_block.splitlines():
            line = line.strip()
            if line.startswith("- "):
                name = _yaml_scalar(line[2:].strip())
                if name and name not in data["events"]:
                    data["events"].append(name)

    ui_block = _indented_block(text, "ui")
    if ui_block:
        ui = _parse_ui(ui_block)
        if ui is not None:
            data["ui"] = ui
    return data


def _parse_app_actions(block):
    """Parse an `app_actions:` block into a list of action dicts.

    Format (dedented by `_indented_block`):
        - name: refresh_image_tags
          label: Refresh image tags
          shortcut: Alt+R          # optional default binding
          capability: tags.load    # optional backend fallback
    """
    entries = []
    current = None
    for raw in block.splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("- "):
            current = {"name": None, "label": None, "shortcut": None, "capability": None}
            entries.append(current)
            s = s[2:].strip()
            if not s:
                continue
        if current is None or ":" not in s:
            continue
        key, _, value = s.partition(":")
        key, value = key.strip(), _yaml_scalar(_strip_comment(value))
        if key in current and value:
            current[key] = value
    out = []
    for entry in entries:
        if not entry["name"]:
            continue
        if not entry["label"]:
            entry["label"] = entry["name"]
        out.append(entry)
    return out


def _parse_ui(block):
    """Parse a `ui:` block into its fields, or None when there is no script.

    Format (dedented by `_indented_block`):
        api_version: 1
        title: My Panel
        script: panel.js
        location: float     # float | left | right | bottom
        height: 220         # optional initial body height, px
    """
    ui = {"api_version": None, "title": None, "script": None,
          "location": "float", "height": None}
    for raw in block.splitlines():
        if len(raw) - len(raw.lstrip(" ")) != 0:
            continue
        s = raw.strip()
        if not s or s.startswith("#") or ":" not in s:
            continue
        key, _, value = s.partition(":")
        key, value = key.strip(), _strip_comment(value)
        if key == "api_version":
            ui["api_version"] = _parse_api_version(value)
        elif key in ("title", "script", "location"):
            ui[key] = _yaml_scalar(value)
        elif key == "height":
            try:
                ui["height"] = int(float(value))
            except (TypeError, ValueError):
                ui["height"] = None
    if ui["location"] not in ("float", "left", "right", "bottom"):
        ui["location"] = "float"
    if not ui["script"]:
        return None
    return ui


def plugin_api_status(version):
    """Classify a panel's `ui.api_version` against `config.PLUGIN_API_VERSION`."""
    if not isinstance(version, int):
        return "outdated"
    if version < config.PLUGIN_API_VERSION:
        return "outdated"
    if version > config.PLUGIN_API_VERSION:
        return "newer"
    return "current"


def package_relative_path(pkg, rel):
    """Resolve `rel` inside a package folder, or None when missing/unsafe.

    Resolves the real path and requires it to stay inside the package folder, so
    a `..` or absolute path can never escape it.
    """
    if not rel:
        return None
    base = os.path.realpath(pkg["path"])
    target = os.path.realpath(os.path.join(base, rel))
    try:
        if os.path.commonpath([base, target]) != base:
            return None
    except ValueError:
        return None  # e.g. different drives on Windows
    if not os.path.isfile(target):
        return None
    return target


def package_script_path(pkg):
    """Absolute path of a package's `ui.script`, or None when missing/unsafe."""
    return package_relative_path(pkg, (pkg.get("ui") or {}).get("script"))


def package_backend_path(pkg):
    """Absolute path of a package's `backend:` module, or None when missing/unsafe."""
    return package_relative_path(pkg, pkg.get("backend"))


def package_route_prefix(pkg):
    """The unique URL prefix a package's routes are mounted under.

    The manifest `prefix:` if given, else the package id; sanitized to
    `[a-z0-9_-]` so it is always a safe path segment.
    """
    raw = (pkg.get("prefix") or pkg.get("id") or "").strip().lower()
    safe = "".join(c if (c.isalnum() or c in "-_") else "-" for c in raw).strip("-_")
    return safe or "ext"


def package_route_prefix_duplicates():
    """`{prefix: [package ids]}` for every prefix used by more than one package."""
    by_prefix = {}
    for pkg in load_packages()[0]:
        by_prefix.setdefault(package_route_prefix(pkg), []).append(pkg["id"])
    return {prefix: ids for prefix, ids in by_prefix.items() if len(ids) > 1}


def extension_app_action_defs(only_active=True):
    """Every declared extension app action as a list of dicts.

    Each dict: `{id, extension, name, label, shortcut, capability, source}` where
    `id` is the fully-qualified `<extension_id>.<name>` used in steps and events.
    """
    out = []
    for pkg in load_packages()[0]:
        if only_active and not pkg["active"]:
            continue
        for entry in pkg["app_actions"]:
            name = entry["name"]
            out.append({
                "id": config.EXTENSION_ACTION_PREFIX + pkg["id"] + "." + name,
                "extension": pkg["id"],
                "name": name,
                "label": entry["label"],
                "shortcut": entry["shortcut"],
                "capability": entry["capability"],
                "source": pkg["source"],
            })
    return out


def extension_app_action_ids():
    """The set of valid extension app-action ids (`<ext>.<name>`)."""
    return {d["id"] for d in extension_app_action_defs()}


def _discover_parts(path):
    """Map each extension kind to its `.yaml` file names inside a package."""
    parts = {}
    for kind, sub in _KIND_SUBDIR.items():
        dirpath = os.path.join(path, sub)
        if not os.path.isdir(dirpath):
            continue
        files = sorted(
            f for f in os.listdir(dirpath)
            if f.endswith(".yaml") and os.path.isfile(os.path.join(dirpath, f))
        )
        if files:
            parts[kind] = files
    return parts


def load_packages():
    """Discover extension packages -> (list, errors) (read fresh).

    A package is a subfolder of `extensions/` (shipped then user) that holds an
    `extension.yaml`. Its id is the manifest `id:` key, else the folder name; the
    user folder wins on an id clash.
    """
    merged, errors = {}, []
    for source, root in (("shipped", config.EXTENSIONS_DIR),
                         ("user", config.USER_EXTENSIONS_DIR)):
        if not os.path.isdir(root):
            continue
        for entry in sorted(os.listdir(root)):
            path = os.path.join(root, entry)
            manifest_path = os.path.join(path, "extension.yaml")
            if not os.path.isdir(path) or not os.path.isfile(manifest_path):
                continue
            data = _parse_manifest(_read_text(manifest_path))
            pid = (data["id"] or entry).strip()
            if not pid:
                continue
            if isinstance(data["api_version"], int) and data["api_version"] > config.EXTENSION_API_VERSION:
                errors.append(
                    "'extensions/%s/extension.yaml': written for extension format "
                    "v%s, but this app supports v%s — update yolo-box-editor to "
                    "use it" % (entry, data["api_version"], config.EXTENSION_API_VERSION))
                continue
            merged[pid] = {
                "id": pid,
                "name": (data["name"] or pid).strip(),
                "description": (data["description"] or "").strip(),
                "version": (data["version"] or "").strip(),
                "author": (data["author"] or "").strip(),
                "active": data["active"],
                "api_version": data["api_version"],
                "settings": data["settings"],
                "events": data["events"],
                "ui": data["ui"],
                "backend": data["backend"],
                "app_actions": data["app_actions"],
                "prefix": (data["prefix"] or "").strip() or None,
                "parts": _discover_parts(path),
                "source": source,
                "path": path,
            }
    # A user-level enable/disable override (extensions.json) wins over the
    # manifest's own `active:`, so a package can be turned on/off across updates.
    overrides = extension_flags.load_flags()
    for pid, pkg in merged.items():
        if pid in overrides:
            pkg["active"] = overrides[pid]
        # Permissions: what the package declares, and anything it ships that the
        # declaration does not cover (so callers can flag dishonest packages).
        perms = permissions.read_permissions(pkg)
        pkg["permissions"] = perms
        pkg["permission_errors"] = permissions.coverage_errors(pkg, perms)
        pkg["permission_unknown"] = (
            permissions.unknown_ybe_permissions(perms) if perms else [])
    return list(merged.values()), errors


def _active_packages(source):
    """Active packages of one source (``shipped``/``user``)."""
    return [p for p in load_packages()[0] if p["source"] == source and p["active"]]


def package_for_file(path):
    """The package a file lives in, or None (used by the API for display)."""
    target = os.path.abspath(path)
    for pkg in load_packages()[0]:
        base = os.path.abspath(pkg["path"])
        if os.path.commonpath([base, target]) == base:
            return pkg["id"]
    return None


def extension_sources(kind):
    """Ordered `(source, dirpath, package_id)` for one kind.

    Per source the package subfolders come first and the flat folder last, so a
    flat file always wins over a package file of the same name/source.
    """
    out = []
    for source in ("shipped", "user"):
        for pkg in _active_packages(source):
            sub = os.path.join(pkg["path"], _KIND_SUBDIR[kind])
            if os.path.isdir(sub):
                out.append((source, sub, pkg["id"]))
        out.append((source, _FLAT_DIRS[source][kind](), None))
    return out


def package_dirs(kind):
    """The active package subfolders for one kind as `(source, dirpath, id)`.

    (Deprecated alias kept for callers that only need packages, not flat files.)
    """
    return [entry for entry in extension_sources(kind) if entry[2] is not None]
