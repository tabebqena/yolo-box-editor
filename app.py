#!/usr/bin/env python3
"""YOLO labelling app served by Flask.

Usage:
    python app.py --data /path/to/data.yaml
    python app.py --data /path/to/data.yaml --readonly   # viewer only

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
import json
import os
import shlex
import subprocess
import sys
import tempfile
import uuid

from flask import Flask, abort, jsonify, render_template, request, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}

RECENT_FILE = os.path.join(BASE_DIR, ".recent_data_yamls.json")
ACTIONS_DIR = os.path.join(BASE_DIR, "actions")  # one YAML file per action
HOOKS_DIR = os.path.join(BASE_DIR, "hooks")  # one YAML file per event hook
FILTERS_DIR = os.path.join(BASE_DIR, "filters")  # one Python script per filter
SHORTCUTS_FILE = os.path.join(BASE_DIR, "shortcuts.txt")
SHORTCUTS_ADD_FILE = os.path.join(BASE_DIR, "shortcuts.a.txt")  # user overrides, never shipped
# Per-run {PIPE_PATH} files live in the system temp dir (never in the repo).
PIPE_DIR = os.path.join(tempfile.gettempdir(), "yolo-box-editor-pipes")

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
    "app_refresh_image",
}

MAX_RECENT = 10
ACTION_TIMEOUT = 120  # seconds
FILTER_TIMEOUT = 120  # seconds
MAX_CASCADE_DEPTH = 8  # max actions run by one execution (root + after_success)

# Event hooks live in the hooks/ folder and fire on app events (never from a
# toolbar button or a shortcut). A hook file is named `on_<event>.yaml`; when the
# file name does not resolve to a known event, its `event_name:` key is used.
HOOK_PREFIX = "on_"
HOOK_EVENTS = (
    "images_list_loaded",
    "image_loaded",
    "prev",
    "next",
    "before_save",
    "after_save",
    "box_created",
    "box_deleted",
    "box_edited",
)


def is_hook_name(name):
    """True when `name` looks like a hook name (`on_*`)."""
    return bool(name) and name.startswith(HOOK_PREFIX)


app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

STATE = {
    "data_yaml": None,
    "dataset_path": None,
    "splits": [],   # [{"name": "train", "images_dir": ..., "labels_dir": ...}]
    "images": [],   # flat navigation list: [{"split": "train", "name": "a.jpg"}]
    "active_split": None,  # None = all splits; or a single split name
    "active_filter": None,  # None = no filter; or a filter name from filters/
    "filter_images": None,  # cached filter result (list of {split, name})
    "filter_error": None,   # last filter failure/notice message (shown in the UI)
    "classes": [],  # resolved class names from data.yaml `names`
    "readonly": False,
    "debug": False,  # --debug: the UI logs verbose messages to the browser console
    "keep_pipe": False,  # --keep-pipe: do not delete the {PIPE_PATH} file after a run
}

# In-flight action executions, paused at a client-side (app_*) after_success
# entry: uid -> execution state (see _begin_execution / _advance_execution). The
# backend owns the whole chain, so it also owns the run's {PIPE_PATH} file.
EXECUTIONS = {}


# --------------------------------------------------------------------------- #
# data.yaml parsing
# --------------------------------------------------------------------------- #
def _strip_comment(s):
    return s.split("#", 1)[0].strip()


def _parse_yaml_names_value(value):
    value = _strip_comment(value.strip())
    if not value:
        return []
    # inline list: [fire, smoke]
    if value.startswith("["):
        inner = value[1 : value.rfind("]")]
        return [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
    names = []
    for raw in value.splitlines():
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("-"):
            name = line[1:].strip().strip("'\"")
            if name:
                names.append(name)
        elif ":" in line:
            name = line.split(":", 1)[1].strip().strip("'\"")
            if name:
                names.append(name)
    return names


def _extract_yaml_block(lines, key):
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith(key + ":"):
            continue
        indent = len(line) - len(line.lstrip())
        block = []
        first = _strip_comment(stripped.split(":", 1)[1])
        if first:
            block.append(first)
        for ln in lines[i + 1 :]:
            s = ln.strip()
            if not s:
                block.append(s)
                continue
            cur_indent = len(ln) - len(ln.lstrip())
            if cur_indent <= indent:
                break
            block.append(_strip_comment(s))
        return "\n".join(block).strip()
    return None


def _read_yaml_names(path):
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    value = _extract_yaml_block(lines, "names")
    return _parse_yaml_names_value(value or "")


def _parse_data_yaml(path):
    data = {}
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return data

    names = _read_yaml_names(path)
    if names:
        data["names"] = names

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = _strip_comment(value).strip().strip("'\"")
        if key in ("path", "train", "val", "test") and value:
            data[key] = value
        elif key == "nc":
            try:
                data["nc"] = int(float(value))
            except ValueError:
                pass
    return data


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def is_image(name):
    return os.path.splitext(name)[1].lower() in IMAGE_EXTS


def _load_recent():
    """Read the last opened data.yaml paths (newest first)."""
    try:
        with open(RECENT_FILE, encoding="utf-8") as f:
            recents = json.load(f)
        return [p for p in recents if isinstance(p, str)][:MAX_RECENT]
    except (OSError, ValueError):
        return []


def _push_recent(path):
    """Record an opened data.yaml, newest first, capped at MAX_RECENT."""
    recents = [p for p in _load_recent() if p != path]
    recents.insert(0, path)
    recents = recents[:MAX_RECENT]
    try:
        with open(RECENT_FILE, "w", encoding="utf-8") as f:
            json.dump(recents, f, indent=2)
            f.write("\n")
    except OSError:
        pass
    return recents


# --------------------------------------------------------------------------- #
# actions/ (user-configurable shell actions, one YAML file per action)
# --------------------------------------------------------------------------- #
ACTIONS_DOC = (
    "Each action is a YAML file in the actions/ directory: an optional "
    "top-level `name:` (defaults to the file name), a `steps` list and an "
    "optional `after_success` list, run in order and stopping at the first "
    "failure. Both lists accept the same entries: an `app_*` name runs in the "
    "UI, another (non-hook) action name runs its own steps inline, and any "
    "other `steps` entry is a shell command. Files ending in `.a.yaml` are the "
    "user's own (never shipped) and win on a name clash. Placeholders are "
    "substituted with shell-quoted values: {IMAGE_PATH}, {LABEL_PATH}, "
    "{DATASET_PATH}, {DATA_YAML_PATH}, {IMAGE_INDEX}, {APP_DIR}, {PIPE_PATH}. "
    "Event hooks live in the hooks/ directory and cannot be bound."
)


def _read_text_lines(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.readlines()
    except OSError:
        return []


def _read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _yaml_scalar(s):
    """Strip one layer of matching single/double quotes from a YAML scalar."""
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


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


def _action_files(dirpath, overrides):
    """Sorted `.yaml` paths in `dirpath`: `.a.yaml` when `overrides`, else the rest."""
    if not os.path.isdir(dirpath):
        return []
    paths = []
    for fname in sorted(os.listdir(dirpath)):
        if not fname.endswith(".yaml") or fname.endswith(".a.yaml") != overrides:
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
    suffix = ".a.yaml" if fname.endswith(".a.yaml") else ".yaml"
    return fname[: -len(suffix)]


def load_actions():
    """Parse the actions/ directory into entries (read fresh).

    One action per `.yaml` file (name from its `name:` key or the file name).
    Returns [{"name": ..., "steps": [...], "after_success": [...]}]; entries with
    neither steps nor after_success are dropped. The user's `.a.yaml` files are
    read last and win on a name clash.
    """
    merged = {}
    paths = _action_files(ACTIONS_DIR, overrides=False) + _action_files(
        ACTIONS_DIR, overrides=True
    )
    for path in paths:
        data = _parse_action_file(_read_text(path))
        name = _action_name(path, data["name"])
        if not name:
            continue
        if data["steps"] or data["after_success"]:
            merged[name] = {
                "name": name,
                "steps": data["steps"],
                "after_success": data["after_success"],
            }
    return list(merged.values())


HOOKS_DOC = (
    "Each hook is a YAML file in the hooks/ directory, named `on_<event>.yaml` "
    "(the file name picks the event). When the file name does not resolve to a "
    "known event, the top-level `event_name:` key is used instead. A hook with "
    "`active: false` is ignored. Hooks use the same `steps` / `after_success` "
    "as actions and the same placeholders, but run on app events instead of a "
    "button. Files ending in `.a.yaml` are the user's own (never shipped). "
    "Available events: " + ", ".join(HOOK_EVENTS) + "."
)


def _hook_event(path, data):
    """The event a hook file fires: `on_<event>.yaml` first, then `event_name:`.

    Returns None when neither the file name nor the `event_name:` key names a
    known app event.
    """
    fname = os.path.basename(path)
    suffix = ".a.yaml" if fname.endswith(".a.yaml") else ".yaml"
    stem = fname[: -len(suffix)]
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
    user's `.a.yaml` files are read last and win on an event clash.
    """
    merged = {}
    errors = []
    paths = _action_files(HOOKS_DIR, overrides=False) + _action_files(
        HOOKS_DIR, overrides=True
    )
    for path in paths:
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
def _run_command(state, command):
    """Run one shell command, accumulating output in `state`.

    Returns "ok", "failed", "timeout" or "error"; `state["exit_code"]` holds the
    failing command's code on "failed".
    """
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=ACTION_TIMEOUT,
            cwd=BASE_DIR,
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


