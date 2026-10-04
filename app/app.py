#!/usr/bin/env python3
"""YOLO labelling app served by Flask.

Usage:
    python app/app.py --data /path/to/data.yaml
    python app/app.py --data /path/to/data.yaml --readonly   # viewer only

The data.yaml file can also be set from the web interface.

Expected data.yaml layout:

    path: /path/to/dataset_root      # optional; defaults to the data.yaml dir
    train: images/train
    val: images/val
    test: images/test                # optional

    nc: 3
    names: ['cat', 'dog', 'bird']    # one-line list, or a block form

For each split (train/val/test) the labels folder is the corresponding folder
with the `images` path segment replaced by `labels`
(e.g. `images/train` -> `labels/train`).
"""

import argparse
import getpass
import json
import logging
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid

from flask import (
    Flask,
    abort,
    jsonify,
    render_template,
    request,
    send_from_directory,
    session,
)
from werkzeug.security import check_password_hash, generate_password_hash

from ybe.parsing import (
    _extract_yaml_block,
    _is_toplevel_list_item,
    _line_comment,
    _normalize_tags,
    _parse_api_version,
    _parse_data_yaml,
    _parse_version,
    _parse_yaml_names_value,
    _read_tag_lines,
    _read_text,
    _read_text_lines,
    _read_yaml_names,
    _strip_comment,
    _toplevel_list_names,
    _version_newer,
    _yaml_scalar,
    parse_shortcut_line,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # the shipped app/ directory


def _resolve_home():
    """The user folder: `--home` (applied later) > $YBX_HOME > parent of app.py.

    The parent of `app.py` is the user root in both an installed copy
    (`<root>/app/app.py`) and a git clone (`<repo>/app/app.py`), so both behave
    identically without extra flags.
    """
    env = os.environ.get("YBX_HOME")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    return os.path.dirname(BASE_DIR)


YBX_HOME = _resolve_home()

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}

# Built-in, shipped files (inside app/); replaced wholesale on upgrade.
ACTIONS_DIR = os.path.join(BASE_DIR, "actions")  # one YAML file per action
HOOKS_DIR = os.path.join(BASE_DIR, "hooks")  # one YAML file per event hook
FILTERS_DIR = os.path.join(BASE_DIR, "filters")  # one YAML file per filter
APP_SCRIPT_DIR = os.path.join(BASE_DIR, "scripts")  # shipped helper programs
SHORTCUTS_FILE = os.path.join(BASE_DIR, "shortcuts.txt")
VERSION_FILE = os.path.join(BASE_DIR, "VERSION")  # shipped app version
CHANGES_FILE = os.path.join(BASE_DIR, "CHANGES")  # per-version "what's new" notes

# User files (inside YBX_HOME); read after the built-ins and win on a clash.
USER_ACTIONS_DIR = os.path.join(YBX_HOME, "actions")
USER_HOOKS_DIR = os.path.join(YBX_HOME, "hooks")
USER_FILTERS_DIR = os.path.join(YBX_HOME, "filters")
USER_SCRIPT_DIR = os.path.join(YBX_HOME, "scripts")
USER_SHORTCUTS_FILE = os.path.join(YBX_HOME, "shortcuts.txt")
# One JSON file holds all per-user config: recent datasets, per-dataset views
# (split/filter/tags/disabled + last image) and cross-browser UI settings. It
# sits in YBX_HOME, outside `app/`, so app updates never touch it.
CONFIG_FILE = os.path.join(YBX_HOME, "config.json")
# The update-check cache is a throwaway background result, so it stays its own
# file; `_load_update_cache` / `check_for_update` own it.
UPDATE_CHECK_FILE = os.path.join(YBX_HOME, ".update_check.json")
# Legacy per-purpose files, read once to migrate into CONFIG_FILE and then
# removed. Kept as module constants so tests can redirect them.
RECENT_FILE = os.path.join(YBX_HOME, ".recent_data_yamls.json")
VIEW_FILE = os.path.join(YBX_HOME, ".view_state.json")  # active split/filter per dataset
SETTINGS_FILE = os.path.join(YBX_HOME, ".settings.json")  # cross-browser UI prefs
# Login accounts: {"version": 1, "users": {"name": "<password_hash>"}}. A
# non-empty store turns login on; the file is owner-only (0600) because it holds
# password hashes. Managed with --create-user / --list-users and seeded with
# admin/admin on first run (ensure_default_admin).
USERS_FILE = os.path.join(YBX_HOME, "users.json")

# Update check: compare the shipped VERSION with the newest GitHub one. A check
# is skipped while the cache is fresh (< UPDATE_CHECK_INTERVAL) and the running
# version is unchanged; the start thread polls, so the network is only hit after
# the interval has passed.
UPDATE_REPO = "tabebqena/yolo-box-editor"
UPDATE_API = f"https://api.github.com/repos/{UPDATE_REPO}"
UPDATE_RAW = f"https://raw.githubusercontent.com/{UPDATE_REPO}"
UPDATE_CHECK_INTERVAL = 7 * 24 * 60 * 60  # re-check at most once a week
UPDATE_POLL_INTERVAL = 6 * 60 * 60  # how often the start thread wakes up
UPDATE_CHECK_TIMEOUT = 5  # seconds per network request

# Per-run {PIPE_PATH} files live in the system temp dir (never in the repo).
PIPE_DIR = os.path.join(tempfile.gettempdir(), "yolo-box-editor-pipes")
# Per-run filter-chain scratch dirs (input/output pipes) live here too.
FILTER_PIPES_DIR = os.path.join(tempfile.gettempdir(), "yolo-box-editor-filter-pipes")


def configure_home(path):
    """Point the user folders at `path` (the `--home` override)."""
    global YBX_HOME, USER_ACTIONS_DIR, USER_HOOKS_DIR, USER_FILTERS_DIR
    global USER_SCRIPT_DIR, USER_SHORTCUTS_FILE, RECENT_FILE, VIEW_FILE
    global SETTINGS_FILE, UPDATE_CHECK_FILE, CONFIG_FILE, USERS_FILE
    YBX_HOME = os.path.abspath(os.path.expanduser(path))
    USER_ACTIONS_DIR = os.path.join(YBX_HOME, "actions")
    USER_HOOKS_DIR = os.path.join(YBX_HOME, "hooks")
    USER_FILTERS_DIR = os.path.join(YBX_HOME, "filters")
    USER_SCRIPT_DIR = os.path.join(YBX_HOME, "scripts")
    USER_SHORTCUTS_FILE = os.path.join(YBX_HOME, "shortcuts.txt")
    CONFIG_FILE = os.path.join(YBX_HOME, "config.json")
    RECENT_FILE = os.path.join(YBX_HOME, ".recent_data_yamls.json")
    VIEW_FILE = os.path.join(YBX_HOME, ".view_state.json")
    SETTINGS_FILE = os.path.join(YBX_HOME, ".settings.json")
    UPDATE_CHECK_FILE = os.path.join(YBX_HOME, ".update_check.json")
    USERS_FILE = os.path.join(YBX_HOME, "users.json")


def ensure_user_dirs():
    """Create the user folders when missing, so the home is usable right away."""
    for dirpath in (USER_ACTIONS_DIR, USER_HOOKS_DIR, USER_FILTERS_DIR, USER_SCRIPT_DIR):
        try:
            os.makedirs(dirpath, exist_ok=True)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# logging (stderr by default; a file when daemonized with --log-file)
# --------------------------------------------------------------------------- #
class _SkipPresenceFilter(logging.Filter):
    """Drop the frequent `/api/presence` access-log lines (client heartbeat)."""

    def filter(self, record):
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - never let logging fail on formatting
            return True
        return "/api/presence" not in message


def setup_logging(log_file=None, debug=False):
    """Configure logging; with `log_file`, daemon-mode output goes to that file.

    Returns the app logger. Werkzeug's access logger is routed through the same
    handler, minus the `/api/presence` heartbeat.
    """
    level = logging.DEBUG if debug else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = None
    if log_file:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
            handler = logging.FileHandler(log_file, encoding="utf-8")
        except OSError:
            handler = None
    if handler is None:
        handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root.addHandler(handler)

    werkzeug = logging.getLogger("werkzeug")
    werkzeug.setLevel(level)
    werkzeug.handlers = []  # use the root handler instead of its own console one
    werkzeug.propagate = True
    werkzeug.filters = [f for f in werkzeug.filters if not isinstance(f, _SkipPresenceFilter)]
    werkzeug.addFilter(_SkipPresenceFilter())

    return logging.getLogger("ybe")

# Built-in app actions; may be rebound in shortcuts.txt but cannot be renamed.
APP_ACTIONS = {
    "app_prev",
    "app_next",
    "app_del",
    "app_drop",
    "app_save",
    "app_undo",
    "app_redo",
    "app_ch_box",
    "app_sel_box",
    "app_sel_points",
    "app_escape",
    "app_show_hide",
    "app_fix_box",
    "app_force_draw",
    "app_refresh_images_list",
    "app_reload_images_list",
    "app_refresh_image",
}

# Server-side built-in actions (name -> callable) usable as a `steps` /
# `after_success` entry. They run inline on the backend, unlike `app_*` which
# pauses for the UI, so an action can ask the server to change its own state
# (e.g. re-scan the image folders) even when no browser is driving the run.
# Defined here so `_resolve_entry` / `_advance_execution` can see it; the actual
# callables are registered next to `_rescan_images` below.
BACKEND_ACTION_NAMES = {"backend_rescan_images"}

# Shipped "tip of the day" ideas, shown once per day (per browser). The browser
# remembers which it has seen so a new one appears each day until they cycle.
TIPS = [
    "Draw a box by dragging on the image; press Esc to drop a box you just drew by mistake.",
    "Select a box, then Tab cycles through its class and cx/cy/w/h fields; Esc leaves the row.",
    "Shift selects the next box, resuming from the last one you had active.",
    "Alt+1 … Alt+9 toggles the matching tag from tags.yaml — no mouse needed.",
    "Right-click a tag badge? No — just click any badge to toggle it on or off.",
    "Settings → Layout lets every widget (Tags, Boxes, Actions, Navigation, Save) float or dock to any panel.",
    "Drag a floating window by its title bar; the L/T/R/B buttons dock it to an edge.",
    "Resize the side, dock and bottom panels by dragging their divider — the size is remembered.",
    "Filters (Settings → Filters) narrow the image list; stack up to eight of them top to bottom.",
    "Actions and hooks live in your user folder; a hook runs on events like on_after_save.",
    "Turn on Auto-save (Settings → General) so Prev/Next never asks you to save.",
    "Read-only mode (--readonly) is a safe way to browse a dataset without changing labels.",
    "Save (S) writes only when there are changes; Undo (Z) and Redo (Y) cover every edit.",
    "After an external tool edits the current image, use app_refresh_image to reload it in place.",
    "New tag names are added to tags.yaml when you save the image.",
    "Paste the path to your data.yaml in Settings → Dataset, or use the Recent… dropdown.",
    "Click a box on the image to select it; its row in the Boxes list becomes editable.",
    "Type a number in the counter and press Enter to jump straight to that image.",
    "The split dropdown switches between train / val / test, or shows all of them together.",
    "Your last image is remembered per split, so switching back to a split returns you to it.",
    "Read-only mode is a safe way to look around: it never writes labels or tags.",
    "Every shortcut can be changed in shortcuts.txt — no code editing needed.",
    "Settings → Updates checks GitHub and tells you when a newer version is available.",
    "The ⚙ button opens Settings; Esc closes any dialog.",
    "Your UI settings are saved on the server too, so a new browser starts with your layout.",
    "Hooks run on events like on_after_save; see docs/actions-and-hooks.md for examples.",
]

MAX_RECENT = 10
ACTION_TIMEOUT = 120  # seconds
FILTER_TIMEOUT = 120  # seconds
MAX_CASCADE_DEPTH = 8  # max actions run by one execution (root + after_success)
# In a steps/after_success entry, another action is named `action_<Name>` so a
# bare action name can never be confused with a shell command.
ACTION_REF_PREFIX = "action_"

# Event hooks live in the hooks/ folder and fire on app events (never from a
# toolbar button or a shortcut). A hook file is named `on_<event>.yaml`; when the
# file name does not resolve to a known event, its `event_name:` key is used.
HOOK_PREFIX = "on_"
HOOK_EVENTS = (
    "images_list_loaded",
    "image_loaded",
    "before_prev",
    "before_next",
    "prev",
    "next",
    "before_save",
    "after_save",
    "box_created",
    "box_deleted",
    "box_edited",
)

# The extension YAML format version. Bump it only when the action/hook/filter
# file format changes: the UI compares a file's `api_version:` against this to
# flag files that predate (or postdate) the format it understands.
EXTENSION_API_VERSION = 1

