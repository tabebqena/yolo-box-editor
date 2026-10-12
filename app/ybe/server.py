"""Flask application and HTTP routes for yolo-box-editor.

Holds the `app` object, the session/login wiring and every `/api/*` route. The
server-side logic lives in the sibling `ybe` modules; `app.py` is the CLI entry
point that configures the home, loads the secret key and calls `app.run`.
"""

import functools
import os
import secrets
import sys
import time
import uuid

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    render_template,
    request,
    send_from_directory,
    session,
)
from ybe import (
    access,
    compat,
    config,
    envs,
    extension_flags,
    permissions,
    policy,
    state,
    userdata,
    userstate,
)
from ybe.auth import (
    _valid_username,
    auth_enabled,
    create_user,
    delete_user,
    is_admin,
    role_of,
    set_role,
    set_user,
    update_user,
    user_id,
    verify_user,
)
from ybe.commands import (
    _advance_execution,
    _rescan_images,
    begin_execution,
    finish_execution,
)
from ybe.dataset import (
    _current_images,
    _entry_by_key,
    _image_index,
    _load_dataset,
    _parse_label_file,
    _split_by_name,
    label_path,
    read_classes,
    scan_splits,
)
from ybe.extensions import (
    _bump_api_version_text,
    _clean_extension_entries,
    _clean_filter_arguments,
    _dump_action_file,
    _dump_filter_file,
    _extension_file_payload,
    _extension_user_dir,
    _parse_extension_text,
    _placeholder_payload,
    _safe_extension_name,
    _usable_extension_text,
    api_version_status,
    extension_file_for,
    load_actions,
    load_actions_report,
    load_filters,
    load_hooks,
    resolve_filter_options,
)
from ybe.widgets import load_widgets, sanitize_widget_values
from ybe.filters import _clear_filter, apply_filters
from ybe.packages import (
    extension_app_action_defs,
    load_packages,
    package_route_prefix,
    package_script_path,
    plugin_api_status,
)
from ybe.plugins import (
    call_capability,
    disable as disable_extension,
    dispatch as dispatch_extension_route,
    enable as enable_extension,
    is_loaded,
)
from ybe.parsing import _read_text
from ybe.pipes import create_pipe
from ybe.shortcuts import (
    _valid_shortcut,
    load_shortcuts,
    load_shortcuts_from,
    split_shortcuts,
    user_shortcut_names,
    write_user_shortcuts,
)
from ybe.update import changelog_for, check_for_update, read_version, update_status
from ybe.userconfig import (
    DISABLED_KIND_KEYS,
    _disabled_extensions,
    _load_recent,
    _load_settings,
    _push_recent,
    _save_view,
    _set_extension_disabled,
    _update_settings,
)


# The single Flask application object. Templates and static files live beside
# app.py inside the shipped `app/` folder (config.BASE_DIR), so the path works
# the same in a clone and in an install.
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
# request helpers
# --------------------------------------------------------------------------- #
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


def _current_role():
    """The request's effective role: "admin" when auth is off, else the account's."""
    if not auth_enabled():
        return "admin"
    return role_of(_session_username())


def _is_admin():
    """True when the request may author/install/run (anonymous counts when auth off)."""
    return is_admin(_session_username())


def _deny_non_admin():
    """The standard 403 for a restricted account touching an admin-only route."""
    return jsonify({"ok": False, "error": "admin permission required"}), 403


def admin_only(view):
    """Wrap a route so only an admin may call it (403 otherwise)."""

    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if not _is_admin():
            return _deny_non_admin()
        return view(*args, **kwargs)

    return wrapper


def _admin_count():
    """How many accounts currently hold the admin role."""
    return sum(1 for record in state.USERS.values()
               if record.get("role") == "admin")


def _visible_datasets():
    """Designated datasets the request may pick from (all for an admin)."""
    if _is_admin():
        return policy.datasets()
    uid = state.current_uid()
    return policy.user_datasets(uid) if uid else []