def _action_items(action):
    """Expand an action into its ordered work-queue items.

    `steps` and `after_success` share one syntax:
      - an `app_*` name                 -> ("app", name)    run in the UI
      - a known (non-hook) action name  -> ("action", dict) run its steps inline
      - anything else in `steps`        -> ("cmd", text)    shell command
      - anything else in `after_success`-> an error item
    """
    actions_by_name = {a["name"]: a for a in load_actions()}
    items = []
    for step in action.get("steps") or []:
        if step in APP_ACTIONS:
            items.append(("app", step))
        elif step in actions_by_name:
            items.append(("action", actions_by_name[step]))
        else:
            items.append(("cmd", step))
    for name in action.get("after_success") or []:
        if name in APP_ACTIONS:
            items.append(("app", name))
        elif name in actions_by_name:
            items.append(("action", actions_by_name[name]))
        elif is_hook_name(name):
            items.append(
                ("bad", f'"{name}" is an event hook; hooks cannot run from after_success')
            )
        else:
            items.append(("bad", f"unknown action: {name}"))
    return items


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


SHORTCUTS_FILE_DOC = (
    "Each non-empty, non-comment line is  ACTION_NAME  <SHORTCUT>  label. "
    "SHORTCUT is wrapped in angle brackets: a key with optional +joined "
    "modifiers (Ctrl, Alt, Shift, Meta). The label after the '>' is free text. "
    "ACTION_NAME must be an app action (app_*) or an action from the actions/ "
    "folder (hooks cannot be bound). Entries are merged from shortcuts.txt then "
    "shortcuts.a.txt (the user file, which wins on a name clash)."
)