# Placeholder catalogs offered by the UI's click-to-insert palette. Keep them in
# sync with the values built in `api_action_run` and `_filter_placeholder_values`
# (and with the tables in docs/actions-and-hooks.md and docs/filters.md).
ACTION_PLACEHOLDERS = (
    ("IMAGE_PATH", "path of the current image"),
    ("LABEL_PATH", "path of the current image's label file (may not exist yet)"),
    ("DATASET_PATH", "root path of the loaded dataset"),
    ("DATA_YAML_PATH", "path of the loaded data.yaml"),
    ("IMAGE_INDEX", "1-based position of the current image in the list"),
    ("APP_DIR", "the shipped code folder (app/)"),
    ("HOME_DIR", "your user folder (the working directory of every run)"),
    ("APP_SCRIPT_DIR", "the shipped helper scripts (app/scripts/)"),
    ("USER_SCRIPT_DIR", "your helper scripts (<home>/scripts/)"),
    ("PYTHON", "the Python interpreter running the app"),
    ("PIPE_PATH", "the per-run scratch file shared by the run's steps"),
)
FILTER_PLACEHOLDERS = (
    ("DATA_YAML_PATH", "path of the loaded data.yaml"),
    ("DATASET_PATH", "root path of the loaded dataset"),
    ("SPLIT", "active split (train/val/test) or empty on All splits"),
    ("INPUT_PIPE", "file with the candidate image paths (one per line)"),
    ("OUTPUT_PIPE", "file to write the kept image paths to"),
    ("APP_DIR", "the shipped code folder (app/)"),
    ("HOME_DIR", "your user folder (the working directory of every run)"),
    ("APP_SCRIPT_DIR", "the shipped helper scripts (app/scripts/)"),
    ("USER_SCRIPT_DIR", "your helper scripts (<home>/scripts/)"),
    ("PYTHON", "the Python interpreter running the app"),
)


def _placeholder_payload(catalog):
    """`ACTION_PLACEHOLDERS` -> the UI shape `{token, description}`."""
    return [
        {"token": "{" + name + "}", "name": name, "description": desc}
        for name, desc in catalog
    ]


def api_version_status(version):
    """Classify a file's `api_version` against `EXTENSION_API_VERSION`.

    Returns "current", "outdated" (missing or lower) or "newer" (higher); a
    non-integer value counts as outdated.
    """
    if not isinstance(version, int):
        return "outdated"
    if version < EXTENSION_API_VERSION:
        return "outdated"
    if version > EXTENSION_API_VERSION:
        return "newer"
    return "current"


def is_hook_name(name):
    """True when `name` looks like a hook name (`on_*`)."""
    return bool(name) and name.startswith(HOOK_PREFIX)


app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)
# Signs the login session cookie. Random per process: a restart (or the debug
# reloader) invalidates existing sessions, which is fine for a single instance.
# Tests never rely on a stable key.
app.secret_key = secrets.token_hex(32)

# Persistent login accounts as a {username: password_hash} map, loaded from
# USERS_FILE at startup. Empty (the default) means login is off; any entry turns
# it on. Passwords are only ever stored hashed.
USERS = {}

STATE = {
    "data_yaml": None,
    "dataset_path": None,
    "splits": [],   # [{"name": "train", "images_dir": ..., "labels_dir": ...}]
    "images": [],   # flat navigation list: [{"split": "train", "name": "a.jpg"}]
    "active_split": None,  # None = all splits; or a single split name
    "active_filters": [],   # chain of {name, arguments} from filters/ ([] = none)
    "filter_images": None,  # cached filter-chain result (list of {split, name})
    "filter_error": None,   # last filter failure/notice message (shown in the UI)
    "classes": [],  # resolved class names from data.yaml `names`
    "tags_dir": None,  # per-dataset override for the tags folder (None = derive)
    "readonly": False,
    "debug": False,  # --debug: the UI logs verbose messages to the browser console
    "keep_pipe": False,  # --keep-pipe: do not delete the {PIPE_PATH} file after a run
    "keep_filter_pipes": False,  # --keep-filter-pipes: keep the filter scratch dir
    "no_update_check": False,  # --no-update-check: never check GitHub for updates
}

# In-flight action executions, paused at a client-side (app_*) after_success
# entry: uid -> execution state (see _begin_execution / _advance_execution). The
# backend owns the whole chain, so it also owns the run's {PIPE_PATH} file.
EXECUTIONS = {}

# Connected clients, for the multi-tab / multi-client presence warning: a client
# id (kept per browser tab by the UI) -> last-seen monotonic timestamp. A client
# that stops pinging /api/presence for PRESENCE_TTL seconds is considered gone.
# Presence is informational only: it never blocks or changes any other route.
CLIENTS = {}
CLIENTS_LOCK = threading.Lock()
PRESENCE_TTL = 15  # seconds


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def is_image(name):
    return os.path.splitext(name)[1].lower() in IMAGE_EXTS


# --------------------------------------------------------------------------- #
# user config (one JSON file: recent datasets + per-dataset views + UI settings)
# --------------------------------------------------------------------------- #
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
        cfg["recent"] = [p for p in recent if isinstance(p, str)][:MAX_RECENT]
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
    recent = _read_json_file(RECENT_FILE)
    if isinstance(recent, list):
        cfg["recent"] = [p for p in recent if isinstance(p, str)][:MAX_RECENT]
    views = _read_json_file(VIEW_FILE)
    if isinstance(views, dict):
        cfg["views"] = {k: v for k, v in views.items() if isinstance(v, dict)}
    settings = _read_json_file(SETTINGS_FILE)
    if isinstance(settings, dict):
        cfg["settings"] = dict(settings)
    return cfg


def _remove_legacy_files():
    """Delete the old files once their contents live in CONFIG_FILE."""
    for path in (RECENT_FILE, VIEW_FILE, SETTINGS_FILE):
        if path and path != CONFIG_FILE:
            try:
                os.remove(path)
            except OSError:
                pass


def _write_config(cfg):
    """Write the config atomically (temp file + rename); never raises."""
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE) or ".", exist_ok=True)
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
            f.write("\n")
        os.replace(tmp, CONFIG_FILE)
    except OSError:
        pass


def _load_config_unlocked():
    """Read config.json, migrating the legacy files on first use.

    A corrupt config.json yields an empty config but is left on disk so it can
    still be fixed by hand.
    """
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
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
    """Record an opened data.yaml, newest first, capped at MAX_RECENT."""
    def mutate(cfg):
        recents = [p for p in cfg["recent"] if p != path]
        recents.insert(0, path)
        cfg["recent"] = recents[:MAX_RECENT]

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
        entry["tags_dir"] = STATE.get("tags_dir")
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
    data_yaml = STATE.get("data_yaml")
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
    data_yaml = STATE.get("data_yaml")
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
    STATE["tags_dir"] = tags_dir if tags_dir and os.path.isdir(tags_dir) else None
    if STATE["splits"]:
        STATE["splits"] = scan_splits()


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
    if split in {s["name"] for s in STATE["splits"]}:
        STATE["active_split"] = split
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


# --------------------------------------------------------------------------- #
# update check (newest GitHub version vs. this app's VERSION)
# --------------------------------------------------------------------------- #
_UPDATE_THREAD = None


