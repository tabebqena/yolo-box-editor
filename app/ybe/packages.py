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

from ybe import config
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
        "author": None, "active": True, "api_version": None,
        "settings": None, "events": [],
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
        elif key in ("id", "name", "description", "version", "author"):
            if value:
                data[key] = _yaml_scalar(value)
        elif key == "active":
            if value:
                data["active"] = value.lower() not in ("false", "no", "0")

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
    return data


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
                "parts": _discover_parts(path),
                "source": source,
                "path": path,
            }
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