def _line_comment(line):
    """Whole-line comments only; labels may contain '#'."""
    return line.startswith("#")


def parse_shortcut_line(line):
    """One optionally-inline line  NAME <SHORTCUT> label  -> (name, shortcut, label)."""
    line = line.strip()
    if not line or _line_comment(line):
        return None
    parts = line.split(None, 1)
    if len(parts) < 2:
        return None
    name = parts[0]
    rest = parts[1]
    start = rest.find("<")
    end = rest.find(">", start + 1)
    if start < 0 or end < 0:
        return None  # malformed: no <SHORTCUT> brackets
    shortcut = rest[start + 1 : end].strip()
    label = rest[end + 1 :].strip()
    if not shortcut:
        return None
    return name, shortcut, label


def load_shortcuts():
    """Parse shortcuts.txt + shortcuts.a.txt into {name: {shortcut, label}} (read fresh)."""
    shortcuts = {}
    for path in (SHORTCUTS_FILE, SHORTCUTS_ADD_FILE):
        for raw in _read_text_lines(path):
            parsed = parse_shortcut_line(raw)
            if parsed is None:
                continue
            name, shortcut, label = parsed
            shortcuts[name] = {"shortcut": shortcut, "label": label}
    return shortcuts


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
# filters/ (one Python script per filter; narrows the loaded image list)
# --------------------------------------------------------------------------- #
FILTERS_DOC = (
    "Each filter is a Python script in the filters/ directory (name = file name "
    "without .py). The app runs it as `python <script> <data.yaml> <split>`, "
    "where <split> is train/val/test or an empty string for all splits. The "
    "script must print one `split/name` per line (e.g. train/a.jpg); the app "
    "keeps those images in that order. Files ending in `.a.py` are the user's "
    "own (never shipped) and win on a name clash."
)