def read_version():
    """The shipped app version, from app/VERSION (never raises)."""
    try:
        with open(VERSION_FILE, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    return line.strip()
    except OSError:
        pass
    return "unknown"


def _http_get_text(url, timeout=UPDATE_CHECK_TIMEOUT):
    """GET a URL and return its body as text (GitHub needs a User-Agent)."""
    req = urllib.request.Request(url, headers={"User-Agent": f"yolo-box-editor/{read_version()}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def fetch_latest_version(timeout=UPDATE_CHECK_TIMEOUT):
    """Newest published version, or None when it cannot be determined.

    Considers the latest release **and** every tag and returns the highest
    version (so a newer tag is not hidden by an older release), else the `main`
    branch's VERSION. Any network/parse error is swallowed.
    """
    candidates = []
    try:
        data = json.loads(_http_get_text(f"{UPDATE_API}/releases/latest", timeout))
        tag = str(data.get("tag_name") or "").strip().lstrip("vV")
        if tag:
            candidates.append(tag)
    except (urllib.error.URLError, OSError, ValueError, AttributeError):
        pass
    try:
        data = json.loads(_http_get_text(f"{UPDATE_API}/tags", timeout))
        if isinstance(data, list):
            for entry in data:
                name = str((entry or {}).get("name") or "").strip().lstrip("vV")
                if name:
                    candidates.append(name)
    except (urllib.error.URLError, OSError, ValueError, AttributeError):
        pass

    parsed = [(v, name) for name, v in ((n, _parse_version(n)) for n in candidates) if v]
    if parsed:
        return max(parsed)[1]
    try:
        text = _http_get_text(f"{UPDATE_RAW}/main/app/VERSION", timeout).strip()
        if text:
            return text.splitlines()[0].strip()
    except (urllib.error.URLError, OSError):
        pass
    return candidates[0] if candidates else None


def parse_changes(text):
    """Parse the shipped CHANGES file into `{version: [lines]}`.

    A `## <version>` line starts a section; every following non-empty line is
    that version's changelog (a leading `- ` is stripped). Lines before the
    first section (the header comment) are ignored.
    """
    sections = {}
    current = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current is not None and line:
            sections[current].append(line[2:].strip() if line.startswith("- ") else line)
    return sections


def load_changes():
    """The shipped CHANGES sections (empty on error)."""
    try:
        with open(CHANGES_FILE, encoding="utf-8") as f:
            return parse_changes(f.read())
    except OSError:
        return {}


def changelog_for(version):
    """The changelog lines for `version` (empty when it has no section)."""
    return load_changes().get((version or "").strip(), [])


def _load_update_cache():
    """The last update-check result, or {} when missing/invalid."""
    try:
        with open(UPDATE_CHECK_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _update_payload(info):
    """A stable UI shape built from a (possibly empty) cache entry."""
    current = info.get("current_version") or read_version()
    latest = info.get("latest_version")
    return {
        "current_version": current,
        "latest_version": latest,
        "update_available": bool(latest) and _version_newer(latest, current),
        "checked_at": info.get("checked_at"),
    }


def update_status():
    """The cached update info; never touches the network (fast for /api/config)."""
    return _update_payload(_load_update_cache())


def check_for_update(force=False, now=None):
    """Check for a newer version, using/storing the cache, and return its payload.

    A network request is made only when `force` is set, the cache is missing, it
    is older than UPDATE_CHECK_INTERVAL, or the running version changed.
    """
    now = time.time() if now is None else now
    current = read_version()
    cache = _load_update_cache()
    checked_at = cache.get("checked_at")
    fresh = (
        isinstance(checked_at, (int, float))
        and now - checked_at < UPDATE_CHECK_INTERVAL
        and cache.get("current_version") == current
    )
    if fresh and not force:
        return _update_payload(cache)

    latest = fetch_latest_version()
    info = {
        "checked_at": now,
        "current_version": current,
        "latest_version": latest,
    }
    try:
        os.makedirs(os.path.dirname(UPDATE_CHECK_FILE), exist_ok=True)
        with open(UPDATE_CHECK_FILE, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2)
            f.write("\n")
    except OSError:
        pass
    return _update_payload(info)


def _update_check_loop():
    """Check now, then wake up periodically (the cache enforces the weekly gap)."""
    while True:
        try:
            check_for_update()
        except Exception:  # noqa: BLE001 - the checker must never crash the app
            pass
        time.sleep(UPDATE_POLL_INTERVAL)


def start_update_checker():
    """Start the background update checker once (no-op when disabled)."""
    global _UPDATE_THREAD
    if STATE.get("no_update_check"):
        return
    if _UPDATE_THREAD is not None and _UPDATE_THREAD.is_alive():
        return
    _UPDATE_THREAD = threading.Thread(target=_update_check_loop, name="update-check", daemon=True)
    _UPDATE_THREAD.start()


# --------------------------------------------------------------------------- #
# actions/ (user-configurable shell actions, one YAML file per action)
# --------------------------------------------------------------------------- #
def _parse_action_file(text):
    """Parse one action/hook file into a dict of its top-level keys.

    Top-level keys (2-space indentation, whole-line # comments):
        name: Remove            # optional; the file name is used otherwise
        event_name: after_save  # hooks only: fallback event when the file
                                # name does not encode one
        active: false           # hooks only: ignore this file
        steps:
          - rm -f {IMAGE_PATH}
        after_success:
          - app_refresh_images_list
    `steps` and `after_success` may also be a single value on the key line.
    """
    data = {
        "name": None,
        "event_name": None,
        "active": True,
        "api_version": None,
        "steps": [],
        "after_success": [],
    }
    section = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0 and ":" in stripped:
            key, _, value = stripped.partition(":")
            key, value = key.strip(), value.strip()
            if key == "name":
                section = None
                if value:
                    data["name"] = _yaml_scalar(value)
            elif key == "api_version":
                section = None
                data["api_version"] = _parse_api_version(value)
            elif key == "event_name":
                section = None
                if value:
                    data["event_name"] = _yaml_scalar(value)
            elif key == "active":
                section = None
                if value:
                    data["active"] = value.lower() not in ("false", "no", "0")
            elif key in ("steps", "after_success"):
                section = data[key]
                if value and value != "[]":
                    section.append(_yaml_scalar(value))
            else:
                section = None
        elif section is not None and stripped.startswith("- "):
            section.append(_yaml_scalar(stripped[2:].strip()))
    return data


def _action_files(dirpath):
    """Sorted `.yaml` paths in `dirpath`."""
    if not os.path.isdir(dirpath):
        return []
    paths = []
    for fname in sorted(os.listdir(dirpath)):
        if not fname.endswith(".yaml"):
            continue
        path = os.path.join(dirpath, fname)
        if os.path.isfile(path):
            paths.append(path)
    return paths


def _action_name(path, explicit):
    """The action's name: its `name:` key when given, else the file name."""
    if explicit:
        return explicit
    fname = os.path.basename(path)
    return fname[: -len(".yaml")]


def load_actions():
    """Parse the actions/ folders into entries (read fresh).

    One action per `.yaml` file (name from its `name:` key or the file name).
    Returns [{"name": ..., "steps": [...], "after_success": [...]}]; entries with
    neither steps nor after_success are dropped. The shipped app/actions/ folder
    is read first, the user's <home>/actions/ second (it wins on a name clash).
    """
    merged = {}
    for source, dirpath in (("shipped", ACTIONS_DIR), ("user", USER_ACTIONS_DIR)):
        for path in _action_files(dirpath):
            data = _parse_action_file(_read_text(path))
            name = _action_name(path, data["name"])
            if not name:
                continue
            if data["steps"] or data["after_success"]:
                merged[name] = {
                    "name": name,
                    "steps": data["steps"],
                    "after_success": data["after_success"],
                    "api_version": data["api_version"],
                    "source": source,
                    "path": path,
                }
    return list(merged.values())


def _hook_event(path, data):
    """The event a hook file fires: `on_<event>.yaml` first, then `event_name:`.

    Returns None when neither the file name nor the `event_name:` key names a
    known app event.
    """
    fname = os.path.basename(path)
    stem = fname[: -len(".yaml")]
    if is_hook_name(stem):
        event = stem[len(HOOK_PREFIX):]
        if event in HOOK_EVENTS:
            return event
    key_event = (data.get("event_name") or "").strip()
    if key_event in HOOK_EVENTS:
        return key_event
    return None


def load_hooks():
    """Parse the hooks/ directory into (hooks, errors) (read fresh).

    One hook per `.yaml` file; its name is the canonical `on_<event>` and the
    event comes from the file name or the `event_name:` key. `active: false`
    hooks are skipped. Templates (files with neither `steps` nor
    `after_success`, e.g. hooks/example.yaml) are ignored silently; a file that
    does define steps but names no known event is reported in `errors`. The
    shipped app/hooks/ folder is read first, the user's <home>/hooks/ second (it
    wins on an event clash).
    """
    merged = {}
    errors = []
    for source, dirpath in (("shipped", HOOKS_DIR), ("user", USER_HOOKS_DIR)):
        for path in _action_files(dirpath):
            data = _parse_action_file(_read_text(path))
            event = _hook_event(path, data)
            has_body = bool(data["steps"] or data["after_success"])
            if event is None:
                if has_body:
                    errors.append(
                        f"'hooks/{os.path.basename(path)}': no app event — name it "
                        f"on_<event>.yaml or set event_name: (known: "
                        f"{', '.join(HOOK_EVENTS)})"
                    )
                continue
            if not data["active"] or not has_body:
                continue
            name = HOOK_PREFIX + event
            merged[name] = {
                "name": name,
                "event": event,
                "steps": data["steps"],
                "after_success": data["after_success"],
                "api_version": data["api_version"],
                "source": source,
                "path": path,
            }
    return list(merged.values()), errors


def build_command(template, values):
    """Replace only the placeholders present in `template` with shell-quoted paths."""
    cmd = template
    for key, val in values.items():
        cmd = cmd.replace("{" + key + "}", shlex.quote(val))
    return cmd


def create_pipe():
    """Create an empty per-run pipe file; return its path (None when it fails).

    The file backs the `{PIPE_PATH}` placeholder: every step of a run (and the
    actions in its `after_success` chain) can read/write it to pass data on.
    """
    try:
        os.makedirs(PIPE_DIR, exist_ok=True)
        fd, path = tempfile.mkstemp(prefix="pipe_", suffix=".txt", dir=PIPE_DIR)
    except OSError:
        return None
    os.close(fd)
    return path


def is_pipe_path(path):
    """True when `path` is a pipe file the app may delete.

    Only paths inside PIPE_DIR qualify, so a stray path can never make the app
    remove an unrelated file.
    """
    if not path:
        return False
    base = os.path.abspath(PIPE_DIR)
    target = os.path.abspath(path)
    try:
        return os.path.commonpath([base, target]) == base
    except ValueError:
        return False


def remove_pipe(path):
    """Delete a pipe file; ignore a missing/mismatched one."""
    if not is_pipe_path(path):
        return False
    try:
        os.remove(path)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# action executions: `steps` and `after_success` form one ordered queue of
# server commands and server/frontend actions. The backend runs it until it
# reaches a frontend (app_*) entry, which it hands to the UI by execution uid;
# the client runs it and calls back to resume. The backend owns the whole run,
# including its {PIPE_PATH} file.
# --------------------------------------------------------------------------- #
def _subprocess_env():
    """Environment handed to every command/filter: the resolved user paths."""
    env = os.environ.copy()
    env["YBE_HOME"] = YBX_HOME
    env["YBE_APP_DIR"] = BASE_DIR
    env["YBE_APP_SCRIPT_DIR"] = APP_SCRIPT_DIR
    env["YBE_USER_SCRIPT_DIR"] = USER_SCRIPT_DIR
    return env


def _run_command(state, command):
    """Run one shell command, accumulating output in `state`.

    Returns "ok", "failed", "timeout" or "error"; `state["exit_code"]` holds the
    failing command's code on "failed". Runs with cwd=YBX_HOME (logged), so
    relative paths land in the user folder (`scripts/…` is yours); reach shipped
    helpers with {APP_DIR}/scripts/… explicitly.
    """
    print(f"[ybe] command: cwd={YBX_HOME} cmd={command}", file=sys.stderr)
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=ACTION_TIMEOUT,
            cwd=YBX_HOME,
            env=_subprocess_env(),
        )
    except subprocess.TimeoutExpired:
        state["stderr"].append(f"$ {command}\ntimed out")
        return "timeout"
    except OSError as exc:
        state["stderr"].append(f"$ {command}\n{exc}")
        return "error"
    state["commands"].append(command)
    if proc.stdout.strip():
        state["stdout"].append(f"$ {command}\n{proc.stdout.rstrip()}")
    if proc.stderr.strip():
        state["stderr"].append(f"$ {command}\n{proc.stderr.rstrip()}")
    if proc.returncode != 0:
        state["exit_code"] = proc.returncode
        return "failed"
    return "ok"


def _resolve_entry(entry, actions_by_name):
    """Resolve one `steps` / `after_success` entry into a work-queue item.

    Both lists share one syntax:
      - an `app_*` app action          -> ("app", name)     run in the UI
      - a `backend_*` built-in action  -> ("backend", name) run inline
      - `action_<Name>` known action   -> ("action", dict)  run inline
      - anything else                  -> ("cmd", entry)    shell command
    An unknown `app_*`, `backend_*` or `action_*` name becomes a
    ("bad", message) item.
    """
    if entry in APP_ACTIONS:
        return ("app", entry)
    if entry.startswith("app_"):
        return ("bad", f"unknown app action: {entry}")
    if entry in BACKEND_ACTION_NAMES:
        return ("backend", entry)
    if entry.startswith("backend_"):
        return ("bad", f"unknown backend action: {entry}")
    if entry.startswith(ACTION_REF_PREFIX):
        name = entry[len(ACTION_REF_PREFIX):]
        if name in actions_by_name:
            return ("action", actions_by_name[name])
        return ("bad", f"unknown action: {name}")
    return ("cmd", entry)


def _action_items(action):
    """Expand an action into its ordered work-queue items (steps, then after_success).

    An `action_<Name>` reference to an action disabled for this dataset does not
    resolve, matching the toolbar (there is no way to run a disabled action).
    """
    disabled = _disabled_extensions()["action"]
    actions_by_name = {
        a["name"]: a for a in load_actions() if a["name"] not in disabled
    }
    entries = list(action.get("steps") or []) + list(action.get("after_success") or [])
    return [_resolve_entry(entry, actions_by_name) for entry in entries]


def _advance_execution(state):
    """Process the queue until a frontend action is reached or the run ends.

    Returns (status, detail):
        ("client", name)  the named app action must run in the UI next
        ("done", None)    the whole chain finished successfully
        ("failed", None)  a command failed (see state["exit_code"])
        ("timeout", None) a command timed out
        ("error", msg)    an unknown action / bad after_success / cascade limit
    """
    while state["queue"]:
        kind, value = state["queue"].pop(0)
        if kind == "app":  # frontend action: pause for the client
            return "client", value
        if kind == "bad":
            return "error", value
        if kind == "action":
            state["runs"] += 1
            if state["runs"] > MAX_CASCADE_DEPTH:
                return "error", f"action cascade exceeded {MAX_CASCADE_DEPTH} levels"
            state["queue"][0:0] = _action_items(value)
            continue
        if kind == "backend":
            error = BACKEND_ACTIONS[value]()
            if error:
                return "error", error
            continue
        status = _run_command(state, build_command(value, state["values"]))
        if status != "ok":
            return status, None
    return "done", None


def begin_execution(action, action_name, values, pipe_path):
    """Start a run: queue the action's steps + after_success, then advance it.

    Returns (state, status, detail) as `_advance_execution` does.
    """
    state = {
        "action": action_name,
        "values": values,
        "pipe_path": pipe_path,
        "cwd": YBX_HOME,
        "queue": _action_items(action),
        "stdout": [],
        "stderr": [],
        "commands": [],
        "exit_code": 0,
        "runs": 1,
    }
    status, detail = _advance_execution(state)
    return state, status, detail


def finish_execution(state):
    """Delete the run's pipe file (unless --keep-pipe) and forget the run."""
    uid = state.get("uid")
    if uid:
        EXECUTIONS.pop(uid, None)
    if not STATE["keep_pipe"]:
        remove_pipe(state.get("pipe_path"))


def load_shortcuts_from(path):
    """Parse one shortcuts.txt file into {name: {shortcut, label}} (read fresh)."""
    shortcuts = {}
    for raw in _read_text_lines(path):
        parsed = parse_shortcut_line(raw)
        if parsed is None:
            continue
        name, shortcut, label = parsed
        shortcuts[name] = {"shortcut": shortcut, "label": label}
    return shortcuts


def load_shortcuts():
    """Parse the shipped + user shortcuts.txt into {name: {shortcut, label}} (read fresh)."""
    shortcuts = load_shortcuts_from(SHORTCUTS_FILE)
    shortcuts.update(load_shortcuts_from(USER_SHORTCUTS_FILE))
    return shortcuts


def user_shortcut_names():
    """Names the user's shortcuts.txt overrides (read fresh)."""
    return set(load_shortcuts_from(USER_SHORTCUTS_FILE))


def _valid_shortcut(value):
    """A storable shortcut token, or None when it cannot be written safely."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or any(ch in value for ch in "<>\r\n"):
        return None
    return value


def write_user_shortcuts(sets, resets):
    """Upsert/remove shortcut overrides in the user shortcuts.txt.

    `sets` maps name -> shortcut; `resets` is an iterable of names whose override
    line is dropped (falling back to the shipped binding). Comments, blank lines
    and untouched entries are preserved. Returns the file path.
    """
    sets = dict(sets or {})
    resets = set(resets or [])
    merged = load_shortcuts()
    lines = _read_text(USER_SHORTCUTS_FILE).splitlines()

    out, written = [], set()
    for raw in lines:
        parsed = parse_shortcut_line(raw)
        if parsed is None:
            out.append(raw)
            continue
        name, _shortcut, label = parsed
        if name in resets:
            continue
        if name in sets:
            out.append(f"{name} <{sets[name]}> {label}".rstrip())
            written.add(name)
            continue
        out.append(raw)
    for name, shortcut in sets.items():
        if name in written:
            continue
        label = (merged.get(name) or {}).get("label", "")
        out.append(f"{name} <{shortcut}> {label}".rstrip())

    text = "\n".join(out)
    if text:
        text += "\n"
    os.makedirs(os.path.dirname(USER_SHORTCUTS_FILE) or ".", exist_ok=True)
    with open(USER_SHORTCUTS_FILE, "w", encoding="utf-8") as f:
        f.write(text)
    return USER_SHORTCUTS_FILE


def split_shortcuts(shortcuts):
    """Split raw shortcuts into (app, user) maps, collecting unknown names as errors."""
    user_names = {a["name"] for a in load_actions()}
    hook_names = {h["name"] for h in load_hooks()[0]}
    app, user, errors = {}, {}, []
    for name, info in shortcuts.items():
        if name in APP_ACTIONS:
            app[name] = info
        elif name in hook_names:
            errors.append(
                f"'shortcuts.txt': '{name}' is an event hook; hooks cannot be bound"
            )
        elif name in user_names:
            user[name] = info
        else:
            errors.append(
                f"'shortcuts.txt': unknown action '{name}' "
                f"(not an app action and not defined in the actions/ folder)"
            )
    return app, user, errors


# --------------------------------------------------------------------------- #
# filters/ (one YAML file per filter; narrows the loaded image list)
# --------------------------------------------------------------------------- #
# Placeholders a filter argument may never shadow (defined by the app).
FILTER_RESERVED_PLACEHOLDERS = {
    "DATASET_PATH",
    "DATA_YAML_PATH",
    "APP_DIR",
    "HOME_DIR",
    "APP_SCRIPT_DIR",
    "USER_SCRIPT_DIR",
    "PYTHON",
    "SPLIT",
    "INPUT_PIPE",
    "OUTPUT_PIPE",
}
# A filter argument name; its in-place placeholder is the upper-cased name.
_FILTER_ARG_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Dynamic option token: expands to the loaded dataset's class names.
FILTER_CLASS_NAMES_TOKEN = "{DATASET_CLASS_NAMES}"


def resolve_filter_options(options, classes):
    """Expand dynamic option tokens (e.g. `{DATASET_CLASS_NAMES}`).

    Non-token options are kept as-is; a token expands in place (deduplicated).
    Used both to fill the UI dropdown and to validate a submitted value.
    """
    if not options:
        return options
    resolved = []
    for opt in options:
        values = classes if opt == FILTER_CLASS_NAMES_TOKEN else [opt]
        for value in values:
            if value and value not in resolved:
                resolved.append(value)
    return resolved


def _set_filter_arg_field(arg, key, value):
    """Set one argument field; return True while a block `options:` list may follow."""
    value = _strip_comment(value)
    if key == "name":
        arg["name"] = _yaml_scalar(value)
    elif key == "required":
        arg["required"] = value.lower() not in ("false", "no", "0", "")
    elif key == "default":
        arg["default"] = _yaml_scalar(value) if value else None
    elif key == "options":
        if value.startswith("["):
            arg["options"] = _parse_yaml_names_value(value)
        elif value:
            arg["options"] = [_yaml_scalar(p) for p in value.split(",") if p.strip()]
        else:
            arg["options"] = []
            return True
    return False


def _parse_filter_file(text):
    """Parse one filter YAML file into a dict of its keys.

    Format (2-space indentation, whole-line # comments):
        name: Keep every N-th   # optional; the file name is used otherwise
        description: ...        # optional
        active: true            # optional; false hides the filter
        arguments:              # optional list of dicts
          - name: every         # -> the in-place placeholder {EVERY}
            required: false
            default: "2"
            options: ["2", "3"]  # inline list, or a block of `- item` lines
        steps:                  # one shell command per entry
          - python {APP_SCRIPT_DIR}/x.py ... {EVERY}
    `steps` may also be a single value on the key line.
    """
    data = {"name": None, "description": None, "active": True,
            "api_version": None, "arguments": [], "steps": []}
    mode, current, arg_indent, options_pending = None, None, None, False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0 and ":" in stripped:
            key, _, value = stripped.partition(":")
            key, value = key.strip(), value.strip()
            mode, current, arg_indent, options_pending = None, None, None, False
            if key == "name":
                if value:
                    data["name"] = _yaml_scalar(value)
            elif key == "api_version":
                data["api_version"] = _parse_api_version(value)
            elif key == "description":
                if value:
                    data["description"] = _yaml_scalar(value)
            elif key == "active":
                if value:
                    data["active"] = value.lower() not in ("false", "no", "0")
            elif key == "arguments":
                mode = "arguments"
            elif key == "steps":
                mode = "steps"
                if value and value != "[]":
                    data["steps"].append(_yaml_scalar(value))
            continue
        if mode == "steps":
            if stripped.startswith("- "):
                data["steps"].append(_yaml_scalar(stripped[2:].strip()))
        elif mode == "arguments":
            if stripped.startswith("- ") and (arg_indent is None or indent <= arg_indent):
                if arg_indent is None:
                    arg_indent = indent
                current = {"name": None, "required": False,
                           "default": None, "options": None}
                data["arguments"].append(current)
                options_pending = False
                rest = stripped[2:].strip()
                if ":" in rest:
                    field, _, value = rest.partition(":")
                    options_pending = _set_filter_arg_field(current, field.strip(), value.strip())
            elif current is not None:
                if options_pending and stripped.startswith("- "):
                    current["options"].append(_yaml_scalar(stripped[2:].strip()))
                elif ":" in stripped:
                    field, _, value = stripped.partition(":")
                    options_pending = _set_filter_arg_field(current, field.strip(), value.strip())
    return data


def _validate_filter_arguments(fname, filter_name, raw_args):
    """Normalize a filter's `arguments`; return (arguments, errors).

    An invalid name or a collision with a reserved placeholder drops the whole
    filter: the caller reports every error and skips it.
    """
    arguments, errors, seen = [], [], set()
    for raw in raw_args:
        arg_name = (raw.get("name") or "").strip()
        if not arg_name:
            errors.append(f"'filters/{fname}': filter \"{filter_name}\": an argument has no name")
            return [], errors
        if not _FILTER_ARG_NAME_RE.match(arg_name):
            errors.append(
                f"'filters/{fname}': filter \"{filter_name}\": invalid argument name "
                f"\"{arg_name}\" (letters, digits and _ only; cannot start with a digit)")
            return [], errors
        if arg_name.upper() in FILTER_RESERVED_PLACEHOLDERS:
            errors.append(
                f"'filters/{fname}': filter \"{filter_name}\": argument \"{arg_name}\" "
                f"collides with the reserved placeholder {{{arg_name.upper()}}}")
            return [], errors
        if arg_name in seen:
            errors.append(
                f"'filters/{fname}': filter \"{filter_name}\": duplicate argument \"{arg_name}\"")
            return [], errors
        seen.add(arg_name)
        arguments.append({
            "name": arg_name,
            "required": bool(raw.get("required")),
            "default": raw.get("default"),
            "options": raw.get("options"),
        })
    return arguments, errors


def _filter_files(dirpath):
    """Sorted `.yaml` paths in `dirpath`."""
    if not os.path.isdir(dirpath):
        return []
    paths = []
    for fname in sorted(os.listdir(dirpath)):
        if not fname.endswith(".yaml"):
            continue
        path = os.path.join(dirpath, fname)
        if os.path.isfile(path):
            paths.append(path)
    return paths


def load_filters():
    """Parse the filters/ folders into (filters, errors) (read fresh).

    One filter per `.yaml` file; its name is the `name:` key, else the file name.
    `active: false` and files with no `steps` are skipped. An argument that is
    invalid or shadows a reserved placeholder drops the filter and is reported in
    `errors`. The shipped app/filters/ folder is read first, the user's
    <home>/filters/ second (it wins on a name clash).
    """
    merged, errors = {}, []
    for source, dirpath in (("shipped", FILTERS_DIR), ("user", USER_FILTERS_DIR)):
        for path in _filter_files(dirpath):
            data = _parse_filter_file(_read_text(path))
            fname = os.path.basename(path)
            name = (data["name"] or "").strip() or fname[: -len(".yaml")]
            if not name or not data["active"] or not data["steps"]:
                continue
            arguments, arg_errors = _validate_filter_arguments(fname, name, data["arguments"])
            if arg_errors:
                errors.extend(arg_errors)
                continue
            merged[name] = {
                "name": name,
                "description": (data["description"] or "").strip(),
                "arguments": arguments,
                "steps": data["steps"],
                "api_version": data["api_version"],
                "source": source,
                "path": path,
            }
    return merged, errors


# --------------------------------------------------------------------------- #
# extension authoring (Settings > Actions / Hooks / Filters)
#
# The web editor writes user YAML in exactly the shape the parsers above read.
# A small hand-written writer is used (no PyYAML) so the runtime dependency stays
# Flask only; `_dump_action_file` / `_dump_filter_file` round-trip through
# `_parse_action_file` / `_parse_filter_file` (covered by tests).
# --------------------------------------------------------------------------- #
_EXTENSION_BAD_FILENAME = set('/\\<>:"|?*')
_EXTENSION_RESERVED_PREFIXES = ("app_", "backend_", "action_", "on_")


def _safe_extension_name(name):
    """A file-stem for a user action/filter name, or None when unsafe.

    Allows spaces, letters, digits, `.`, `_` and `-`; rejects path separators,
    control characters, the reserved action prefixes and a leading dot.
    """
    if not isinstance(name, str):
        return None
    name = name.strip()
    if not name or name in (".", "..") or len(name) > 80:
        return None
    if name.startswith(".") or name.startswith(_EXTENSION_RESERVED_PREFIXES):
        return None
    if any(ch in _EXTENSION_BAD_FILENAME or ord(ch) < 32 for ch in name):
        return None
    return name


def _yaml_quote(value):
    """Wrap a scalar in double quotes (round-trips through `_yaml_scalar`)."""
    return '"' + value + '"'


def _clean_extension_entries(raw):
    """Validate a `steps` / `after_success` list -> (entries, error).

    Each entry is a non-empty single-line string, stored verbatim (a shell
    command or an action reference).
    """
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, "steps must be a list"
    entries = []
    for item in raw:
        if not isinstance(item, str):
            return None, "each step must be text"
        text = item.strip()
        if not text:
            continue
        if any(ord(ch) < 32 for ch in text):
            return None, "a step contains a newline or control character"
        entries.append(text)
    return entries, None


def _clean_filter_arguments(raw):
    """Validate submitted filter arguments -> (arguments, error)."""
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, "arguments must be a list"
    cleaned, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            return None, "each argument must be an object"
        name = str(item.get("name") or "").strip()
        if not name:
            return None, "every argument needs a name"
        if not _FILTER_ARG_NAME_RE.match(name):
            return None, (
                f'invalid argument name "{name}" (letters, digits and _ only; '
                "cannot start with a digit)")
        if name.upper() in FILTER_RESERVED_PLACEHOLDERS:
            return None, f'argument "{name}" collides with {{{name.upper()}}}'
        if name in seen:
            return None, f'duplicate argument "{name}"'
        seen.add(name)
        default = item.get("default")
        if default is not None:
            default = str(default)
            if any(ord(ch) < 32 for ch in default) or "#" in default:
                return None, f'argument "{name}": default cannot contain # or newlines'
            if default == "":
                default = None
        options = item.get("options")
        if options is not None:
            if not isinstance(options, list):
                return None, f'argument "{name}": options must be a list'
            clean_options = []
            for opt in options:
                opt = str(opt).strip()
                if not opt:
                    continue
                if "," in opt or "#" in opt or any(ord(ch) < 32 for ch in opt):
                    return None, (
                        f'argument "{name}": an option cannot contain , # or newlines')
                if opt not in clean_options:
                    clean_options.append(opt)
            options = clean_options or None
        cleaned.append({
            "name": name,
            "required": bool(item.get("required")),
            "default": default,
            "options": options,
        })
    return cleaned, None


def _dump_action_file(steps, after_success, active=True,
                      api_version=EXTENSION_API_VERSION):
    """Serialize a `steps`/`after_success` file in the parser's own format."""
    lines = [f"api_version: {api_version}"]
    if not active:
        lines.append("active: false")
    for key, entries in (("steps", steps), ("after_success", after_success)):
        if entries:
            lines.append(f"{key}:")
            lines.extend("  - " + entry for entry in entries)
    return "\n".join(lines) + "\n"


def _dump_filter_file(description, active, arguments, steps,
                      api_version=EXTENSION_API_VERSION):
    """Serialize a filter file in the parser's own format."""
    lines = [f"api_version: {api_version}"]
    if description:
        lines.append("description: " + _yaml_quote(description))
    if not active:
        lines.append("active: false")
    if arguments:
        lines.append("arguments:")
        for arg in arguments:
            lines.append("  - name: " + arg["name"])
            if arg.get("required"):
                lines.append("    required: true")
            default = arg.get("default")
            if default is not None and str(default) != "":
                lines.append("    default: " + _yaml_quote(str(default)))
            options = arg.get("options")
            if options:
                rendered = ", ".join(_yaml_quote(str(o)) for o in options)
                lines.append(f"    options: [{rendered}]")
    if steps:
        lines.append("steps:")
        lines.extend("  - " + entry for entry in steps)
    return "\n".join(lines) + "\n"


def _bump_api_version_text(text, version=EXTENSION_API_VERSION):
    """Return `text` with its top-level `api_version:` set to `version`.

    Comments and every other line are preserved; when the key is absent it is
    inserted after the leading comment/blank block.
    """
    lines = text.splitlines()
    pattern = re.compile(r"^api_version\s*:")
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f"api_version: {version}"
            return "\n".join(lines) + "\n"
    insert_at = 0
    while insert_at < len(lines):
        stripped = lines[insert_at].strip()
        if stripped and not stripped.startswith("#"):
            break
        insert_at += 1
    lines.insert(insert_at, f"api_version: {version}")
    return "\n".join(lines) + "\n"


def _parse_extension_text(kind, text):
    """Parse raw editor text with the parser for `kind`."""
    if kind in ("action", "hook"):
        return _parse_action_file(text)
    return _parse_filter_file(text)


def _extension_user_dir(kind):
    """The user folder a kind is written to (None for an unknown kind)."""
    return {
        "action": USER_ACTIONS_DIR,
        "hook": USER_HOOKS_DIR,
        "filter": USER_FILTERS_DIR,
    }.get(kind)


def extension_file_for(kind, name):
    """Resolve a loaded extension to its winning file, or None.

    Returns `{kind, name, path, source, api_version}`; `source` is "shipped" or
    "user". Only extensions the loaders accept (with a body) are resolvable.
    """
    entry = None
    if kind == "action":
        entry = next((a for a in load_actions() if a["name"] == name), None)
    elif kind == "hook":
        entry = next((h for h in load_hooks()[0] if h["name"] == name), None)
    elif kind == "filter":
        entry = load_filters()[0].get(name)
    if entry is None:
        return None
    return {
        "kind": kind,
        "name": name,
        "path": entry["path"],
        "source": entry["source"],
        "api_version": entry.get("api_version"),
    }


def _extension_file_payload(found, text):
    """The UI shape for the raw YAML editor."""
    return {
        "ok": True,
        "kind": found["kind"],
        "name": found["name"],
        "source": found["source"],
        "path": found["path"],
        "api_version": found["api_version"],
        "status": api_version_status(found["api_version"]),
        "writable": found["source"] == "user" and not STATE["readonly"],
        "text": text,
    }



def _entry_path(entry):
    """Absolute path of a scanned `{split, name}` entry (or None)."""
    split = _split_by_name(entry["split"])
    if split is None:
        return None
    return os.path.abspath(os.path.join(split["images_dir"], entry["name"]))


def _known_image_paths():
    """Map every scanned image's absolute path to its `{split, name}` entry."""
    known = {}
    for entry in STATE["images"]:
        path = _entry_path(entry)
        if path:
            known[path] = entry
    return known


def _write_filter_input(path, entries):
    """Write one absolute image path per line (a filter's input pipe)."""
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            abs_path = _entry_path(entry)
            if abs_path:
                f.write(abs_path + "\n")


def _parse_filter_output(text, known):
    """Map absolute image paths to entries, keeping only known images.

    Order is preserved and duplicates dropped. Returns (entries, skipped),
    where `skipped` counts non-blank lines that map to no scanned image.
    """
    entries, seen, skipped = [], set(), 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        entry = known.get(os.path.abspath(line))
        if entry is None:
            skipped += 1
            continue
        pair = (entry["split"], entry["name"])
        if pair in seen:
            continue
        seen.add(pair)
        entries.append(entry)
    return entries, skipped


def _read_filter_output(path, known):
    """Read a filter's output pipe; missing/unreadable means an empty result."""
    try:
        with open(path, encoding="utf-8") as f:
            return _parse_filter_output(f.read(), known)
    except OSError:
        return [], 0


def effective_filter_arguments(flt, arguments):
    """The filter's arguments as `{name: value}`, user values over defaults.

    Every declared argument gets a value (its default when none was given); a
    missing default becomes an empty string.
    """
    provided = arguments if isinstance(arguments, dict) else {}
    effective = {}
    for arg in flt["arguments"]:
        value = provided.get(arg["name"])
        if value is None or (isinstance(value, str) and not value.strip()):
            value = arg.get("default")
        effective[arg["name"]] = "" if value is None else str(value)
    return effective


def _filter_placeholder_values(flt, data_yaml, split, input_pipe, output_pipe, arguments):
    """Substitution values for a filter's steps (shared paths + pipes + args)."""
    values = {
        "DATASET_PATH": STATE["dataset_path"] or "",
        "DATA_YAML_PATH": data_yaml or "",
        "APP_DIR": BASE_DIR,
        "HOME_DIR": YBX_HOME,
        "APP_SCRIPT_DIR": APP_SCRIPT_DIR,
        "USER_SCRIPT_DIR": USER_SCRIPT_DIR,
        "PYTHON": sys.executable,
        "SPLIT": split or "",
        "INPUT_PIPE": input_pipe,
        "OUTPUT_PIPE": output_pipe,
    }
    effective = effective_filter_arguments(flt, arguments)
    for arg in flt["arguments"]:
        key = arg["name"].upper()
        if key not in values:
            values[key] = effective.get(arg["name"], "")
    return values


def run_filter(name, data_yaml, split, input_pipe, output_pipe, arguments=None,
               filters=None):
    """Run filter `name` once; return {ok, error}.

    Every `steps` entry is a shell command; the app substitutes the shared
    placeholders, the pipe paths and each argument (as `{<NAME>}`) before it
    runs. The filter reads candidate image paths from `input_pipe` and writes the
    kept ones to `output_pipe`; the caller validates the output.
    """
    if filters is None:
        filters = load_filters()[0]
    flt = filters.get(name)
    if flt is None:
        return {"ok": False, "error": f"unknown filter: {name}"}

    values = _filter_placeholder_values(flt, data_yaml, split, input_pipe, output_pipe, arguments)
    for step in flt["steps"]:
        command = build_command(step, values)
        print(f"[ybe] filter: cwd={YBX_HOME} cmd={command}", file=sys.stderr)
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=FILTER_TIMEOUT,
                cwd=YBX_HOME,
                env=_subprocess_env(),
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "filter timed out"}
        except OSError as exc:
            return {"ok": False, "error": f"could not run filter: {exc}"}
        if proc.returncode != 0:
            detail = proc.stderr.strip() or f"exit code {proc.returncode}"
            return {"ok": False, "error": detail}
    return {"ok": True}


def _normalize_filter_chain(items):
    """Validate an active filter chain; return (chain, error).

    `items` may be strings (legacy) or `{name, arguments}` dicts. The returned
    chain fills each argument with its value/default and checks `required`.
    """
    filters, _ = load_filters()
    chain = []
    for item in items or []:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            return None, "invalid filter entry"
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        flt = filters.get(name)
        if flt is None:
            return None, f"unknown filter: {name}"
        effective = effective_filter_arguments(flt, item.get("arguments"))
        for arg in flt["arguments"]:
            value = effective.get(arg["name"], "")
            if arg["required"] and not value.strip():
                return None, f'Filter "{name}": argument "{arg["name"]}" is required'
            options = resolve_filter_options(arg.get("options"), read_classes())
            if options and value and value not in options:
                return None, (
                    f'Filter "{name}": argument "{arg["name"]}" must be one of: '
                    f'{", ".join(options)}')
        chain.append({"name": name, "arguments": effective})
    return chain, None


def run_filter_chain(chain, split):
    """Run `chain` in order, piping each result into the next.

    Each item is `{name, arguments}`. `split` selects the first filter's input
    (its images, or every scanned image when it is empty/"All"). Returns
    {ok, images, skipped, error, chain_dir}; `chain_dir` is the scratch directory
    (kept only with --keep-filter-pipes).
    """
    known = _known_image_paths()
    if not chain:
        return {"ok": True, "images": [], "skipped": 0, "error": None,
                "chain_dir": None}

    try:
        os.makedirs(FILTER_PIPES_DIR, exist_ok=True)
        chain_dir = tempfile.mkdtemp(prefix="chain_", dir=FILTER_PIPES_DIR)
    except OSError as exc:
        return {"ok": False, "error": f"could not create filter pipes: {exc}",
                "chain_dir": None}

    filters, _ = load_filters()
    initial = [e for e in STATE["images"] if e["split"] == split] if split \
        else STATE["images"]
    in_path = os.path.join(chain_dir, "input_0.txt")
    _write_filter_input(in_path, initial)

    entries, skipped, error = initial, 0, None
    for i, item in enumerate(chain):
        out_path = os.path.join(chain_dir, f"output_{i}.txt")
        result = run_filter(item["name"], STATE["data_yaml"], split, in_path,
                            out_path, item.get("arguments"), filters)
        if not result["ok"]:
            error = f'Filter "{item["name"]}" failed: {result["error"]}'
            entries = None
            break
        entries, skipped = _read_filter_output(out_path, known)
        in_path = out_path

    if not STATE["keep_filter_pipes"]:
        shutil.rmtree(chain_dir, ignore_errors=True)
        chain_dir = None

    if error:
        return {"ok": False, "error": error, "chain_dir": chain_dir}
    return {"ok": True, "images": entries, "skipped": skipped, "error": None,
            "chain_dir": chain_dir}


def _clear_filter():
    STATE["active_filters"] = []
    STATE["filter_images"] = None
    STATE["filter_error"] = None


def apply_filters(items):
    """Run the filter chain for the current split and cache it in STATE.

    `items` is a list of `{name, arguments}` (strings are accepted as legacy;
    [] clears). Returns an error message on failure (state untouched), or None on
    success.
    """
    chain, error = _normalize_filter_chain(items)
    if error:
        return error
    if not chain:
        _clear_filter()
        return None
    result = run_filter_chain(chain, STATE["active_split"])
    if not result["ok"]:
        return result["error"]
    STATE["active_filters"] = chain
    STATE["filter_images"] = result["images"]
    if STATE["keep_filter_pipes"] and result["chain_dir"]:
        print(f"[ybe] kept filter pipes: {result['chain_dir']}", file=sys.stderr)
    STATE["filter_error"] = (
        f"{result['skipped']} filter line(s) ignored" if result["skipped"] else None
    )
    return None


def _replace_images_segment(images_dir, component):
    """Replace the last `images` path segment with `component` (labels/tags)."""
    parts = images_dir.replace("\\", "/").rstrip("/").split("/")
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "images":
            parts[i] = component
            return "/".join(parts)
    # fallback: sibling `component` folder next to the images dir
    return os.path.normpath(os.path.join(images_dir, "..", component, os.path.basename(images_dir)))


def _labels_dir_for(images_dir):
    """Derive the labels dir by replacing the last `images` segment with `labels`."""
    return _replace_images_segment(images_dir, "labels")


def _tags_dir_for(images_dir, split_name=None):
    """The tags dir: the per-dataset override, else `images` -> `tags`.

    An override is a base folder; each split keeps its own subfolder
    (`<override>/<split>`), matching the default `tags/<split>` layout.
    """
    override = STATE.get("tags_dir")
    if override:
        return os.path.join(override, split_name) if split_name else override
    return _replace_images_segment(images_dir, "tags")


def scan_splits():
    """Parse data.yaml and build the list of {name, images_dir, labels_dir} splits."""
    splits = []
    if not STATE["data_yaml"] or not os.path.isfile(STATE["data_yaml"]):
        return splits

    data = _parse_data_yaml(STATE["data_yaml"])
    data_yaml_dir = os.path.dirname(os.path.abspath(STATE["data_yaml"]))

    base = data.get("path") or data_yaml_dir
    if not os.path.isabs(base):
        base = os.path.normpath(os.path.join(data_yaml_dir, base))
    STATE["dataset_path"] = os.path.abspath(base)
    STATE["classes"] = data.get("names") or []

    for key in ("train", "val", "test"):
        rel = data.get(key)
        if not rel:
            continue
        images_dir = rel if os.path.isabs(rel) else os.path.join(STATE["dataset_path"], rel)
        images_dir = os.path.normpath(images_dir)
        if not os.path.isdir(images_dir):
            continue
        splits.append(
            {
                "name": key,
                "images_dir": images_dir,
                "labels_dir": _labels_dir_for(images_dir),
                "tags_dir": _tags_dir_for(images_dir, key),
            }
        )
    return splits


def scan_images():
    flat = []
    for split in STATE["splits"]:
        d = split["images_dir"]
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if os.path.isfile(os.path.join(d, f)) and is_image(f):
                flat.append({"split": split["name"], "name": f})
    return flat


def _load_dataset(path):
    """Activate the dataset at `path` in STATE. True when it has usable splits."""
    STATE["data_yaml"] = os.path.abspath(path)
    STATE["splits"] = scan_splits()
    STATE["images"] = scan_images()
    return bool(STATE["splits"])


def _resume_last_dataset():
    """Activate the most recent still-existing data.yaml; None when there is none.

    Used at startup when `--data` is omitted, so a plain `python app.py` returns
    to the dataset last opened (the newest entry of `.recent_data_yamls.json`).
    """
    for path in _load_recent():
        if os.path.isfile(path) and _load_dataset(path):
            _restore_view(STATE["data_yaml"])
            return path
    STATE["data_yaml"] = None
    STATE["splits"] = []
    STATE["images"] = []
    return None


def _current_images():
    """The images visible to the UI.

    A filter chain narrows the list to its own result (the chain's first filter
    already received the active split as its input); otherwise the list is
    filtered to the active split.
    """
    if STATE["active_filters"]:
        return STATE["filter_images"] or []
    if not STATE["active_split"]:
        return STATE["images"]
    return [e for e in STATE["images"] if e["split"] == STATE["active_split"]]


def _rescan_images():
    """Re-scan the image folders and re-apply the active filter in place.

    Used by `POST /api/images/rescan` (an explicit refresh) and by the
    `backend_rescan_images` action entry. The flat list is rebuilt and a filter
    that depends on the files (e.g. tags) is re-run; an active split that no
    longer has any image is cleared.
    """
    STATE["images"] = scan_images()
    if STATE["active_split"] and not any(
        e["split"] == STATE["active_split"] for e in STATE["images"]
    ):
        STATE["active_split"] = None
    # the flat list changed: an active filter chain must be re-evaluated
    if STATE["active_filters"]:
        error = apply_filters(STATE["active_filters"])
        if error:
            _clear_filter()
            STATE["filter_error"] = error


# Server-side built-in action callables (see BACKEND_ACTION_NAMES). Each returns
# None on success or an error message that stops the run.
BACKEND_ACTIONS = {
    "backend_rescan_images": _rescan_images,
}


def _split_by_name(name):
    for s in STATE["splits"]:
        if s["name"] == name:
            return s
    return None


def label_path(entry):
    split = _split_by_name(entry["split"])
    if split is None:
        return None
    stem = os.path.splitext(entry["name"])[0]
    return os.path.join(split["labels_dir"], stem + ".txt")


def tag_path(entry):
    """Per-image tag file: same stem as the image, stored under the split's tags dir."""
    split = _split_by_name(entry["split"])
    if split is None:
        return None
    stem = os.path.splitext(entry["name"])[0]
    return os.path.join(split["tags_dir"], stem + ".txt")


def tags_yaml_path():
    """Path of the dataset's tags.yaml (beside data.yaml), or None."""
    if not STATE["data_yaml"]:
        return None
    return os.path.join(os.path.dirname(os.path.abspath(STATE["data_yaml"])), "tags.yaml")


def read_tags_yaml():
    """Read the available-tags list from the dataset's tags.yaml ([] if absent).

    The list is a bare YAML list; a nested `tags:` key is ignored.
    """
    path = tags_yaml_path()
    if not path:
        return []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    return _normalize_tags(_toplevel_list_names(lines))


def save_tags_yaml(tags):
    """Write `tags` to the dataset's tags.yaml as a plain list, one per row.

    The canonical shape is a bare top-level list, one tag per line, each
    prefixed by ``- ``:

        - fire
        - smoke

    Any other content is preserved: an old `tags:` key (with its block) is
    replaced in place, and a pre-existing bare list is rewritten. Returns the
    written path, or None when no dataset is loaded.
    """
    path = tags_yaml_path()
    if not path:
        return None
    tags = _normalize_tags(tags)
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        lines = []

    # Drop a pre-existing bare list; it is rewritten below.
    lines = [ln for ln in lines if not _is_toplevel_list_item(ln)]

    out = []
    replaced = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if not replaced and _strip_comment(line.strip()).startswith("tags:"):
            for t in tags:
                out.append(f"- {t}\n")
            i += 1
            # skip the old tag block (list items only; stop at anything else)
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


def write_image_tags(entry, tags):
    """Write one image's tag file (normalized, one tag per line).

    Creates the split's tags folder when needed. Returns the written path, or
    None when the split is unknown.
    """
    split = _split_by_name(entry["split"])
    path = tag_path(entry)
    if split is None or path is None:
        return None
    tags = _normalize_tags(tags)
    os.makedirs(split["tags_dir"], exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(tags))
        if tags:
            f.write("\n")
    return path


def register_available_tags(tags):
    """Add tag names not yet in tags.yaml, preserving order.

    `tags.yaml` is rewritten only when there is at least one new name; when
    every name is already known the file is left untouched. Returns the
    resulting available-tags list ([] when no dataset is loaded).
    """
    available = read_tags_yaml()
    if tags_yaml_path() is None:
        return available
    fresh = [t for t in _normalize_tags(tags) if t not in available]
    if not fresh:
        return available
    available = available + fresh
    save_tags_yaml(available)
    return available


def _parse_label_file(path):
    """Return a list of (class, cx, cy, w, h) tuples from a YOLO label file."""
    boxes = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) < 5:
                    continue
                try:
                    cls = int(float(parts[0]))
                    cx, cy, w, h = (float(x) for x in parts[1:5])
                except ValueError:
                    continue
                boxes.append((cls, cx, cy, w, h))
    except OSError:
        pass
    return boxes


def read_classes():
    if STATE["classes"]:
        return STATE["classes"]
    # fallback: derive max class id from existing label files
    max_cls = -1
    for entry in STATE["images"]:
        p = label_path(entry)
        if p is None:
            continue
        if not os.path.isfile(p):
            continue
        for cls, *_ in _parse_label_file(p):
            max_cls = max(max_cls, cls)
    if max_cls >= 0:
        return [f"class_{i}" for i in range(max_cls + 1)]
    return ["class_0"]


def _entry_by_key(key):
    """Resolve a `split/name` key to a known image entry, or None.

    Identity (not position) is the stable way to name an image: the active
    filter/split can rebuild the list at any time, so an index may point at a
    different file than the client is showing.
    """
    if not key or "/" not in key:
        return None
    split, name = key.split("/", 1)
    for entry in STATE["images"]:
        if entry["split"] == split and entry["name"] == name:
            return entry
    return None


def _image_index(entry):
    """The 1-based position of `entry` in the visible list, else None."""
    visible = _current_images()
    for i, e in enumerate(visible):
        if e["split"] == entry["split"] and e["name"] == entry["name"]:
            return i + 1
    return None


def _request_entry():
    """Resolve the `?key=split/name` query string to an image entry, or 404."""
    entry = _entry_by_key(request.args.get("key", ""))
    if entry is None:
        abort(404)
    return entry


def _prune_clients(now=None):
    """Forget clients that have not pinged `/api/presence` within PRESENCE_TTL."""
    now = time.monotonic() if now is None else now
    for cid in [c for c, seen in CLIENTS.items() if now - seen > PRESENCE_TTL]:
        CLIENTS.pop(cid, None)
    return len(CLIENTS)


# --------------------------------------------------------------------------- #
# authentication (a non-empty user store turns login on)
# --------------------------------------------------------------------------- #
# Paths served without a session so the login page itself can load. Everything
# else under /api/ answers 401 until the user signs in; the SPA shell and its
# static assets are public so the login form can be rendered.
_AUTH_PUBLIC_PATHS = {"/api/login", "/api/session", "/api/logout"}

# Shipped default account, created on first run so `ybe start` is usable with no
# extra setup. Change it from the UI (Change password) or with --create-user.
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASSWORD = "admin"


def _valid_username(username):
    """A username may not be empty, contain ':', or include control chars."""
    return bool(username) and ":" not in username and not any(
        ord(ch) < 32 for ch in username
    )


def load_users():
    """Load USERS_FILE into the USERS map; missing/corrupt file means none."""
    global USERS
    try:
        with open(USERS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        USERS = {}
        return USERS
    raw = data.get("users") if isinstance(data, dict) else None
    USERS = (
        {str(name): str(hash_) for name, hash_ in raw.items()}
        if isinstance(raw, dict)
        else {}
    )
    return USERS


def _write_users():
    """Persist USERS atomically and owner-only; returns False on failure."""
    try:
        os.makedirs(os.path.dirname(USERS_FILE) or ".", exist_ok=True)
        tmp = USERS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "users": USERS}, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, USERS_FILE)
        try:
            os.chmod(USERS_FILE, 0o600)
        except OSError:
            pass
        return True
    except OSError:
        return False


def set_user(username, password):
    """Create or update a user; returns "created" or "updated"."""
    existed = username in USERS
    USERS[username] = generate_password_hash(password)
    if not _write_users():
        raise OSError(f"could not write {USERS_FILE}")
    return "updated" if existed else "created"


def ensure_default_admin():
    """Seed the shipped admin/admin account when no users exist; True if created."""
    if USERS:
        return False
    set_user(DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASSWORD)
    return True


def _prompt_password():
    """Read a new password twice with getpass; None on empty or mismatch.

    Prompting keeps the password out of the process list and shell history.
    """
    try:
        first = getpass.getpass("Password: ")
        second = getpass.getpass("Confirm password: ")
    except (EOFError, KeyboardInterrupt):
        print("", file=sys.stderr)
        print("error: password entry cancelled", file=sys.stderr)
        return None
    if not first:
        print("error: password must not be empty", file=sys.stderr)
        return None
    if first != second:
        print("error: passwords do not match", file=sys.stderr)
        return None
    return first


def verify_user(username, password):
    """Constant-time check of a submitted password against the store."""
    hashed = USERS.get(str(username))
    if not hashed:
        return False
    return check_password_hash(hashed, str(password))


def auth_enabled():
    """True when at least one user is registered and a login is required."""
    return bool(USERS)


def _session_username():
    """The signed-in username, if it still exists in the store."""
    user = session.get("ybe_user")
    return user if user in USERS else None


def _is_authenticated():
    """True when auth is off, or the request carries a valid session."""
    return not auth_enabled() or _session_username() is not None


@app.before_request
def _require_login():
    """Block API calls (and the SPA load) until the user has signed in."""
    if not auth_enabled():
        return None
    path = request.path
    if path == "/" or path.startswith("/static/") or path in _AUTH_PUBLIC_PATHS:
        return None
    if _session_username():
        return None
    if path.startswith("/api/"):
        return jsonify({"ok": False, "error": "authentication required"}), 401
    abort(401)


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/session")
def api_session():
    """Report whether a login is required and whether this client has one."""
    username = _session_username()
    return jsonify(
        {
            "auth_required": auth_enabled(),
            "authenticated": _is_authenticated(),
            "username": username,
        }
    )


@app.route("/api/login", methods=["POST"])
def api_login():
    """Sign in: compare the posted credentials and start a session."""
    if not auth_enabled():
        return jsonify({"ok": True, "auth_required": False})
    data = request.get_json(silent=True) or {}
    username = data.get("username", "")
    password = data.get("password", "")
    if verify_user(username, password):
        session["ybe_user"] = str(username)
        return jsonify({"ok": True, "username": str(username)})
    return jsonify({"ok": False, "error": "invalid username or password"}), 401


@app.route("/api/logout", methods=["POST"])
def api_logout():
    """Sign out: drop the session's user marker."""
    session.pop("ybe_user", None)
    return jsonify({"ok": True})


@app.route("/api/password", methods=["POST"])
def api_password():
    """Change the signed-in user's own password (needs the current one)."""
    username = _session_username()
    if not username:
        return jsonify({"ok": False, "error": "authentication required"}), 401
    data = request.get_json(silent=True) or {}
    current = str(data.get("current_password", ""))
    new = str(data.get("new_password", ""))
    if not verify_user(username, current):
        return jsonify({"ok": False, "error": "current password is incorrect"}), 403
    if not new:
        return jsonify({"ok": False, "error": "new password must not be empty"}), 400
    try:
        set_user(username, new)
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True})