def _quota_payload():
    """The request user's label-byte cap and current usage."""
    uid = state.current_uid()
    return {
        "limit": policy.size_limit(),
        "used": userdata.user_bytes(uid) if uid else 0,
    }


@app.before_request
def _require_login():
    """Block API calls (and the SPA load) until the user has signed in.

    Runs before every request. When no account exists, login is off and this is a
    no-op. Otherwise the SPA shell, its static assets and the login/logout/
    session endpoints stay open (the browser must be able to render the sign-in
    form); everything else needs a valid session.

    Also selects the request's dataset state: the signed-in account's state (and
    a one-time hydrate from its `state.json`) or the anonymous state.
    """
    state.activate(None)  # every request starts on the anonymous state
    if not auth_enabled():
        return None
    path = request.path
    if path == "/" or path.startswith("/static/") or path in _AUTH_PUBLIC_PATHS:
        return None
    username = _session_username()
    if username:
        uid = user_id(username)
        state.activate(uid)
        userstate.ensure(uid)
        return None
    # API callers get a JSON 401; a direct page load gets a plain 401.
    if path.startswith("/api/"):
        return jsonify({"ok": False, "error": "authentication required"}), 401
    abort(401)


@app.teardown_request
def _release_user_state(exc=None):
    """Drop the request's user selection so it never leaks into the next one."""
    state.deactivate()


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
            "role": _current_role(),
            "is_admin": _is_admin(),
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


# --- admin: account management (web UI; CLI stays `ybe users`) ------------- #
def _users_payload():
    """The account list for the admin Users tab (never includes hashes)."""
    return [
        {"name": name, "id": record.get("id"), "role": record.get("role")}
        for name, record in sorted(state.USERS.items())
    ]


@app.route("/api/admin/users", methods=["GET", "POST", "DELETE"])
def api_admin_users():
    """List, create/update, or delete accounts. Admin only.

    POST body `{name, password?, role?}` creates a missing account (password
    required) or edits an existing one (password and/or role optional). The last
    admin cannot be demoted, so the store never loses its only administrator.
    """
    if not _is_admin():
        return _deny_non_admin()
    if request.method == "GET":
        return jsonify({"ok": True, "users": _users_payload()})

    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or data.get("username") or "").strip()

    if request.method == "DELETE":
        if not name:
            return jsonify({"ok": False, "error": "name is required"}), 400
        uid = user_id(name)
        try:
            delete_user(name)
        except KeyError:
            return jsonify({"ok": False, "error": "no such user"}), 404
        except OSError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500
        state.drop_user(uid)
        userstate.forget(uid)
        return jsonify({"ok": True, "users": _users_payload()})

    if not _valid_username(name):
        return jsonify(
            {"ok": False, "error": "invalid user name (no ':' or control chars)"}), 400
    role = data.get("role")
    if role is not None and role not in ("admin", "user"):
        return jsonify({"ok": False, "error": "role must be 'admin' or 'user'"}), 400
    password = data.get("password")
    exists = name in state.USERS
    if role == "user" and exists and role_of(name) == "admin" and _admin_count() <= 1:
        return jsonify({"ok": False, "error": "cannot demote the last admin"}), 400
    try:
        if exists:
            if password:
                update_user(name, str(password))
            if role is not None:
                set_role(name, role)
        else:
            if not password:
                return jsonify(
                    {"ok": False, "error": "password is required for a new user"}), 400
            create_user(name, str(password))
            if role is not None:
                set_role(name, role)
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "users": _users_payload()})