def _filter_files(dirpath, overrides):
    """Sorted `.py` paths in `dirpath`: `.a.py` when `overrides`, else the rest."""
    if not os.path.isdir(dirpath):
        return []
    paths = []
    for fname in sorted(os.listdir(dirpath)):
        if not fname.endswith(".py") or fname.endswith(".a.py") != overrides:
            continue
        path = os.path.join(dirpath, fname)
        if os.path.isfile(path):
            paths.append(path)
    return paths


def _filter_name(path):
    """The filter's name: its file name without the `.py` / `.a.py` suffix."""
    fname = os.path.basename(path)
    suffix = ".a.py" if fname.endswith(".a.py") else ".py"
    return fname[: -len(suffix)]


def load_filters():
    """Map every filter name to its script path (read fresh).

    The user's `.a.py` files are read last and win on a name clash.
    """
    merged = {}
    for path in _filter_files(FILTERS_DIR, overrides=False) + _filter_files(
        FILTERS_DIR, overrides=True
    ):
        name = _filter_name(path)
        if name:
            merged[name] = path
    return merged


def _parse_filter_output(text):
    """Parse `split/name` lines into entries, keeping only known images.

    Order is preserved and duplicates dropped. Returns (entries, skipped),
    where `skipped` counts non-blank lines that are malformed or not in the
    scanned image list.
    """
    known = {(e["split"], e["name"]) for e in STATE["images"]}
    entries, seen, skipped = [], set(), 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if "/" not in line:
            skipped += 1
            continue
        split, name = line.split("/", 1)
        key = (split, name)
        if key not in known:
            skipped += 1
            continue
        if key in seen:
            continue
        seen.add(key)
        entries.append({"split": split, "name": name})
    return entries, skipped


def run_filter(name, split):
    """Run filter `name` for `split`; return {ok, images, skipped, error}."""
    path = load_filters().get(name)
    if path is None:
        return {"ok": False, "error": f"unknown filter: {name}"}

    command = [sys.executable, path, STATE["data_yaml"] or "", split or ""]
    try:
        proc = subprocess.run(
            command, capture_output=True, text=True, timeout=FILTER_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "filter timed out"}
    except OSError as exc:
        return {"ok": False, "error": f"could not run filter: {exc}"}
    if proc.returncode != 0:
        detail = proc.stderr.strip() or f"exit code {proc.returncode}"
        return {"ok": False, "error": f"filter failed: {detail}"}

    entries, skipped = _parse_filter_output(proc.stdout)
    return {"ok": True, "images": entries, "skipped": skipped}


def _clear_filter():
    STATE["active_filter"] = None
    STATE["filter_images"] = None
    STATE["filter_error"] = None


def apply_filter(name):
    """Run `name` for the current split and cache the result in STATE.

    Returns an error message on failure (state untouched), or None on success.
    """
    result = run_filter(name, STATE["active_split"])
    if not result["ok"]:
        return result["error"]
    STATE["active_filter"] = name
    STATE["filter_images"] = result["images"]
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


def _tags_dir_for(images_dir):
    """Derive the tags dir by replacing the last `images` segment with `tags`."""
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
                "tags_dir": _tags_dir_for(images_dir),
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
            return path
    STATE["data_yaml"] = None
    STATE["splits"] = []
    STATE["images"] = []
    return None


def _current_images():
    """The images visible to the UI.

    A filter narrows the list to its own result (it already received the active
    split as an argument); otherwise the list is filtered to the active split.
    """
    if STATE["active_filter"]:
        return STATE["filter_images"] or []
    if not STATE["active_split"]:
        return STATE["images"]
    return [e for e in STATE["images"] if e["split"] == STATE["active_split"]]


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


def _normalize_tags(raw):
    """Coerce arbitrary input into a clean, de-duplicated list of tag names."""
    tags = []
    if isinstance(raw, list):
        for t in raw:
            if not isinstance(t, str):
                continue
            t = t.strip()
            if t and "\n" not in t and t not in tags:
                tags.append(t)
    return tags


def _read_tag_lines(path):
    """Read a per-image tag file: one tag name per line."""
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


