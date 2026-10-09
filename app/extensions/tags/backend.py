"""Tags extension backend: tags.yaml, per-image tag files and the tags folder.

This is the whole tags feature, moved out of the core. It owns:

* `tags.yaml` beside the dataset's `data.yaml` (the available-tag list),
* each image's own tag file (`<tags-dir>/<stem>.txt`, one tag per line),
* a per-dataset tags-folder override (stored in the user home, keyed by the
  dataset path), and
* the routes `/api/tags` and `/api/tags-dir`.

The same helpers are exposed as `YBE` capabilities (`tags.*`) for the sandboxed
panel, and through `/api/extensions/call` for headless use.
"""

import json
import os

from ybe import state
from ybe.dataset import _current_images, _split_by_name
from ybe.parsing import _read_text

OVERRIDE_FILE = ".tags_extension.json"


# --- tags.yaml (available tags) ------------------------------------------- #
def _strip_comment(s):
    return s.split("#", 1)[0].strip()


def _normalize(tags):
    out = []
    if isinstance(tags, list):
        for t in tags:
            if not isinstance(t, str):
                continue
            t = t.strip()
            if t and "\n" not in t and t not in out:
                out.append(t)
    return out


def _is_toplevel_item(line):
    return (len(line) - len(line.lstrip()) == 0
            and _strip_comment(line.strip()).startswith("-"))


def _toplevel_names(lines):
    names = []
    for raw in lines:
        if not _is_toplevel_item(raw):
            continue
        name = _strip_comment(raw.strip())
        while name.startswith("-"):
            name = name[1:].strip()
        name = name.strip("'\"")
        if name:
            names.append(name)
    return names


def tags_yaml_path():
    if not state.STATE["data_yaml"]:
        return None
    return os.path.join(os.path.dirname(os.path.abspath(state.STATE["data_yaml"])), "tags.yaml")


def read_tags_yaml():
    path = tags_yaml_path()
    if not path:
        return []
    lines = _read_text(path).splitlines(keepends=True)
    return _normalize(_toplevel_names(lines))


def save_tags_yaml(tags):
    path = tags_yaml_path()
    if not path:
        return None
    tags = _normalize(tags)
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        lines = []
    lines = [ln for ln in lines if not _is_toplevel_item(ln)]
    out = []
    replaced = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if not replaced and _strip_comment(line.strip()).startswith("tags:"):
            for t in tags:
                out.append(f"- {t}\n")
            i += 1
            while i < len(lines) and _strip_comment(lines[i].strip()).startswith("-"):
                i += 1
            replaced = True
            continue
        out.append(line)
        i += 1
    if not replaced:
        if out and out[-1].strip():
            out.append("\n")
        for t in tags:
            out.append(f"- {t}\n")
    text = "".join(out)
    if not text.endswith("\n"):
        text += "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def register_available(tags):
    available = read_tags_yaml()
    if tags_yaml_path() is None:
        return available
    fresh = [t for t in _normalize(tags) if t not in available]
    if not fresh:
        return available
    available = available + fresh
    save_tags_yaml(available)
    return available


# --- per-dataset tags folder override ------------------------------------- #
def _override_path():
    # Stored in the user home so it survives without touching the dataset.
    from ybe import config
    return os.path.join(config.YBX_HOME, OVERRIDE_FILE)


