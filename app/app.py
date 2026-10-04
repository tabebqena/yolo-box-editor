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
import os
import secrets
import sys
import time
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

from ybe import auth, config, state, update
from ybe.auth import (
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USER,
    _prompt_password,
    _valid_username,
    auth_enabled,
    ensure_default_admin,
    load_users,
    set_user,
    verify_user,
)
from ybe.commands import (
    BACKEND_ACTIONS,
    _advance_execution,
    _rescan_images,
    _resolve_entry,
    _run_command,
    begin_execution,
    finish_execution,
)
from ybe.config import configure_home, ensure_user_dirs
from ybe.dataset import (
    _current_images,
    _entry_by_key,
    _image_index,
    _labels_dir_for,
    _load_dataset,
    _parse_label_file,
    _split_by_name,
    _tags_dir_for,
    is_image,
    label_path,
    read_classes,
    scan_images,
    scan_splits,
    tag_path,
)
from ybe.filters import (
    _clear_filter,
    _known_image_paths,
    _normalize_filter_chain,
    _parse_filter_output,
    apply_filters,
    run_filter,
    run_filter_chain,
)
from ybe.extensions import (
    FILTER_CLASS_NAMES_TOKEN,
    _bump_api_version_text,
    _clean_extension_entries,
    _clean_filter_arguments,
    _dump_action_file,
    _dump_filter_file,
    _extension_file_payload,
    _extension_user_dir,
    _parse_action_file,
    _parse_extension_text,
    _parse_filter_file,
    _placeholder_payload,
    _safe_extension_name,
    api_version_status,
    effective_filter_arguments,
    extension_file_for,
    is_hook_name,
    load_actions,
    load_filters,
    load_hooks,
    resolve_filter_options,
)
from ybe.logging_setup import _SkipPresenceFilter, setup_logging
from ybe.secret_key import load_or_create_secret_key
from ybe.pipes import (
    _subprocess_env,
    build_command,
    create_pipe,
    is_pipe_path,
    remove_pipe,
)
from ybe.shortcuts import (
    _valid_shortcut,
    load_shortcuts,
    load_shortcuts_from,
    split_shortcuts,
    user_shortcut_names,
    write_user_shortcuts,
)
from ybe.tags import (
    read_tags_yaml,
    register_available_tags,
    save_tags_yaml,
    tags_yaml_path,
    write_image_tags,
)
from ybe.userconfig import (
    DISABLED_KIND_KEYS,
    _disabled_extensions,
    _load_recent,
    _load_settings,
    _load_views,
    _push_recent,
    _restore_tags_dir,
    _restore_view,
    _save_view,
    _set_extension_disabled,
    _update_settings,
)
from ybe.update import (
    _http_get_text,
    _update_payload,
    changelog_for,
    check_for_update,
    fetch_latest_version,
    load_changes,
    parse_changes,
    read_version,
    start_update_checker,
    update_status,
)


app = Flask(
    __name__,
    template_folder=os.path.join(config.BASE_DIR, "templates"),
    static_folder=os.path.join(config.BASE_DIR, "static"),
)
# Signs the login session cookie. This import-time value is an ephemeral
# fallback (used by the test client); `main()` replaces it with the persistent
# key from `config.SECRET_KEY_FILE`, so a real run keeps sessions across
# restarts and app updates.
app.secret_key = secrets.token_hex(32)


# --------------------------------------------------------------------------- #
# dataset resume
# --------------------------------------------------------------------------- #
def _resume_last_dataset():
    """Activate the most recent still-existing data.yaml; None when there is none.

    Used at startup when `--data` is omitted, so a plain `python app.py` returns
    to the dataset last opened (the newest entry of `.recent_data_yamls.json`).
    """
    for path in _load_recent():
        if os.path.isfile(path) and _load_dataset(path):
            _restore_view(state.STATE["data_yaml"])
            return path
    state.STATE["data_yaml"] = None
    state.STATE["splits"] = []
    state.STATE["images"] = []
    return None


def _request_entry():
    """Resolve the `?key=split/name` query string to an image entry, or 404."""
    entry = _entry_by_key(request.args.get("key", ""))
    if entry is None:
        abort(404)
    return entry


