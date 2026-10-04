"""The per-user config.json: recent datasets, per-dataset views and UI settings.

One JSON file in the user home holds everything the browser would otherwise
store locally (recent data files, each dataset's split/filter/tags view and
disabled extensions, and cross-browser UI settings). Legacy per-purpose files
are migrated in and removed on first use.
"""

import json
import os
import threading

from ybe import config, state
from ybe.dataset import scan_splits
from ybe.extensions import load_filters
from ybe.filters import apply_filters

# RLock: each accessor reads-modifies-writes the whole file, and a routed call
# (e.g. `_set_extension_disabled` -> `_disabled_extensions`) may re-enter.
_CONFIG_LOCK = threading.RLock()


def _read_json_file(path):
    """Parse a JSON file; None when it is missing or invalid."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _default_config():
    return {"recent": [], "views": {}, "settings": {}}


def _normalize_config(data):
    """Coerce a loaded config into the known shape (never raises)."""
    cfg = _default_config()
    if not isinstance(data, dict):
        return cfg
    recent = data.get("recent")
    if isinstance(recent, list):
        cfg["recent"] = [p for p in recent if isinstance(p, str)][:config.MAX_RECENT]
    views = data.get("views")
    if isinstance(views, dict):
        cfg["views"] = {k: v for k, v in views.items() if isinstance(v, dict)}
    settings = data.get("settings")
    if isinstance(settings, dict):
        cfg["settings"] = dict(settings)
    return cfg


def _migrate_legacy_config():
    """Build a config from the old per-purpose files (read once)."""
    cfg = _default_config()
    recent = _read_json_file(config.RECENT_FILE)
    if isinstance(recent, list):
        cfg["recent"] = [p for p in recent if isinstance(p, str)][:config.MAX_RECENT]
    views = _read_json_file(config.VIEW_FILE)
    if isinstance(views, dict):
        cfg["views"] = {k: v for k, v in views.items() if isinstance(v, dict)}
    settings = _read_json_file(config.SETTINGS_FILE)
    if isinstance(settings, dict):
        cfg["settings"] = dict(settings)
    return cfg


def _remove_legacy_files():
    """Delete the old files once their contents live in config.CONFIG_FILE."""
    for path in (config.RECENT_FILE, config.VIEW_FILE, config.SETTINGS_FILE):
        if path and path != config.CONFIG_FILE:
            try:
                os.remove(path)
            except OSError:
                pass


def _write_config(cfg):
    """Write the config atomically (temp file + rename); never raises."""
    try:
        os.makedirs(os.path.dirname(config.CONFIG_FILE) or ".", exist_ok=True)
        tmp = config.CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
            f.write("\n")
        os.replace(tmp, config.CONFIG_FILE)
    except OSError:
        pass


def _load_config_unlocked():
    """Read config.json, migrating the legacy files on first use.

    A corrupt config.json yields an empty config but is left on disk so it can
    still be fixed by hand.
    """
    try:
        with open(config.CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        cfg = _migrate_legacy_config()
        _write_config(cfg)
        _remove_legacy_files()
        return cfg
    except (OSError, ValueError):
        return _default_config()
    return _normalize_config(data)


def _load_config():
    with _CONFIG_LOCK:
        return _load_config_unlocked()


def _update_config(mutate):
    """Read-modify-write the config under the lock; returns the new config."""
    with _CONFIG_LOCK:
        cfg = _load_config_unlocked()
        mutate(cfg)
        _write_config(cfg)
        return cfg


def _load_recent():
    """Read the last opened data.yaml paths (newest first)."""
    return _load_config()["recent"]


def _push_recent(path):
    """Record an opened data.yaml, newest first, capped at config.MAX_RECENT."""
    def mutate(cfg):
        recents = [p for p in cfg["recent"] if p != path]
        recents.insert(0, path)
        cfg["recent"] = recents[:config.MAX_RECENT]

    return _update_config(mutate)["recent"]


def _load_views():
    """The saved per-dataset views ({data_yaml: {...}})."""
    return _load_config()["views"]


def _save_view(data_yaml, split, active_filters):
    """Remember a dataset's split/filter chain and tags folder so a restart reopens it.

    Other per-dataset view keys (the disabled action/hook lists, the last image)
    are preserved.
    """
    if not data_yaml:
        return

    def mutate(cfg):
        entry = cfg["views"].get(data_yaml)
        if not isinstance(entry, dict):
            entry = {}
        entry["split"] = split
        entry["filters"] = list(active_filters or [])
        entry["tags_dir"] = state.STATE.get("tags_dir")
        cfg["views"][data_yaml] = entry

    _update_config(mutate)


# A dataset's disabled extensions live in its view entry under the "disabled"
# key: {"actions": [names], "hooks": [names]}. This maps an extension `kind` to
# its list key. The flag is a per-dataset view preference, so it never edits the
# extension files themselves (a hook's own `active: false` is separate).
DISABLED_KIND_KEYS = {"action": "actions", "hook": "hooks"}


def _disabled_extensions():
    """The current dataset's disabled action/hook names.

    Returns `{"action": set, "hook": set}`; empty when no dataset is loaded or
    nothing was disabled.
    """
    data_yaml = state.STATE.get("data_yaml")
    view = _load_views().get(data_yaml) if data_yaml else None
    disabled = view.get("disabled") if isinstance(view, dict) else None
    disabled = disabled if isinstance(disabled, dict) else {}
    return {
        kind: {n for n in (disabled.get(key) or []) if isinstance(n, str)}
        for kind, key in DISABLED_KIND_KEYS.items()
    }


def _set_extension_disabled(kind, name, disabled):
    """Record or clear one disabled action/hook in the current dataset's view.

    Returns the fresh disabled sets (see `_disabled_extensions`), or None when no
    dataset is loaded. Read-only is not consulted: this is a view preference, not
    a dataset write.
    """
    data_yaml = state.STATE.get("data_yaml")
    if not data_yaml:
        return None
    key = DISABLED_KIND_KEYS[kind]

    def mutate(cfg):
        entry = cfg["views"].get(data_yaml)
        if not isinstance(entry, dict):
            entry = {}
        stored = entry.get("disabled")
        stored = stored if isinstance(stored, dict) else {}
        names = [n for n in (stored.get(key) or []) if isinstance(n, str)]
        if disabled:
            if name not in names:
                names.append(name)
        else:
            names = [n for n in names if n != name]
        stored[key] = sorted(names)
        entry["disabled"] = stored
        cfg["views"][data_yaml] = entry

    _update_config(mutate)
    return _disabled_extensions()


def _restore_tags_dir(data_yaml):
    """Apply a dataset's remembered tags folder and re-derive the split paths."""
    view = _load_views().get(data_yaml) if data_yaml else None
    tags_dir = view.get("tags_dir") if isinstance(view, dict) else None
    state.STATE["tags_dir"] = tags_dir if tags_dir and os.path.isdir(tags_dir) else None
    if state.STATE["splits"]:
        state.STATE["splits"] = scan_splits()