def _load_overrides():
    try:
        with open(_override_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def get_tags_dir(data_yaml=None):
    """The remembered tags-folder override for a dataset, or None."""
    key = os.path.abspath(data_yaml or state.STATE["data_yaml"] or "")
    if not key:
        return None
    return _load_overrides().get(key)


def set_tags_dir(folder):
    key = os.path.abspath(state.STATE["data_yaml"] or "")
    if not key:
        return None
    data = _load_overrides()
    if folder:
        data[key] = folder
    else:
        data.pop(key, None)
    try:
        path = _override_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except OSError:
        pass
    return folder


def _replace_images_segment(images_dir, component):
    parts = images_dir.replace("\\", "/").rstrip("/").split("/")
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "images":
            parts[i] = component
            return "/".join(parts)
    return os.path.normpath(os.path.join(images_dir, "..", component, os.path.basename(images_dir)))


def split_tags_dir(split):
    """The tags folder for a split: override/<split>, else images -> tags."""
    override = get_tags_dir()
    if override:
        return os.path.join(override, split["name"])
    return _replace_images_segment(split["images_dir"], "tags")


def tag_path(entry):
    split = _split_by_name(entry["split"])
    if split is None:
        return None
    stem = os.path.splitext(entry["name"])[0]
    return os.path.join(split_tags_dir(split), stem + ".txt")


# --- reads / writes -------------------------------------------------------- #
def read_image_tags(entry):
    path = tag_path(entry)
    if not path:
        return []
    tags = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                t = line.strip()
                if t:
                    tags.append(t)
    except OSError:
        pass
    return tags


def write_image_tags(entry, tags):
    split = _split_by_name(entry["split"])
    path = tag_path(entry)
    if split is None or path is None:
        return None
    tags = _normalize(tags)
    os.makedirs(split_tags_dir(split), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(tags))
        if tags:
            f.write("\n")
    return path


def _entry_for_key(key):
    if not key or "/" not in key:
        return None
    split, name = key.split("/", 1)
    for e in state.STATE["images"]:
        if e["split"] == split and e["name"] == name:
            return e
    return None


def _previous_entry(entry):
    visible = _current_images()
    for i, e in enumerate(visible):
        if e["split"] == entry["split"] and e["name"] == entry["name"]:
            return visible[i - 1] if i > 0 else None
    return None


def _require_writable():
    if state.STATE["readonly"]:
        raise PermissionError("read-only mode")


# --- capabilities (used by the panel and /api/extensions/call) ------------ #
def _cap_available():
    return read_tags_yaml()


def _cap_get(key):
    entry = _entry_for_key(key)
    if entry is None:
        return []
    return read_image_tags(entry)


def _cap_set(key, tags):
    _require_writable()
    entry = _entry_for_key(key)
    if entry is None:
        raise ValueError("unknown image")
    write_image_tags(entry, tags)
    return {"tags": read_image_tags(entry), "available": register_available(tags)}


def _cap_clear(key):
    return _cap_set(key, [])


def _cap_copy_from_prev(key):
    _require_writable()
    entry = _entry_for_key(key)
    if entry is None:
        raise ValueError("unknown image")
    prev = _previous_entry(entry)
    return _cap_set(key, read_image_tags(prev) if prev else [])


def _cap_set_dir(folder):
    _require_writable()
    folder = (folder or "").strip()
    path = os.path.abspath(os.path.expanduser(folder)) if folder else None
    if path and not os.path.isdir(path):
        raise ValueError(f"not a folder: {path}")
    set_tags_dir(path)
    state.STATE["splits"] = _rescan_splits()
    return {"tags_dir": path}


def _rescan_splits():
    from ybe.dataset import scan_splits
    return scan_splits()


# --- HTTP routes (declared for the host's runtime dispatcher) -------------- #
def _get_tags():
    from flask import jsonify, request
    key = request.args.get("key", "")
    return jsonify({"ok": True, "available": read_tags_yaml(), "tags": _cap_get(key)})


def _post_tags():
    from flask import jsonify, request
    if state.STATE["readonly"]:
        return jsonify({"ok": False, "error": "read-only mode"}), 403
    data = request.get_json(silent=True) or {}
    try:
        result = _cap_set(data.get("key", ""), data.get("tags"))
    except (ValueError, PermissionError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    result["ok"] = True
    return jsonify(result)


def _post_tags_dir():
    from flask import jsonify, request
    if state.STATE["readonly"]:
        return jsonify({"ok": False, "error": "read-only mode"}), 403
    data = request.get_json(silent=True) or {}
    try:
        result = _cap_set_dir(data.get("tags_dir"))
    except (ValueError, PermissionError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    result["ok"] = True
    return jsonify(result)


# Declarative routes served by the host's catch-all dispatcher (no `@app.route`,
# so enabling this package needs no restart).
extension_routes = (
    {"rule": "/api/tags", "methods": ["GET"], "handler": _get_tags},
    {"rule": "/api/tags", "methods": ["POST"], "handler": _post_tags},
    {"rule": "/api/tags-dir", "methods": ["POST"], "handler": _post_tags_dir},
)


def register(ctx):
    """Return the capability table (routes are declared in `extension_routes`)."""
    return {
        "capabilities": {
            "tags.available": lambda *a: _cap_available(),
            "tags.get": lambda key: _cap_get(key),
            "tags.set": lambda key, tags: _cap_set(key, tags),
            "tags.clear": lambda key: _cap_clear(key),
            "tags.copyFromPrev": lambda key: _cap_copy_from_prev(key),
            "tags.setDir": lambda folder: _cap_set_dir(folder),
        },
    }
