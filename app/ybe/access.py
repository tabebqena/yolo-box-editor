"""Role-based run access for restricted accounts.

An admin may run anything. A restricted account may run only what its policy
allowlists grant, plus the built-in client-side (`app_*`) and backend
(`backend_*`) actions, which never touch the shell. Nested `action_<Name>`
references are checked too (see `commands.py`), so an allowed action cannot
smuggle in a disallowed one.
"""

from ybe import config, policy, state


def current_is_admin():
    """True when the active request may run anything (anonymous counts when off)."""
    if not state.USERS:
        return True
    uid = state.current_uid()
    if not uid:
        return False
    return any(
        record.get("id") == uid and record.get("role") == "admin"
        for record in state.USERS.values()
    )


def allowed(kind, name):
    """True when the active account may use `name` for allowlist `kind`."""
    if current_is_admin():
        return True
    uid = state.current_uid()
    if not uid:
        return False
    return str(name) in policy.user_allowed(uid, kind)


def action_allowed(name):
    """Whether the active request may run an action or hook by `name`."""
    if current_is_admin():
        return True
    name = str(name)
    if name in config.APP_ACTIONS or name.startswith("app_"):
        return True  # client-side editor actions, never shell
    if name in config.BACKEND_ACTION_NAMES:
        return True
    prefix = config.EXTENSION_ACTION_PREFIX
    if name.startswith(prefix):
        pid = name[len(prefix):].split(".", 1)[0]
        return allowed("extensions", pid)
    uid = state.current_uid()
    if not uid:
        return False
    return (name in policy.user_allowed(uid, "actions")
            or name in policy.user_allowed(uid, "hooks"))


def action_ref_allowed(name):
    """Whether a nested `action_<Name>` reference may run."""
    return allowed("actions", name)


def package_allowed(pid):
    """Whether the active account may use an extension package."""
    return allowed("extensions", pid)


def widget_allowed(name, package=None):
    """Whether a widget button may run (by its own name or its package)."""
    if allowed("widgets", name):
        return True
    return bool(package) and allowed("extensions", package)


def filter_allowed(name):
    """Whether a filter may be applied by the active account."""
    return allowed("filters", name)