@app.route("/api/config")
def api_config():
    app_shortcuts, user_shortcuts, shortcut_errors = split_shortcuts(load_shortcuts())
    actions = load_actions()
    hooks, hook_errors = load_hooks()
    filters, filter_errors = load_filters()
    classes = read_classes()
    filter_catalog = sorted(
        (
            {
                "name": f["name"],
                "description": f["description"],
                "arguments": [
                    {**arg, "options": resolve_filter_options(arg.get("options"), classes)}
                    for arg in f["arguments"]
                ],
            }
            for f in filters.values()
        ),
        key=lambda f: f["name"],
    )
    disabled = _disabled_extensions()
    action_defs = [
        {
            "name": a["name"],
            "steps": a["steps"],
            "after_success": a["after_success"],
            "source": a["source"],
            "api_version": a["api_version"],
            "status": api_version_status(a["api_version"]),
            "enabled": a["name"] not in disabled["action"],
        }
        for a in actions
    ]
    hook_defs = [
        {
            "name": h["name"],
            "event": h["event"],
            "steps": h["steps"],
            "after_success": h["after_success"],
            "source": h["source"],
            "api_version": h["api_version"],
            "status": api_version_status(h["api_version"]),
            "enabled": h["name"] not in disabled["hook"],
        }
        for h in hooks
    ]
    filter_defs = [
        {
            "name": f["name"],
            "description": f["description"],
            "arguments": f["arguments"],
            "steps": f["steps"],
            "source": f["source"],
            "api_version": f["api_version"],
            "status": api_version_status(f["api_version"]),
        }
        for f in filters.values()
    ]
    return jsonify(
        {
            "data_yaml": STATE["data_yaml"],
            "dataset_path": STATE["dataset_path"],
            "classes": classes,
            "tags": read_tags_yaml(),
            "images": _current_images(),
            "active_split": STATE["active_split"],
            "filters": filter_catalog,
            "filter_defs": filter_defs,
            "active_filters": STATE["active_filters"],
            "filter_error": STATE["filter_error"],
            "filter_errors": filter_errors,
            "recent_data_yamls": _load_recent(),
            "settings": _load_settings(),
            "tags_dir": STATE.get("tags_dir"),
            "tips": TIPS,
            "actions": [a["name"] for a in actions if a["name"] not in disabled["action"]],
            "action_defs": action_defs,
            "hooks": [h["name"] for h in hooks if h["name"] not in disabled["hook"]],
            "hook_defs": hook_defs,
            "hook_errors": hook_errors,
            "app_actions": sorted(APP_ACTIONS),
            "backend_actions": sorted(BACKEND_ACTION_NAMES),
            "hook_events": list(HOOK_EVENTS),
            "extension_api_version": EXTENSION_API_VERSION,
            "placeholders": {
                "action": _placeholder_payload(ACTION_PLACEHOLDERS),
                "filter": _placeholder_payload(FILTER_PLACEHOLDERS),
            },
            "shortcuts": app_shortcuts,
            "action_shortcuts": user_shortcuts,
            "shortcut_errors": shortcut_errors,
            "shortcut_defaults": load_shortcuts_from(SHORTCUTS_FILE),
            "user_shortcut_names": sorted(user_shortcut_names()),
            "readonly": STATE["readonly"],
            "debug": STATE["debug"],
            "auth": {
                "required": auth_enabled(),
                "username": _session_username() if auth_enabled() else None,
            },
            "version": read_version(),
            "changelog": changelog_for(read_version()),
            "update": update_status(),
            "splits": [
                {
                    "name": s["name"],
                    "images_dir": s["images_dir"],
                    "labels_dir": s["labels_dir"],
                    "tags_dir": s["tags_dir"],
                }
                for s in STATE["splits"]
            ],
        }
    )