def _load_settings():
    """Read the cross-browser UI settings (a flat `{key: value}` map)."""
    return _load_config()["settings"]


def _update_settings(changes):
    """Merge `{key: value}` into the settings section; a null value deletes the key.

    The browser sends only the keys the user just changed, so a partial merge
    keeps every other browser's settings intact.
    """
    if not isinstance(changes, dict):
        return _load_settings()

    def mutate(cfg):
        settings = cfg["settings"]
        for key, value in changes.items():
            if value is None:
                settings.pop(key, None)
            else:
                settings[key] = value

    return _update_config(mutate)["settings"]


def _restore_view(data_yaml):
    """Re-apply a dataset's remembered split/filter, ignoring stale entries.

    The `data.yaml` (and its filter scripts) may have changed since the view was
    saved, so only names that still exist are applied.
    """
    view = _load_views().get(data_yaml)
    if not isinstance(view, dict):
        return
    _restore_tags_dir(data_yaml)
    split = view.get("split")
    if split in {s["name"] for s in state.STATE["splits"]}:
        state.STATE["active_split"] = split
    # `filters` is the current shape ({name, arguments}); `filter` was a
    # single-name (legacy) view and a list of names is the older chain shape.
    raw = view.get("filters")
    if not isinstance(raw, list):
        raw = [view["filter"]] if view.get("filter") else []
    known = load_filters()[0]
    chain = []
    for item in raw:
        if isinstance(item, str):
            item = {"name": item}
        if isinstance(item, dict) and item.get("name") in known:
            chain.append(item)
    if chain:
        apply_filters(chain)