def tags_yaml_path():
    """Path of the dataset's tags.yaml (beside data.yaml), or None."""
    if not STATE["data_yaml"]:
        return None
    return os.path.join(os.path.dirname(os.path.abspath(STATE["data_yaml"])), "tags.yaml")


def read_tags_yaml():
    """Read the available-tags list from the dataset's tags.yaml ([] if absent)."""
    path = tags_yaml_path()
    if not path:
        return []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    value = _extract_yaml_block(lines, "tags")
    return _parse_yaml_names_value(value or "")


def save_tags_yaml(tags):
    """Write `tags` to the dataset's tags.yaml, keeping any non-tags content.

    Rewrites only the top-level `tags:` block (or appends one); other keys are
    preserved. Returns the written path, or None when no dataset is loaded.
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

    out = []
    replaced = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if not replaced and _strip_comment(line.strip()).startswith("tags:"):
            out.append("tags:\n")
            for t in tags:
                out.append(f"  - {t}\n")
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
        out.append("tags:\n")
        for t in tags:
            out.append(f"  - {t}\n")

    text = "".join(out)
    if not text.endswith("\n"):
        text += "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


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


def _entry(idx):
    images = _current_images()
    if idx < 0 or idx >= len(images):
        abort(404)
    return images[idx]


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config")
def api_config():
    app_shortcuts, user_shortcuts, shortcut_errors = split_shortcuts(load_shortcuts())
    actions = load_actions()
    hooks, hook_errors = load_hooks()
    return jsonify(
        {
            "data_yaml": STATE["data_yaml"],
            "dataset_path": STATE["dataset_path"],
            "classes": read_classes(),
            "tags": read_tags_yaml(),
            "images": _current_images(),
            "active_split": STATE["active_split"],
            "filters": sorted(load_filters()),
            "active_filter": STATE["active_filter"],
            "filter_error": STATE["filter_error"],
            "recent_data_yamls": _load_recent(),
            "actions": [a["name"] for a in actions],
            "hooks": [h["name"] for h in hooks],
            "hook_errors": hook_errors,
            "shortcuts": app_shortcuts,
            "action_shortcuts": user_shortcuts,
            "shortcut_errors": shortcut_errors,
            "readonly": STATE["readonly"],
            "debug": STATE["debug"],
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


@app.route("/api/data", methods=["POST"])
def api_data():
    data = request.get_json(silent=True) or {}
    path = (data.get("data_yaml") or "").strip()

    if not path:
        return jsonify({"ok": False, "error": "data.yaml path is required"}), 400
    if not os.path.isfile(path):
        return jsonify({"ok": False, "error": f"not a file: {path}"}), 400

    _load_dataset(path)
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
    # A filter receives the split, so an active one must re-run for the new one.
    if STATE["active_filter"]:
        error = apply_filter(STATE["active_filter"])
        if error:
            STATE["active_split"] = previous  # keep split + filter consistent
            return jsonify({"ok": False, "error": error}), 400

    cfg = api_config().get_json()
    cfg["ok"] = True
    return jsonify(cfg)


@app.route("/api/filter", methods=["POST"])
def api_filter():
    """Set the active filter (narrows the image list), or clear it with null/empty."""
    if not STATE["splits"]:
        return jsonify({"ok": False, "error": "no dataset loaded"}), 400

    data = request.get_json(silent=True) or {}
    name = (data.get("filter") or "").strip() or None
    if name is None:
        _clear_filter()
    else:
        error = apply_filter(name)
        if error:
            return jsonify({"ok": False, "error": error}), 400

    cfg = api_config().get_json()
    cfg["ok"] = True
    return jsonify(cfg)


@app.route("/api/images/rescan", methods=["POST"])
def api_images_rescan():
    """Re-scan the image folders (e.g. after a user action deleted/added files)."""
    STATE["images"] = scan_images()
    if STATE["active_split"] and not any(
        e["split"] == STATE["active_split"] for e in STATE["images"]
    ):
        STATE["active_split"] = None
    # the flat list changed: an active filter must be re-evaluated
    if STATE["active_filter"]:
        error = apply_filter(STATE["active_filter"])
        if error:
            _clear_filter()
            STATE["filter_error"] = error
    return jsonify(
        {
            "ok": True,
            "images": _current_images(),
            "active_split": STATE["active_split"],
            "active_filter": STATE["active_filter"],
            "filter_error": STATE["filter_error"],
        }
    )


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
    idx = data.get("idx")

    if isinstance(idx, bool) or not isinstance(idx, int):
        return jsonify({"ok": False, "error": "invalid image index"}), 400

    entry = _entry(idx)  # 404 when out of range
    split = _split_by_name(entry["split"])
    if split is None:
        abort(404)

    action = next((a for a in load_actions() if a["name"] == name), None)
    if action is None:
        # Event hooks are ordinary names here (`on_<event>`), so they can be run.
        action = next((h for h in load_hooks()[0] if h["name"] == name), None)
    if action is None:
        return jsonify({"ok": False, "error": f"unknown action: {name}"}), 400

    pipe_path = create_pipe()
    values = {
        "IMAGE_PATH": os.path.join(split["images_dir"], entry["name"]),
        "LABEL_PATH": label_path(entry),
        "DATASET_PATH": STATE["dataset_path"] or "",
        "DATA_YAML_PATH": STATE["data_yaml"] or "",
        # 1-based, matching the "current / total" counter shown in the UI.
        "IMAGE_INDEX": str(idx + 1),
        # the folder holding app.py, so steps can reach scripts/ and other files
        # the same way regardless of the directory the server was started from
        "APP_DIR": BASE_DIR,
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
    }


@app.route("/api/image/<int:idx>")
def api_image(idx):
    entry = _entry(idx)
    split = _split_by_name(entry["split"])
    if split is None:
        abort(404)
    assert split is not None
    resp = send_from_directory(split["images_dir"], entry["name"])
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/labels/<int:idx>", methods=["GET", "POST"])
def api_labels(idx):
    entry = _entry(idx)
    split = _split_by_name(entry["split"])
    if split is None:
        abort(404)
    assert split is not None

    if request.method == "GET":
        boxes = _parse_label_file(label_path(entry))
        return jsonify(
            [{"class": c, "cx": cx, "cy": cy, "w": w, "h": h} for c, cx, cy, w, h in boxes]
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
    return jsonify({"ok": True, "count": len(lines)})


@app.route("/api/tags.yaml", methods=["GET", "POST"])
def api_tags_yaml():
    """Read/write the dataset's available-tags list (tags.yaml beside data.yaml)."""
    if request.method == "GET":
        return jsonify({"tags": read_tags_yaml()})

    if STATE["readonly"]:
        return jsonify({"ok": False, "error": "read-only mode"}), 403
    if not STATE["data_yaml"]:
        return jsonify({"ok": False, "error": "no dataset loaded"}), 400

    data = request.get_json(silent=True) or {}
    tags = _normalize_tags(data.get("tags"))
    path = save_tags_yaml(tags)
    if path is None:
        return jsonify({"ok": False, "error": "no dataset loaded"}), 400
    return jsonify({"ok": True, "tags_yaml": path, "tags": read_tags_yaml()})