@app.route("/api/update-check", methods=["GET", "POST"])
def api_update_check():
    """Report (or, with `{"force": true}`, refresh) the cached update info.

    GET is cheap and offline; the start thread populates the cache. POST with
    `force` is the manual "Check now" path and may hit the network.
    """
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        if data.get("force"):
            return jsonify({"ok": True, "update": check_for_update(force=True)})
    return jsonify({"ok": True, "update": update_status()})


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    """Cross-browser UI settings.

    GET returns the stored `{key: value}` map. POST body `{"settings": {...}}`
    merges the given keys (a null value removes one) and returns the result. A
    browser keeps its own `localStorage` value for any key it has set, so these
    act as the fallback a fresh browser starts from.
    """
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        changes = data.get("settings")
        if not isinstance(changes, dict):
            return jsonify({"ok": False, "error": "settings must be an object"}), 400
        return jsonify({"ok": True, "settings": _update_settings(changes)})
    return jsonify({"ok": True, "settings": _load_settings()})


@app.route("/api/shortcuts", methods=["POST"])
def api_shortcuts():
    """Edit keyboard shortcuts; overrides are written to the user shortcuts.txt.

    Body `{"set": {name: shortcut, ...}, "reset": [name, ...]}`. `set` upserts an
    override, `reset` drops it so the shipped binding applies again. Names must
    be app actions or actions from the actions/ folders; read-only is refused.
    """
    if STATE["readonly"]:
        return jsonify({"ok": False, "error": "read-only mode"}), 403

    data = request.get_json(silent=True) or {}
    sets = data.get("set") or {}
    resets = data.get("reset") or []
    if not isinstance(sets, dict) or not isinstance(resets, list):
        return jsonify({"ok": False, "error": "set must be an object and reset a list"}), 400

    known = set(APP_ACTIONS) | {a["name"] for a in load_actions()}
    clean_sets = {}
    for name, value in sets.items():
        if name not in known:
            return jsonify({"ok": False, "error": f"unknown action '{name}'"}), 400
        shortcut = _valid_shortcut(value)
        if shortcut is None:
            return jsonify({"ok": False, "error": f"invalid shortcut for '{name}'"}), 400
        clean_sets[name] = shortcut

    write_user_shortcuts(clean_sets, [n for n in resets if n in known])
    cfg = api_config().get_json()
    cfg["ok"] = True
    return jsonify(cfg)