@app.route("/api/datasets/select", methods=["POST"])
def api_dataset_select():
    """Materialise an allowed dataset for the signed-in user and load it.

    The restricted-user path: the admin designates datasets, the user picks one,
    and a skeleton (symlinked images, local labels) is created under their home.
    """
    if state.STATE["readonly"]:
        return jsonify({"ok": False, "error": "read-only mode"}), 403
    uid = state.current_uid()
    if not uid:
        return jsonify({"ok": False, "error": "sign in required"}), 403
    data = request.get_json(silent=True) or {}
    dsid = str(data.get("id") or "").strip()
    try:
        path = userdata.select(uid, dsid)
    except KeyError:
        return jsonify({"ok": False, "error": "unknown dataset"}), 404
    except PermissionError:
        return jsonify({"ok": False, "error": "dataset not allowed"}), 403
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    _load_dataset(path)
    _clear_filter()  # a filter belongs to the dataset that was active
    if state.STATE["active_split"] not in {s["name"] for s in state.STATE["splits"]}:
        state.STATE["active_split"] = None
    userstate.save_current()
    cfg = api_config().get_json()
    cfg["ok"] = True
    return jsonify(cfg)


def _policy_payload():
    """The admin policy view (designated datasets, cap, per-account access)."""
    policy_data = policy.load()
    accounts = []
    for name, record in sorted(state.USERS.items()):
        uid = record.get("id")
        entry = {"name": name, "id": uid, "role": record.get("role")}
        for kind in policy.USER_KINDS:
            entry[kind] = policy.user_allowed(uid, kind)
        accounts.append(entry)
    return {
        "size_limit": policy_data["size_limit"],
        "datasets": policy_data["datasets"],
        "users": accounts,
    }


@app.route("/api/admin/policy", methods=["GET", "POST"])
@admin_only
def api_admin_policy():
    """Read or edit the admin policy (datasets, size cap, per-account access)."""
    if request.method == "GET":
        return jsonify({"ok": True, "policy": _policy_payload()})

    data = request.get_json(silent=True) or {}
    try:
        if "size_limit" in data:
            policy.set_size_limit(data["size_limit"])
        if "add_dataset" in data:
            spec = data.get("add_dataset") or {}
            policy.add_dataset(spec.get("name"), spec.get("data_yaml"))
        if "remove_dataset" in data:
            policy.remove_dataset(str(data.get("remove_dataset")))
        if "user_datasets" in data:
            spec = data.get("user_datasets") or {}
            uid = user_id(str(spec.get("name") or ""))
            if not uid:
                return jsonify({"ok": False, "error": "no such user"}), 404
            policy.set_user_datasets(uid, spec.get("datasets"))
        if "user_access" in data:
            spec = data.get("user_access") or {}
            uid = user_id(str(spec.get("name") or ""))
            if not uid:
                return jsonify({"ok": False, "error": "no such user"}), 404
            for kind in policy.USER_KINDS:
                if kind in spec:
                    policy.set_user_allowed(uid, kind, spec[kind])
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "policy": _policy_payload()})


# --- app config, settings, shortcuts, presence ----------------------------- #
def _extension_ui_payload(ui):
    """The UI-panel descriptor for `/api/config`, or None when absent."""
    if not ui:
        return None
    return {
        "title": ui.get("title") or "",
        "script": ui.get("script") or "",
        "location": ui.get("location") or "float",
        "height": ui.get("height"),
        "api_version": ui.get("api_version"),
        "status": plugin_api_status(ui.get("api_version")),
    }