@app.route("/api/tags/<int:idx>", methods=["GET", "POST"])
def api_tags(idx):
    """Read/write one image's tag list (its <stem>.txt under the split's tags dir)."""
    entry = _entry(idx)
    split = _split_by_name(entry["split"])
    if split is None:
        abort(404)
    assert split is not None

    if request.method == "GET":
        return jsonify({"tags": _read_tag_lines(tag_path(entry))})

    if STATE["readonly"]:
        return jsonify({"ok": False, "error": "read-only mode"}), 403

    data = request.get_json(silent=True) or {}
    tags = _normalize_tags(data.get("tags"))

    path = tag_path(entry)
    assert path is not None
    os.makedirs(split["tags_dir"], exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(tags))
        if tags:
            f.write("\n")
    return jsonify({"ok": True, "count": len(tags)})


# --------------------------------------------------------------------------- #
# entrypoint
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(description="YOLO labelling app (Flask)")
    parser.add_argument("--data", help="path to data.yaml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument(
        "--readonly",
        action="store_true",
        help="serve as a read-only viewer (no saving labels)",
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
    args = parser.parse_args()

    STATE["readonly"] = args.readonly
    STATE["debug"] = args.debug
    STATE["keep_pipe"] = args.keep_pipe

    if args.data:
        _load_dataset(args.data)
        _push_recent(STATE["data_yaml"])
    elif not args.no_resume:
        _resume_last_dataset()

    app.run(host=args.host, port=args.port, debug=True)


if __name__ == "__main__":
    main()