@app.route("/api/presence", methods=["POST"])
def api_presence():
    """Track connected clients so the UI can warn about concurrent users.

    Body `{cid}` registers or refreshes a client; `{cid, "bye": true}` removes it
    (sent via `navigator.sendBeacon` when a page unloads). `count` is the number
    of clients seen within PRESENCE_TTL seconds; the UI warns while it is > 1.
    Presence never blocks any other request.
    """
    data = request.get_json(silent=True) or {}
    cid = (data.get("cid") or "").strip()
    if not cid:
        return jsonify({"ok": False, "error": "client id is required"}), 400

    now = time.monotonic()
    with CLIENTS_LOCK:
        if data.get("bye"):
            CLIENTS.pop(cid, None)
        else:
            CLIENTS[cid] = now
        count = _prune_clients(now)
    return jsonify({"ok": True, "count": count, "others": max(0, count - 1)})


@app.route("/api/data", methods=["POST"])
def api_data():
    data = request.get_json(silent=True) or {}
    path = (data.get("data_yaml") or "").strip()

    if not path:
        return jsonify({"ok": False, "error": "data.yaml path is required"}), 400
    if not os.path.isfile(path):
        return jsonify({"ok": False, "error": f"not a file: {path}"}), 400

    _load_dataset(path)
    _restore_tags_dir(STATE["data_yaml"])  # re-apply this dataset's tags folder
    _clear_filter()  # a filter belongs to the dataset that was active
    names = {s["name"] for s in STATE["splits"]}
    if STATE["active_split"] not in names:
        STATE["active_split"] = None

    if not STATE["splits"]:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "data.yaml parsed, but no train/val/test image folders were found",
                }
            ),
            400,
        )

    _push_recent(STATE["data_yaml"])

    cfg = api_config().get_json()
    cfg["ok"] = True
    return jsonify(cfg)