def _prune_clients(now=None):
    """Forget clients that have not pinged `/api/presence` within state.PRESENCE_TTL."""
    now = time.monotonic() if now is None else now
    for cid in [c for c, seen in state.CLIENTS.items() if now - seen > state.PRESENCE_TTL]:
        state.CLIENTS.pop(cid, None)
    return len(state.CLIENTS)


# --------------------------------------------------------------------------- #
# authentication: the Flask session wiring (the account store lives in ybe.auth)
# --------------------------------------------------------------------------- #
# Paths served without a session so the login page itself can load. Everything
# else under /api/ answers 401 until the user signs in; the SPA shell and its
# static assets are public so the login form can be rendered.
_AUTH_PUBLIC_PATHS = {"/api/login", "/api/session", "/api/logout"}


def _session_username():
    """The signed-in username, if it still exists in the store."""
    user = session.get("ybe_user")
    return user if user in state.USERS else None


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
            "data_yaml": state.STATE["data_yaml"],
            "dataset_path": state.STATE["dataset_path"],
            "classes": classes,
            "tags": read_tags_yaml(),
            "images": _current_images(),
            "active_split": state.STATE["active_split"],
            "filters": filter_catalog,
            "filter_defs": filter_defs,
            "active_filters": state.STATE["active_filters"],
            "filter_error": state.STATE["filter_error"],
            "filter_errors": filter_errors,
            "recent_data_yamls": _load_recent(),
            "settings": _load_settings(),
            "tags_dir": state.STATE.get("tags_dir"),
            "tips": config.TIPS,
            "actions": [a["name"] for a in actions if a["name"] not in disabled["action"]],
            "action_defs": action_defs,
            "hooks": [h["name"] for h in hooks if h["name"] not in disabled["hook"]],
            "hook_defs": hook_defs,
            "hook_errors": hook_errors,
            "app_actions": sorted(config.APP_ACTIONS),
            "backend_actions": sorted(config.BACKEND_ACTION_NAMES),
            "hook_events": list(config.HOOK_EVENTS),
            "extension_api_version": config.EXTENSION_API_VERSION,
            "placeholders": {
                "action": _placeholder_payload(config.ACTION_PLACEHOLDERS),
                "filter": _placeholder_payload(config.FILTER_PLACEHOLDERS),
            },
            "shortcuts": app_shortcuts,
            "action_shortcuts": user_shortcuts,
            "shortcut_errors": shortcut_errors,
            "shortcut_defaults": load_shortcuts_from(config.SHORTCUTS_FILE),
            "user_shortcut_names": sorted(user_shortcut_names()),
            "readonly": state.STATE["readonly"],
            "debug": state.STATE["debug"],
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
                for s in state.STATE["splits"]
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
    if state.STATE["readonly"]:
        return jsonify({"ok": False, "error": "read-only mode"}), 403

    data = request.get_json(silent=True) or {}
    sets = data.get("set") or {}
    resets = data.get("reset") or []
    if not isinstance(sets, dict) or not isinstance(resets, list):
        return jsonify({"ok": False, "error": "set must be an object and reset a list"}), 400

    known = set(config.APP_ACTIONS) | {a["name"] for a in load_actions()}
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
    of clients seen within state.PRESENCE_TTL seconds; the UI warns while it is > 1.
    Presence never blocks any other request.
    """
    data = request.get_json(silent=True) or {}
    cid = (data.get("cid") or "").strip()
    if not cid:
        return jsonify({"ok": False, "error": "client id is required"}), 400

    now = time.monotonic()
    with state.CLIENTS_LOCK:
        if data.get("bye"):
            state.CLIENTS.pop(cid, None)
        else:
            state.CLIENTS[cid] = now
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
    _restore_tags_dir(state.STATE["data_yaml"])  # re-apply this dataset's tags folder
    _clear_filter()  # a filter belongs to the dataset that was active
    names = {s["name"] for s in state.STATE["splits"]}
    if state.STATE["active_split"] not in names:
        state.STATE["active_split"] = None

    if not state.STATE["splits"]:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "data.yaml parsed, but no train/val/test image folders were found",
                }
            ),
            400,
        )

    _push_recent(state.STATE["data_yaml"])

    cfg = api_config().get_json()
    cfg["ok"] = True
    return jsonify(cfg)


@app.route("/api/split", methods=["POST"])
def api_split():
    """Restrict navigation to a single split (or all splits when `split` is empty/null)."""
    data = request.get_json(silent=True) or {}
    split = (data.get("split") or "").strip() or None
    names = {s["name"] for s in state.STATE["splits"]}
    if split is not None and split not in names:
        return jsonify({"ok": False, "error": f"unknown split: {split}"}), 400

    previous = state.STATE["active_split"]
    state.STATE["active_split"] = split
    # The chain's first filter receives the split, so an active one must re-run.
    if state.STATE["active_filters"]:
        error = apply_filters(state.STATE["active_filters"])
        if error:
            state.STATE["active_split"] = previous  # keep split + filter consistent
            return jsonify({"ok": False, "error": error}), 400

    _save_view(state.STATE["data_yaml"], state.STATE["active_split"], state.STATE["active_filters"])
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
    if not state.STATE["splits"]:
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

    _save_view(state.STATE["data_yaml"], state.STATE["active_split"], state.STATE["active_filters"])
    cfg = api_config().get_json()
    cfg["ok"] = True
    return jsonify(cfg)


def _images_payload():
    """The image-list part of a config/rescan reply (no filesystem access)."""
    return {
        "ok": True,
        "images": _current_images(),
        "active_split": state.STATE["active_split"],
        "active_filters": state.STATE["active_filters"],
        "filter_error": state.STATE["filter_error"],
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
        "DATASET_PATH": state.STATE["dataset_path"] or "",
        "DATA_YAML_PATH": state.STATE["data_yaml"] or "",
        "IMAGE_INDEX": str(position or 0),
        # the folder holding app.py (shipped files); script folders are exposed
        # both explicitly and relatively (cwd is HOME_DIR, so scripts/… works)
        "APP_DIR": config.BASE_DIR,
        "HOME_DIR": config.YBX_HOME,
        "APP_SCRIPT_DIR": config.APP_SCRIPT_DIR,
        "USER_SCRIPT_DIR": config.USER_SCRIPT_DIR,
        # the interpreter running the app; use {PYTHON} so steps work even when
        # `python` is not on PATH
        "PYTHON": sys.executable,
        # scratch file shared by every step and after_success action of this run
        "PIPE_PATH": pipe_path or "",
    }
    run, status, detail = begin_execution(action, name, values, pipe_path)
    return _execution_response(run, status, detail)


def _resume_execution(uid, data):
    """Resume a paused execution after the UI ran its `client_action`."""
    run = state.EXECUTIONS.get(uid)
    if run is None:
        return jsonify({"ok": False, "error": "unknown or expired execution"}), 400

    result = data.get("result") or {}
    if not result.get("ok", True):
        failed = run.get("pending") or "after_success"
        error = result.get("error") or "app action failed"
        finish_execution(run)
        payload = _execution_payload(run)
        payload["ok"] = False
        payload["error"] = f'after_success "{failed}" failed: {error}'
        return jsonify(payload), 200

    run["pending"] = None
    status, detail = _advance_execution(run)
    return _execution_response(run, status, detail)


def _execution_response(run, status, detail):
    """Reply for a start/advance result: pause at a client action, or finish."""
    if status == "client":
        uid = uuid.uuid4().hex
        run["uid"] = uid
        run["pending"] = detail
        state.EXECUTIONS[uid] = run
        payload = {"ok": True, "uid": uid, "client_action": detail}
        payload.update(_execution_payload(run))
        return jsonify(payload)

    finish_execution(run)
    payload = _execution_payload(run)
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


def _execution_payload(run):
    """The user-visible result shared by the paused and final replies."""
    return {
        "action": run["action"],
        "command": " && ".join(run["commands"]),
        "exit_code": run["exit_code"],
        "stdout": "\n".join(run["stdout"]),
        "stderr": "\n".join(run["stderr"]),
        "pipe_path": run["pipe_path"],
        "cwd": run.get("cwd"),
    }


@app.route("/api/actions/save", methods=["POST"])
def api_action_save():
    """Create (or replace) a user action from the Settings form.

    Body `{name, steps, after_success, overwrite}`. The file is written to the
    user actions/ folder as `<name>.yaml`; an existing user file needs
    `overwrite: true`. Read-only is refused.
    """
    if state.STATE["readonly"]:
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

    os.makedirs(config.USER_ACTIONS_DIR, exist_ok=True)
    target = os.path.join(config.USER_ACTIONS_DIR, name + ".yaml")
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
    if state.STATE["readonly"]:
        return jsonify({"ok": False, "error": "read-only mode"}), 403
    data = request.get_json(silent=True) or {}
    event = str(data.get("event") or "").strip()
    if event not in config.HOOK_EVENTS:
        return jsonify({"ok": False, "error": f"unknown hook event: {event}"}), 400
    steps, error = _clean_extension_entries(data.get("steps"))
    if error:
        return jsonify({"ok": False, "error": error}), 400
    after, error = _clean_extension_entries(data.get("after_success"))
    if error:
        return jsonify({"ok": False, "error": error}), 400
    if not steps and not after:
        return jsonify({"ok": False, "error": "add at least one step"}), 400

    os.makedirs(config.USER_HOOKS_DIR, exist_ok=True)
    target = os.path.join(config.USER_HOOKS_DIR, config.HOOK_PREFIX + event + ".yaml")
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
    if state.STATE["readonly"]:
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

    os.makedirs(config.USER_FILTERS_DIR, exist_ok=True)
    target = os.path.join(config.USER_FILTERS_DIR, name + ".yaml")
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
    if not state.STATE["data_yaml"]:
        return jsonify({"ok": False, "error": "load a dataset first"}), 400
    _set_extension_disabled(kind, name, bool(data.get("disabled")))

    cfg = api_config().get_json()
    cfg["ok"] = True
    return jsonify(cfg)


@app.route("/api/extensions/delete", methods=["POST"])
def api_extension_delete():
    """Delete one of the user's extension files (never a shipped one)."""
    if state.STATE["readonly"]:
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
    if state.STATE["readonly"]:
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

    if state.STATE["readonly"]:
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
    if not state.STATE["splits"]:
        return jsonify({"ok": False, "error": "no dataset loaded"}), 400
    if state.STATE["readonly"]:
        return jsonify({"ok": False, "error": "read-only mode"}), 403

    data = request.get_json(silent=True) or {}
    raw = (data.get("tags_dir") or "").strip()
    path = os.path.abspath(os.path.expanduser(raw)) if raw else None
    if path and not os.path.isdir(path):
        return jsonify({"ok": False, "error": f"not a folder: {path}"}), 400

    state.STATE["tags_dir"] = path
    state.STATE["splits"] = scan_splits()
    if state.STATE["active_filters"]:
        error = apply_filters(state.STATE["active_filters"])
        if error:
            state.STATE["filter_error"] = error
    _save_view(state.STATE["data_yaml"], state.STATE["active_split"], state.STATE["active_filters"])
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

    app.secret_key = load_or_create_secret_key()

    log = setup_logging(args.log_file, args.debug)
    log.info(
        "yolo-box-editor %s | user dir: %s (override with --home)", read_version(), config.YBX_HOME
    )

    state.STATE["readonly"] = args.readonly
    state.STATE["debug"] = args.debug
    state.STATE["keep_pipe"] = args.keep_pipe
    state.STATE["keep_filter_pipes"] = args.keep_filter_pipes
    state.STATE["no_update_check"] = args.no_update_check

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
        for name in sorted(state.USERS):
            print(name)
        if not state.USERS:
            print(f"(no users registered in {config.USERS_FILE})")
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
        print(f"{action} user {username!r} in {config.USERS_FILE}")
        return

    start_update_checker()

    if args.data:
        _load_dataset(args.data)
        _push_recent(state.STATE["data_yaml"])
    elif not args.no_resume:
        _resume_last_dataset()

    log.info("serving on http://%s:%s", args.host, args.port)
    app.run(host=args.host, port=args.port, debug=True, use_reloader=not args.no_reload)


if __name__ == "__main__":
    main()