@app.route("/api/config")
def api_config():
    app_shortcuts, user_shortcuts, shortcut_errors = split_shortcuts(load_shortcuts())
    actions, action_errors = load_actions_report()
    hooks, hook_errors = load_hooks()
    filters, filter_errors = load_filters()
    widgets, widget_errors = load_widgets()
    packages, package_errors = load_packages()
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
            "package": a.get("package"),
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
            "package": h.get("package"),
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
            "package": f.get("package"),
            "api_version": f["api_version"],
            "status": api_version_status(f["api_version"]),
        }
        for f in filters.values()
    ]
    widget_defs = [
        {
            "name": wgt["name"],
            "title": wgt["title"],
            "description": wgt["description"],
            "controls": wgt["controls"],
            "source": wgt["source"],
            "package": wgt.get("package"),
            "api_version": wgt["api_version"],
            "status": api_version_status(wgt["api_version"]),
        }
        for wgt in widgets.values()
    ]
    extension_packages = [
        {
            "id": p["id"],
            "name": p["name"],
            "description": p["description"],
            "version": p["version"],
            "author": p["author"],
            "active": p["active"],
            "source": p["source"],
            "parts": p["parts"],
            "settings": p["settings"],
            "events": p["events"],
            "app_actions": p["app_actions"],
            "backend": bool(p["backend"]),
            "loaded": is_loaded(p["id"]),
            "prefix": package_route_prefix(p),
            "route_prefix": config.EXTENSION_ROUTE_PREFIX + "/" + package_route_prefix(p),
            "permissions": p["permissions"],
            "permission_lines": permissions.describe(p["permissions"]),
            "permission_errors": p["permission_errors"],
            "permission_unknown": p["permission_unknown"],
            "ui": _extension_ui_payload(p["ui"]),
            "api_version": p["api_version"],
            "status": api_version_status(p["api_version"]),
            "environment": envs.resolve(p),
        }
        for p in packages
    ]
    ext_app_actions = extension_app_action_defs()
    if not _is_admin():
        # A restricted account only sees (and may run) what its allowlists grant.
        def _pkg_ok(package):
            return bool(package) and access.package_allowed(package)

        action_defs = [d for d in action_defs
                       if access.allowed("actions", d["name"]) or _pkg_ok(d.get("package"))]
        hook_defs = [h for h in hook_defs
                     if access.allowed("hooks", h["name"]) or _pkg_ok(h.get("package"))]
        filter_defs = [f for f in filter_defs
                       if access.allowed("filters", f["name"]) or _pkg_ok(f.get("package"))]
        widget_defs = [w for w in widget_defs
                       if access.allowed("widgets", w["name"]) or _pkg_ok(w.get("package"))]
        extension_packages = [p for p in extension_packages
                              if access.package_allowed(p["id"])]
        allowed_filters = {f["name"] for f in filter_defs}
        filter_catalog = [f for f in filter_catalog if f["name"] in allowed_filters]
    return jsonify(
        {
            "data_yaml": state.STATE["data_yaml"],
            "dataset_path": state.STATE["dataset_path"],
            "classes": classes,
            "images": _current_images(),
            "active_split": state.STATE["active_split"],
            "filters": filter_catalog,
            "filter_defs": filter_defs,
            "active_filters": state.STATE["active_filters"],
            "filter_error": state.STATE["filter_error"],
            "filter_errors": filter_errors,
            "recent_data_yamls": _load_recent(),
            "settings": _load_settings(),
            "tips": config.TIPS,
            "actions": [d["name"] for d in action_defs if d["enabled"]],
            "action_defs": action_defs,
            "action_errors": action_errors,
            "hooks": [h["name"] for h in hook_defs if h["enabled"]],
            "hook_defs": hook_defs,
            "hook_errors": hook_errors,
            "widget_defs": widget_defs,
            "widget_errors": widget_errors,
            "extension_packages": extension_packages,
            "package_errors": package_errors,
            "app_actions": sorted(config.APP_ACTIONS) + [d["id"] for d in ext_app_actions],
            "extension_app_actions": ext_app_actions,
            "backend_actions": sorted(config.BACKEND_ACTION_NAMES),
            "hook_events": list(config.HOOK_EVENTS),
            "extension_api_version": config.EXTENSION_API_VERSION,
            "plugin_api_version": config.PLUGIN_API_VERSION,
            "api_support": compat.support_table(),
            "plugin_permissions": permissions.YBE_PERMISSIONS,
            "plugin_permission_map": permissions.YBE_METHOD_PERMISSIONS,
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
                "role": _current_role(),
                "is_admin": _is_admin(),
            },
            "datasets": [
                {"id": d["id"], "name": d["name"]} for d in _visible_datasets()
            ],
            "quota": _quota_payload(),
            "version": read_version(),
            "changelog": changelog_for(read_version()),
            "update": update_status(),
            "splits": [
                {
                    "name": s["name"],
                    "images_dir": s["images_dir"],
                    "labels_dir": s["labels_dir"],
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


# --- dataset, split and filter selection ----------------------------------- #
@app.route("/api/data", methods=["POST"])
@admin_only
def api_data():
    data = request.get_json(silent=True) or {}
    path = (data.get("data_yaml") or "").strip()

    if not path:
        return jsonify({"ok": False, "error": "data.yaml path is required"}), 400
    if not os.path.isfile(path):
        return jsonify({"ok": False, "error": f"not a file: {path}"}), 400

    _load_dataset(path)
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
    userstate.save_current()

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
    userstate.save_current()
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

    names = [(i.get("name") if isinstance(i, dict) else i) for i in items]
    if not _is_admin() and any(not access.filter_allowed(n) for n in names):
        return jsonify({"ok": False, "error": "filter not allowed"}), 403

    error = apply_filters(items)
    if error:
        return jsonify({"ok": False, "error": error}), 400

    _save_view(state.STATE["data_yaml"], state.STATE["active_split"], state.STATE["active_filters"])
    userstate.save_current()
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


# --- actions and extension authoring --------------------------------------- #
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

    if not access.action_allowed(name):
        return jsonify({"ok": False, "error": "action not allowed"}), 403

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
    values = _image_action_values(entry, split)
    # scratch file shared by every step and after_success action of this run
    values["PIPE_PATH"] = pipe_path or ""
    run, status, detail = begin_execution(action, name, values, pipe_path)
    return _execution_response(run, status, detail)


def _image_action_values(entry, split):
    """The placeholder values shared by action and widget runs on one image."""
    # 1-based, matching the "current / total" counter shown in the UI; 0 when the
    # target is not part of the visible list (e.g. an off-filter image).
    position = _image_index(entry)
    return {
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
    }


@app.route("/api/widgets/run", methods=["POST"])
def api_widget_run():
    """Run one button of a custom widget on the current image.

    Body `{widget, control, target, values}`: `control` is the button's index in
    the widget's `controls` list and `values` are the widget's current control
    values (exposed as `{WIDGET_<ID>}` placeholders). The run reuses the action
    engine, so it pauses at each client (`app_*`) action exactly like
    `/api/actions/run`.
    """
    data = request.get_json(silent=True) or {}
    widget_name = (data.get("widget") or "").strip()
    target = (data.get("target") or "").strip()
    widget = load_widgets()[0].get(widget_name)
    if widget is None:
        return jsonify({"ok": False, "error": f"unknown widget: {widget_name}"}), 400
    if not access.widget_allowed(widget_name, widget.get("package")):
        return jsonify({"ok": False, "error": "widget not allowed"}), 403
    control = _pick_control(widget["controls"], data.get("control"))
    if control is None:
        return jsonify({"ok": False, "error": "unknown widget button"}), 400
    label = f"{widget_name}: {control.get('label') or 'Run'}"
    return _execute_control(control, label, target, data.get("values"),
                            widget.get("package"))


@app.route("/api/extensions/run", methods=["POST"])
def api_extensions_run():
    """Run one button of an extension package's `settings:` block.

    Body `{package, control, target, values}`; same contract as
    `/api/widgets/run` but sourced from the package manifest's declarative
    settings controls.
    """
    data = request.get_json(silent=True) or {}
    pid = (data.get("package") or "").strip()
    pkg = next((p for p in load_packages()[0] if p["id"] == pid), None)
    if pkg is None:
        return jsonify({"ok": False, "error": f"unknown package: {pid}"}), 400
    if not access.package_allowed(pid):
        return jsonify({"ok": False, "error": "extension not allowed"}), 403
    settings = pkg.get("settings") or {}
    control = _pick_control(settings.get("controls") or [], data.get("control"))
    if control is None:
        return jsonify({"ok": False, "error": "unknown package button"}), 400
    label = f"{pkg['name']}: {control.get('label') or 'Run'}"
    return _execute_control(control, label, (data.get("target") or "").strip(),
                            data.get("values"), pid)


def _pick_control(controls, raw_index):
    """Resolve a submitted button index to its control dict, or None."""
    try:
        index = int(raw_index)
    except (TypeError, ValueError):
        return None
    if index < 0 or index >= len(controls):
        return None
    control = controls[index]
    if control.get("type") != "button":
        return None
    return control


def _execute_control(control, name, target, raw_values, package=None):
    """Run a widget/package button through the action engine."""
    entry = _entry_by_key(target)
    if entry is None:
        return (
            jsonify({"ok": False, "error": f"image not in the current list: {target}"}),
            400,
        )
    split = _split_by_name(entry["split"])
    if split is None:
        abort(404)

    values, error = sanitize_widget_values(raw_values)
    if error:
        return jsonify({"ok": False, "error": error}), 400

    action = {
        "name": name,
        "steps": list(control.get("steps") or []),
        "after_success": list(control.get("after_success") or []),
        "package": package,
    }
    if control.get("action"):
        # A named action: expand its steps/after_success here, so the button
        # behaves exactly like a toolbar action with extra {WIDGET_*} values.
        named = next((a for a in load_actions() if a["name"] == control["action"]), None)
        if named is None:
            return jsonify({"ok": False, "error": f"unknown action: {control['action']}"}), 400
        if not access.action_ref_allowed(control["action"]):
            return jsonify({"ok": False, "error": "action not allowed"}), 403
        action["steps"] = list(named["steps"]) + action["steps"]
        action["after_success"] = list(named["after_success"]) + action["after_success"]
        # Prefer the named action's own package so {EXT_*} resolves correctly.
        action["package"] = named.get("package") or package

    pipe_path = create_pipe()
    run_values = _image_action_values(entry, split)
    run_values["PIPE_PATH"] = pipe_path or ""
    run_values.update(values)
    run, status, detail = begin_execution(action, name, run_values, pipe_path)
    return _execution_response(run, status, detail)


def _resume_execution(uid, data):
    """Resume a paused execution after the UI ran its `client_action`."""
    run = state.EXECUTIONS.get(uid)
    if run is None:
        return jsonify({"ok": False, "error": "unknown or expired execution"}), 400
    if run.get("owner") != state.current_uid() and not access.current_is_admin():
        return jsonify({"ok": False, "error": "not your execution"}), 403

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
        run["owner"] = state.current_uid()
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
@admin_only
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
@admin_only
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
@admin_only
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
@admin_only
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
@admin_only
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
    if not _usable_extension_text(kind, parsed):
        return jsonify(
            {"ok": False, "error": "the file is not a usable extension "
             "(no steps / after_success, or no valid controls)"}
        ), 400

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


@app.route("/api/extensions/script")
@admin_only
def api_extension_script():
    """Serve an extension package's sandboxed UI-panel script.

    The host app fetches this text (the sandboxed iframe has no network of its
    own) and inlines it into a generated wrapper. Only active packages are
    served, and the resolved path must stay inside the package folder.
    """
    pid = (request.args.get("package") or "").strip()
    pkg = next((p for p in load_packages()[0] if p["id"] == pid and p["active"]), None)
    if pkg is None or not pkg.get("ui"):
        return jsonify({"ok": False, "error": "unknown or inactive package"}), 404
    path = package_script_path(pkg)
    if path is None:
        return jsonify({"ok": False, "error": "panel script not found"}), 404
    return Response(
        _read_text(path),
        mimetype="text/javascript",
        headers={"Cache-Control": "no-store"},
    )


@app.route("/api/extensions/active", methods=["POST"])
@admin_only
def api_extension_active():
    """Enable or disable a package, live and persisted.

    Body `{"package": "<id>", "active": true|false}`. The per-user override is
    written and the package's backend (routes + capabilities) is loaded or
    unloaded in place, with no restart. This is a user preference, not a dataset
    write, so read-only does not block it.
    """
    data = request.get_json(silent=True) or {}
    pid = (data.get("package") or "").strip()
    if not pid:
        return jsonify({"ok": False, "error": "package is required"}), 400
    active = bool(data.get("active"))
    if active:
        extension_flags.set_flag(pid, True)
        loaded = enable_extension(app, pid)
    else:
        disable_extension(pid)
        extension_flags.set_flag(pid, False)
        loaded = False
    return jsonify({"ok": True, "package": pid, "active": active, "loaded": loaded})


@app.route("/api/extensions/env", methods=["POST"])
@admin_only
def api_extension_env():
    """Build (or refresh) a package's Python environment.

    Body `{"package": "<id>"}`. Creates the package's virtualenv and installs its
    `requirements:` (or installs into the interpreter the manifest names). This
    can take a while (pip/network), so the UI shows a spinner. Like the active
    toggle this is a user preference, not a dataset write, so read-only does not
    block it.
    """
    data = request.get_json(silent=True) or {}
    pid = (data.get("package") or "").strip()
    pkg = next((p for p in load_packages()[0] if p["id"] == pid), None)
    if pkg is None:
        return jsonify({"ok": False, "error": f"unknown package: {pid}"}), 400
    result = envs.setup(pkg)
    payload = {
        "ok": result["ok"],
        "mode": result["mode"],
        "environment": envs.resolve(pkg),
        "log": result["log"],
    }
    if not result["ok"]:
        payload["error"] = result["error"]
        return jsonify(payload), 500
    return jsonify(payload)


@app.route("/api/extensions/call", methods=["POST"])
def api_extension_call():
    """Call one backend capability of an active package (headless fallback).

    Used by the host when an extension app action runs with its panel unmounted,
    and available to any authenticated caller. Read-only is enforced inside the
    capability, not here.
    """
    data = request.get_json(silent=True) or {}
    pid = (data.get("package") or "").strip()
    method = (data.get("method") or "").strip()
    args = data.get("args")
    if not access.package_allowed(pid):
        return jsonify({"ok": False, "error": "extension not allowed"}), 403
    if not is_loaded(pid):
        return jsonify({"ok": False, "error": "unknown or disabled package"}), 404
    try:
        value = call_capability(pid, method, args if isinstance(args, list) else [])
    except Exception as exc:  # noqa: BLE001 - report the capability's own error
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "value": value})


# Startup catch-all for extension-declared routes. It is the only rule that
# serves extension HTTP endpoints, so packages can be enabled/disabled at
# runtime without touching Flask's URL map. Static core rules always win
# (Werkzeug ranks them above this converter rule).
def _package_for_subpath(subpath):
    """The id of the package whose route prefix owns `subpath`, or None."""
    for pkg in load_packages()[0]:
        prefix = package_route_prefix(pkg)
        if subpath == prefix or subpath.startswith(prefix + "/"):
            return pkg["id"]
    return None


@app.route(
    "/api/<path:subpath>",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    endpoint="api_extension_dispatch",
)
def api_extension_dispatch(subpath):
    pid = _package_for_subpath(subpath)
    if pid is not None and not access.package_allowed(pid):
        return jsonify({"ok": False, "error": "extension not allowed"}), 403
    return dispatch_extension_route(request.method, "/api/" + subpath)


# --- single image and its annotations -------------------------------------- #
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
    """Read/write one image's annotations: its boxes (labels).

    GET returns `{"boxes": [...]}`. POST writes the label file. Tags live in the
    tags extension package (`/api/tags`).
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
    content = "\n".join(lines) + ("\n" if lines else "")
    if not userdata.within_quota(state.current_uid(), path, len(content)):
        return jsonify(
            {"ok": False, "error": "storage limit reached; ask an admin"}
        ), 413
    os.makedirs(split["labels_dir"], exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    payload = {"ok": True, "count": len(lines)}
    return jsonify(payload)