@app.route("/api/split", methods=["POST"])
def api_split():
    """Restrict navigation to a single split (or all splits when `split` is empty/null)."""
    data = request.get_json(silent=True) or {}
    split = (data.get("split") or "").strip() or None
    names = {s["name"] for s in STATE["splits"]}
    if split is not None and split not in names:
        return jsonify({"ok": False, "error": f"unknown split: {split}"}), 400

    previous = STATE["active_split"]
    STATE["active_split"] = split
    # The chain's first filter receives the split, so an active one must re-run.
    if STATE["active_filters"]:
        error = apply_filters(STATE["active_filters"])
        if error:
            STATE["active_split"] = previous  # keep split + filter consistent
            return jsonify({"ok": False, "error": error}), 400

    _save_view(STATE["data_yaml"], STATE["active_split"], STATE["active_filters"])
    cfg = api_config().get_json()
    cfg["ok"] = True
    return jsonify(cfg)


@app.route("/api/filter", methods=["POST"])
def api_filter():
    """Set the active filter chain (narrows the image list), or clear it.

    Body `{filters: [{name, arguments}, ...]}` runs the chain in order; an
    empty/missing list clears it. A list of names and `{filter: name}` (or
    `null`) are accepted for older clients.
    """
    if not STATE["splits"]:
        return jsonify({"ok": False, "error": "no dataset loaded"}), 400

    data = request.get_json(silent=True) or {}
    items = data.get("filters")
    if items is None:
        legacy = data.get("filter")
        legacy = legacy.strip() if isinstance(legacy, str) else ""
        items = [legacy] if legacy else []
    if not isinstance(items, list):
        return jsonify({"ok": False, "error": "filters must be a list"}), 400

    error = apply_filters(items)
    if error:
        return jsonify({"ok": False, "error": error}), 400

    _save_view(STATE["data_yaml"], STATE["active_split"], STATE["active_filters"])
    cfg = api_config().get_json()
    cfg["ok"] = True
    return jsonify(cfg)


def _images_payload():
    """The image-list part of a config/rescan reply (no filesystem access)."""
    return {
        "ok": True,
        "images": _current_images(),
        "active_split": STATE["active_split"],
        "active_filters": STATE["active_filters"],
        "filter_error": STATE["filter_error"],
    }


@app.route("/api/images")
def api_images():
    """The current (in-memory) visible image list, without touching the disk."""
    return jsonify(_images_payload())


@app.route("/api/images/rescan", methods=["POST"])
def api_images_rescan():
    """Re-scan the image folders (e.g. after a user action deleted/added files)."""
    _rescan_images()
    return jsonify(_images_payload())


@app.route("/api/actions/run", methods=["POST"])
def api_action_run():
    """Start (or resume) a user action execution for the current image.

    The backend owns the whole `steps` + `after_success` chain: it runs the
    server-side entries inline and, when it reaches a client-side app action,
    returns it as `client_action` together with an execution `uid`. The UI runs
    that action and posts back `{uid, result}` to resume the chain. The run's
    {PIPE_PATH} file is created here and deleted when the chain ends (or aborts)
    unless `--keep-pipe` was passed.
    """
    data = request.get_json(silent=True) or {}
    uid = (data.get("uid") or "").strip()
    if uid:
        return _resume_execution(uid, data)

    name = (data.get("action") or "").strip()
    target = (data.get("target") or "").strip()

    entry = _entry_by_key(target)
    if entry is None:
        return (
            jsonify({"ok": False, "error": f"image not in the current list: {target}"}),
            400,
        )
    split = _split_by_name(entry["split"])
    if split is None:
        abort(404)

    action = next((a for a in load_actions() if a["name"] == name), None)
    is_hook = False
    if action is None:
        # Event hooks are ordinary names here (`on_<event>`), so they can be run.
        action = next((h for h in load_hooks()[0] if h["name"] == name), None)
        is_hook = action is not None
    if action is None:
        return jsonify({"ok": False, "error": f"unknown action: {name}"}), 400

    disabled = _disabled_extensions()
    if name in disabled["hook" if is_hook else "action"]:
        return (
            jsonify({"ok": False, "error": f"'{name}' is disabled for this dataset"}),
            400,
        )

    pipe_path = create_pipe()
    # 1-based, matching the "current / total" counter shown in the UI; 0 when the
    # target is not part of the visible list (e.g. an off-filter image).
    position = _image_index(entry)
    values = {
        "IMAGE_PATH": os.path.join(split["images_dir"], entry["name"]),
        "LABEL_PATH": label_path(entry),
        "DATASET_PATH": STATE["dataset_path"] or "",
        "DATA_YAML_PATH": STATE["data_yaml"] or "",
        "IMAGE_INDEX": str(position or 0),
        # the folder holding app.py (shipped files); script folders are exposed
        # both explicitly and relatively (cwd is HOME_DIR, so scripts/… works)
        "APP_DIR": BASE_DIR,
        "HOME_DIR": YBX_HOME,
        "APP_SCRIPT_DIR": APP_SCRIPT_DIR,
        "USER_SCRIPT_DIR": USER_SCRIPT_DIR,
        # the interpreter running the app; use {PYTHON} so steps work even when
        # `python` is not on PATH
        "PYTHON": sys.executable,
        # scratch file shared by every step and after_success action of this run
        "PIPE_PATH": pipe_path or "",
    }
    state, status, detail = begin_execution(action, name, values, pipe_path)
    return _execution_response(state, status, detail)


def _resume_execution(uid, data):
    """Resume a paused execution after the UI ran its `client_action`."""
    state = EXECUTIONS.get(uid)
    if state is None:
        return jsonify({"ok": False, "error": "unknown or expired execution"}), 400

    result = data.get("result") or {}
    if not result.get("ok", True):
        failed = state.get("pending") or "after_success"
        error = result.get("error") or "app action failed"
        finish_execution(state)
        payload = _execution_payload(state)
        payload["ok"] = False
        payload["error"] = f'after_success "{failed}" failed: {error}'
        return jsonify(payload), 200

    state["pending"] = None
    status, detail = _advance_execution(state)
    return _execution_response(state, status, detail)


def _execution_response(state, status, detail):
    """Reply for a start/advance result: pause at a client action, or finish."""
    if status == "client":
        uid = uuid.uuid4().hex
        state["uid"] = uid
        state["pending"] = detail
        EXECUTIONS[uid] = state
        payload = {"ok": True, "uid": uid, "client_action": detail}
        payload.update(_execution_payload(state))
        return jsonify(payload)

    finish_execution(state)
    payload = _execution_payload(state)
    if status == "done":
        payload["ok"] = True
        return jsonify(payload)
    payload["ok"] = False
    if status == "timeout":
        payload["error"] = "command timed out"
        return jsonify(payload), 500
    if status == "failed":
        return jsonify(payload), 200
    payload["error"] = detail or "action failed"
    return jsonify(payload), 400


def _execution_payload(state):
    """The user-visible result shared by the paused and final replies."""
    return {
        "action": state["action"],
        "command": " && ".join(state["commands"]),
        "exit_code": state["exit_code"],
        "stdout": "\n".join(state["stdout"]),
        "stderr": "\n".join(state["stderr"]),
        "pipe_path": state["pipe_path"],
        "cwd": state.get("cwd"),
    }


@app.route("/api/actions/save", methods=["POST"])
def api_action_save():
    """Create (or replace) a user action from the Settings form.

    Body `{name, steps, after_success, overwrite}`. The file is written to the
    user actions/ folder as `<name>.yaml`; an existing user file needs
    `overwrite: true`. Read-only is refused.
    """
    if STATE["readonly"]:
        return jsonify({"ok": False, "error": "read-only mode"}), 403
    data = request.get_json(silent=True) or {}
    name = _safe_extension_name(data.get("name"))
    if name is None:
        return jsonify({"ok": False, "error": "invalid action name"}), 400
    steps, error = _clean_extension_entries(data.get("steps"))
    if error:
        return jsonify({"ok": False, "error": error}), 400
    after, error = _clean_extension_entries(data.get("after_success"))
    if error:
        return jsonify({"ok": False, "error": error}), 400
    if not steps and not after:
        return jsonify({"ok": False, "error": "add at least one step"}), 400

    os.makedirs(USER_ACTIONS_DIR, exist_ok=True)
    target = os.path.join(USER_ACTIONS_DIR, name + ".yaml")
    if os.path.exists(target) and not data.get("overwrite"):
        return jsonify({"ok": False, "error": f"a user action '{name}' already exists"}), 409
    try:
        with open(target, "w", encoding="utf-8") as f:
            f.write(_dump_action_file(steps, after))
    except OSError as exc:
        return jsonify({"ok": False, "error": f"could not write the action: {exc}"}), 500

    cfg = api_config().get_json()
    cfg["ok"] = True
    return jsonify(cfg)


@app.route("/api/hooks/save", methods=["POST"])
def api_hook_save():
    """Create (or replace) a user event hook from the Settings form.

    Body `{event, steps, after_success, active, overwrite}`. The file is
    `<user hooks>/on_<event>.yaml`; existing needs `overwrite: true`.
    """
    if STATE["readonly"]:
        return jsonify({"ok": False, "error": "read-only mode"}), 403
    data = request.get_json(silent=True) or {}
    event = str(data.get("event") or "").strip()
    if event not in HOOK_EVENTS:
        return jsonify({"ok": False, "error": f"unknown hook event: {event}"}), 400
    steps, error = _clean_extension_entries(data.get("steps"))
    if error:
        return jsonify({"ok": False, "error": error}), 400
    after, error = _clean_extension_entries(data.get("after_success"))
    if error:
        return jsonify({"ok": False, "error": error}), 400
    if not steps and not after:
        return jsonify({"ok": False, "error": "add at least one step"}), 400

    os.makedirs(USER_HOOKS_DIR, exist_ok=True)
    target = os.path.join(USER_HOOKS_DIR, HOOK_PREFIX + event + ".yaml")
    if os.path.exists(target) and not data.get("overwrite"):
        return jsonify({"ok": False, "error": f"a hook for {event} already exists"}), 409
    try:
        with open(target, "w", encoding="utf-8") as f:
            f.write(_dump_action_file(steps, after, active=bool(data.get("active", True))))
    except OSError as exc:
        return jsonify({"ok": False, "error": f"could not write the hook: {exc}"}), 500

    cfg = api_config().get_json()
    cfg["ok"] = True
    return jsonify(cfg)


@app.route("/api/filters/save", methods=["POST"])
def api_filter_save():
    """Create (or replace) a user filter from the Settings form.

    Body `{name, description, active, arguments, steps, overwrite}`. The file is
    written to the user filters/ folder as `<name>.yaml`.
    """
    if STATE["readonly"]:
        return jsonify({"ok": False, "error": "read-only mode"}), 403
    data = request.get_json(silent=True) or {}
    name = _safe_extension_name(data.get("name"))
    if name is None:
        return jsonify({"ok": False, "error": "invalid filter name"}), 400
    description = str(data.get("description") or "").strip()
    if any(ord(ch) < 32 for ch in description):
        return jsonify({"ok": False, "error": "description cannot contain newlines"}), 400
    arguments, error = _clean_filter_arguments(data.get("arguments"))
    if error:
        return jsonify({"ok": False, "error": error}), 400
    steps, error = _clean_extension_entries(data.get("steps"))
    if error:
        return jsonify({"ok": False, "error": error}), 400
    if not steps:
        return jsonify({"ok": False, "error": "add at least one step"}), 400

    os.makedirs(USER_FILTERS_DIR, exist_ok=True)
    target = os.path.join(USER_FILTERS_DIR, name + ".yaml")
    if os.path.exists(target) and not data.get("overwrite"):
        return jsonify({"ok": False, "error": f"a user filter '{name}' already exists"}), 409
    try:
        with open(target, "w", encoding="utf-8") as f:
            f.write(_dump_filter_file(description, bool(data.get("active", True)),
                                      arguments, steps))
    except OSError as exc:
        return jsonify({"ok": False, "error": f"could not write the filter: {exc}"}), 500

    cfg = api_config().get_json()
    cfg["ok"] = True
    return jsonify(cfg)


@app.route("/api/extensions/disabled", methods=["POST"])
def api_extension_disabled():
    """Enable or disable one action/hook for the current dataset.

    Body `{kind, name, disabled}`. The flag is stored in the dataset's view entry
    in `.view_state.json`, so it is undoable and needs no file edit; the extension
    YAML is never touched. Returns the fresh config payload.
    """
    data = request.get_json(silent=True) or {}
    kind = data.get("kind")
    if kind not in DISABLED_KIND_KEYS:
        return jsonify({"ok": False, "error": "kind must be action or hook"}), 400
    name = str(data.get("name") or "").strip()
    if extension_file_for(kind, name) is None:
        return jsonify({"ok": False, "error": "unknown extension"}), 404
    if not STATE["data_yaml"]:
        return jsonify({"ok": False, "error": "load a dataset first"}), 400
    _set_extension_disabled(kind, name, bool(data.get("disabled")))

    cfg = api_config().get_json()
    cfg["ok"] = True
    return jsonify(cfg)


@app.route("/api/extensions/delete", methods=["POST"])
def api_extension_delete():
    """Delete one of the user's extension files (never a shipped one)."""
    if STATE["readonly"]:
        return jsonify({"ok": False, "error": "read-only mode"}), 403
    data = request.get_json(silent=True) or {}
    found = extension_file_for(data.get("kind"), data.get("name"))
    if found is None:
        return jsonify({"ok": False, "error": "unknown extension"}), 404
    if found["source"] != "user":
        return jsonify({"ok": False, "error": "shipped files cannot be deleted"}), 400
    try:
        os.remove(found["path"])
    except OSError as exc:
        return jsonify({"ok": False, "error": f"could not delete the file: {exc}"}), 500
    if found["kind"] in DISABLED_KIND_KEYS:
        # do not keep a name disabled for a file the user just removed
        _set_extension_disabled(found["kind"], found["name"], False)

    cfg = api_config().get_json()
    cfg["ok"] = True
    return jsonify(cfg)


@app.route("/api/extensions/file", methods=["GET", "POST"])
def api_extension_file():
    """Read or raw-edit one extension file for the YAML editor.

    GET (`?kind=&name=`) returns the file's text plus its source and version
    status. POST `{kind, name, text, overwrite}` saves edited text (read-only is
    refused): the file must parse and have a body, `api_version` is bumped to
    the current value, and saving a shipped file writes a user override.
    """
    if request.method == "POST":
        return _save_extension_file()

    found = extension_file_for(request.args.get("kind"), request.args.get("name"))
    if found is None:
        return jsonify({"ok": False, "error": "unknown extension"}), 404
    if api_version_status(found["api_version"]) == "newer":
        return jsonify(
            {"ok": False, "error": "this file is newer than the app supports"}
        ), 400
    return jsonify(_extension_file_payload(found, _read_text(found["path"])))


def _save_extension_file():
    """Save raw editor text (the POST half of `/api/extensions/file`)."""
    if STATE["readonly"]:
        return jsonify({"ok": False, "error": "read-only mode"}), 403
    data = request.get_json(silent=True) or {}
    kind = data.get("kind")
    text = data.get("text")
    if not isinstance(text, str):
        return jsonify({"ok": False, "error": "text is required"}), 400
    found = extension_file_for(kind, data.get("name"))
    if found is None:
        return jsonify({"ok": False, "error": "unknown extension"}), 404
    if api_version_status(found["api_version"]) == "newer":
        return jsonify(
            {"ok": False, "error": "this file is newer than the app supports"}
        ), 400

    parsed = _parse_extension_text(kind, text)
    if kind == "filter":
        usable = bool(parsed.get("steps"))
    else:
        usable = bool(parsed.get("steps") or parsed.get("after_success"))
    if not usable:
        return jsonify({"ok": False, "error": "the file has no steps / after_success"}), 400

    if found["source"] == "user":
        target = found["path"]
    else:
        target = os.path.join(_extension_user_dir(kind), os.path.basename(found["path"]))
        if os.path.exists(target) and not data.get("overwrite"):
            return jsonify(
                {"ok": False, "error": "a user override already exists"}
            ), 409

    text = _bump_api_version_text(text)
    try:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as exc:
        return jsonify({"ok": False, "error": f"could not write the file: {exc}"}), 500

    # Re-resolve so the reply reflects the user override and bumped version.
    return jsonify(_extension_file_payload(extension_file_for(kind, data.get("name")) or found, text))


@app.route("/api/image")
def api_image():
    entry = _request_entry()
    split = _split_by_name(entry["split"])
    if split is None:
        abort(404)
    assert split is not None
    resp = send_from_directory(split["images_dir"], entry["name"])
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/annotations", methods=["GET", "POST"])
def api_annotations():
    """Read/write one image's annotations: its boxes and tags.

    GET returns `{"boxes": [...], "tags": [...]}`. POST writes the label file,
    the image's tag file, and adds any new tag names to tags.yaml.
    """
    entry = _request_entry()
    split = _split_by_name(entry["split"])
    if split is None:
        abort(404)
    assert split is not None

    if request.method == "GET":
        boxes = _parse_label_file(label_path(entry))
        return jsonify(
            {
                "boxes": [
                    {"class": c, "cx": cx, "cy": cy, "w": w, "h": h}
                    for c, cx, cy, w, h in boxes
                ],
                "tags": _read_tag_lines(tag_path(entry)),
            }
        )

    if STATE["readonly"]:
        return jsonify({"ok": False, "error": "read-only mode"}), 403

    data = request.get_json(silent=True) or {}
    raw = data.get("boxes", [])
    lines = []
    for b in raw:
        try:
            cls = int(b.get("class"))
            cx = float(b.get("cx"))
            cy = float(b.get("cy"))
            w = float(b.get("w"))
            h = float(b.get("h"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "invalid box"}), 400
        if cls < 0:
            cls = 0
        cx = max(0.0, min(1.0, cx))
        cy = max(0.0, min(1.0, cy))
        w = max(0.0, min(1.0, w))
        h = max(0.0, min(1.0, h))
        lines.append(f"{cls} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")

    path = label_path(entry)
    assert path is not None
    os.makedirs(split["labels_dir"], exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        if lines:
            f.write("\n")

    payload = {"ok": True, "count": len(lines)}
    # Tags ride along with the save: write the image's tag file and register any
    # new names in tags.yaml. Absent `tags` leaves tag files untouched (a plain
    # label write from an older client).
    if "tags" in data:
        tags = _normalize_tags(data.get("tags"))
        write_image_tags(entry, tags)
        payload["tags_count"] = len(tags)
        payload["available_tags"] = register_available_tags(tags)
    return jsonify(payload)


@app.route("/api/tags-dir", methods=["POST"])
def api_tags_dir():
    """Set (or clear) the per-dataset tags folder and re-derive the split paths.

    Body `{"tags_dir": "<folder>"}` sets an override base folder (each split uses
    `<folder>/<split>`); an empty value restores the default `images` -> `tags`
    derivation. Saved with the dataset's view state.
    """
    if not STATE["splits"]:
        return jsonify({"ok": False, "error": "no dataset loaded"}), 400
    if STATE["readonly"]:
        return jsonify({"ok": False, "error": "read-only mode"}), 403

    data = request.get_json(silent=True) or {}
    raw = (data.get("tags_dir") or "").strip()
    path = os.path.abspath(os.path.expanduser(raw)) if raw else None
    if path and not os.path.isdir(path):
        return jsonify({"ok": False, "error": f"not a folder: {path}"}), 400

    STATE["tags_dir"] = path
    STATE["splits"] = scan_splits()
    if STATE["active_filters"]:
        error = apply_filters(STATE["active_filters"])
        if error:
            STATE["filter_error"] = error
    _save_view(STATE["data_yaml"], STATE["active_split"], STATE["active_filters"])
    cfg = api_config().get_json()
    cfg["ok"] = True
    return jsonify(cfg)


# --------------------------------------------------------------------------- #
# entrypoint
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(description="YOLO labelling app (Flask)")
    parser.add_argument("--data", help="path to data.yaml")
    parser.add_argument(
        "--home",
        help="folder holding your actions/ hooks/ filters/ scripts/ (default: "
        "$YBX_HOME, else the parent of app.py)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument(
        "--readonly",
        action="store_true",
        help="serve as a read-only viewer (no saving labels)",
    )
    parser.add_argument(
        "--create-user",
        metavar="NAME",
        help="create a user (or reset a password) in the user store, prompting "
        "for the password, then exit",
    )
    parser.add_argument(
        "--list-users",
        action="store_true",
        help="list registered users, then exit",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="log verbose messages to the browser console (see /api/config)",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="start on the settings screen instead of reopening the last dataset",
    )
    parser.add_argument(
        "--keep-pipe",
        action="store_true",
        help="keep the {PIPE_PATH} file after each action/hook run instead of deleting it",
    )
    parser.add_argument(
        "--keep-filter-pipes",
        action="store_true",
        help="keep the filter-chain input/output pipe files instead of deleting them",
    )
    parser.add_argument(
        "--no-update-check",
        action="store_true",
        help="do not check GitHub for a newer version",
    )
    parser.add_argument(
        "--log-file",
        help="write logs to this file instead of stderr (used by daemon mode)",
    )
    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="disable the Werkzeug auto-reloader (used by daemon mode)",
    )
    args = parser.parse_args()

    if args.home:
        configure_home(args.home)
    ensure_user_dirs()

    log = setup_logging(args.log_file, args.debug)
    log.info(
        "yolo-box-editor %s | user dir: %s (override with --home)", read_version(), YBX_HOME
    )

    STATE["readonly"] = args.readonly
    STATE["debug"] = args.debug
    STATE["keep_pipe"] = args.keep_pipe
    STATE["keep_filter_pipes"] = args.keep_filter_pipes
    STATE["no_update_check"] = args.no_update_check

    load_users()
    if ensure_default_admin():
        log.warning(
            "no users found: created the default account %r (password %r) — "
            "change it from the UI or with --create-user",
            DEFAULT_ADMIN_USER,
            DEFAULT_ADMIN_PASSWORD,
        )

    # Admin commands manage the user store and exit before the server starts.
    if args.list_users:
        for name in sorted(USERS):
            print(name)
        if not USERS:
            print(f"(no users registered in {USERS_FILE})")
        return

    if args.create_user:
        username = args.create_user
        if not _valid_username(username):
            parser.error("--create-user NAME must be non-empty and contain no ':'")
        password = _prompt_password()
        if password is None:
            sys.exit(1)
        try:
            action = set_user(username, password)
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"{action} user {username!r} in {USERS_FILE}")
        return

    start_update_checker()

    if args.data:
        _load_dataset(args.data)
        _push_recent(STATE["data_yaml"])
    elif not args.no_resume:
        _resume_last_dataset()

    log.info("serving on http://%s:%s", args.host, args.port)
    app.run(host=args.host, port=args.port, debug=True, use_reloader=not args.no_reload)


if __name__ == "__main__":
    main()
