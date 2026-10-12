"""Login accounts: a `{name: {id, role, hash}}` store in the user folder.

`state.USERS` maps username -> `{id, role, hash}`, loaded from `users.json` at
startup. `id` is a stable, filesystem-safe handle (per-user folders and state
are keyed by it, so a rename never moves data). `role` is "admin" (full access)
or "user" (restricted); a lone account is always admin, and no accounts means
the local operator is the admin. Passwords are only ever stored hashed (werkzeug
PBKDF2); the file is owner-only (`0600`) because the hashes are the keys to the
accounts. Login is opt-in: an empty store means no login, and registering any
account (with `ybe users --create NAME`, or from a signed-in browser) turns the
gate on. The Flask session wiring (the cookie, the before_request gate) lives in
`server.py`.
"""

import getpass
import json
import os
import secrets
import sys

from werkzeug.security import check_password_hash, generate_password_hash

from ybe import config, state

# Account roles. "admin" gets full functionality; "user" is restricted. A lone
# account is always an admin (see `_normalize_role`), so a single-user install
# behaves exactly like one with no login at all.
ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLES = (ROLE_ADMIN, ROLE_USER)


def _valid_username(username):
    """A username may not be empty, contain ':', or include control chars."""
    return bool(username) and ":" not in username and not any(
        ord(ch) < 32 for ch in username
    )


def _new_id():
    """A stable, filesystem-safe account id (folders are keyed by this)."""
    return secrets.token_hex(8)


def _normalize_record(value):
    """Coerce a stored account value into `{id, role, hash}`, or None.

    v1 files stored a bare password hash string; v2 stores a record. A legacy
    entry keeps its hash and gains a fresh id.
    """
    if isinstance(value, str):
        return {"id": _new_id(), "role": ROLE_USER, "hash": value}
    if isinstance(value, dict):
        hash_ = value.get("hash")
        if not isinstance(hash_, str) or not hash_:
            return None
        role = value.get("role")
        return {
            "id": value.get("id") or _new_id(),
            "role": role if role in ROLES else ROLE_USER,
            "hash": hash_,
        }
    return None


def _normalize_role(users):
    """A store with exactly one account promotes it to admin (if needed)."""
    if len(users) == 1:
        (record,) = users.values()
        if record.get("role") != ROLE_ADMIN:
            record["role"] = ROLE_ADMIN
            return True
    return False


def load_users():
    """Load config.USERS_FILE into the state.USERS map; missing/corrupt file means none.

    `state.USERS` maps name -> `{id, role, hash}`. A v1 file (bare hashes) is
    migrated and rewritten once, and a lone account is promoted to admin.
    """
    try:
        with open(config.USERS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        state.USERS = {}
        return state.USERS
    raw = data.get("users") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        state.USERS = {}
        return state.USERS
    users = {}
    changed = False
    for name, value in raw.items():
        record = _normalize_record(value)
        if record is None:
            changed = True  # dropped a malformed entry
            continue
        if not isinstance(value, dict) or value.get("id") != record["id"]:
            changed = True  # legacy bare hash or a missing id
        users[str(name)] = record
    changed = _normalize_role(users) or changed
    state.USERS = users
    if changed:
        _write_users()  # persist the migration once; failure is non-fatal
    return state.USERS


def _write_users():
    """Persist state.USERS atomically and owner-only; returns False on failure."""
    try:
        os.makedirs(os.path.dirname(config.USERS_FILE) or ".", exist_ok=True)
        tmp = config.USERS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 2, "users": state.USERS}, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, config.USERS_FILE)  # atomic swap (temp file + rename)
        try:
            os.chmod(config.USERS_FILE, 0o600)  # owner-only, like the key store
        except OSError:
            pass
        return True
    except OSError:
        return False


def set_user(username, password):
    """Create or update a user; returns "created" or "updated".

    The account keeps its id and role on update. A brand-new account is admin
    when it is the first one (a lone account is admin); otherwise it is a
    restricted user.
    """
    name = str(username)
    existed = name in state.USERS
    previous = state.USERS.get(name) or {}
    first = not state.USERS
    state.USERS[name] = {
        "id": previous.get("id") or _new_id(),
        "role": previous.get("role") or (ROLE_ADMIN if first else ROLE_USER),
        "hash": generate_password_hash(password),
    }
    if not _write_users():
        raise OSError(f"could not write {config.USERS_FILE}")
    return "updated" if existed else "created"


def create_user(username, password):
    """Register a brand-new user; refuse a name that already exists."""
    if str(username) in state.USERS:
        raise ValueError(f"user {username!r} already exists")
    return set_user(username, password)


def update_user(username, password):
    """Change an existing user's password; the user must exist."""
    if str(username) not in state.USERS:
        raise KeyError(username)
    return set_user(username, password)


def delete_user(username):
    """Remove a user; the user must exist."""
    name = str(username)
    if name not in state.USERS:
        raise KeyError(name)
    del state.USERS[name]
    _normalize_role(state.USERS)  # a lone survivor becomes admin
    if not _write_users():
        raise OSError(f"could not write {config.USERS_FILE}")
    return "deleted"


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
    record = state.USERS.get(str(username))
    if not record:
        return False
    return check_password_hash(record.get("hash", ""), str(password))


def auth_enabled():
    """True when at least one user is registered and a login is required."""
    return bool(state.USERS)


def user_id(username):
    """The stable id of an account, or None when it does not exist."""
    record = state.USERS.get(str(username))
    return record.get("id") if record else None


def role_of(username):
    """The stored role of an account, or None when it does not exist."""
    record = state.USERS.get(str(username))
    return record.get("role") if record else None


def is_admin(username):
    """True when `username` has full access (anonymous counts when auth is off)."""
    if not state.USERS:
        return True  # no accounts: the local operator is the admin
    return role_of(username) == ROLE_ADMIN


def set_role(username, role):
    """Change an account's role; the role must be known and the user exist."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    name = str(username)
    if name not in state.USERS:
        raise KeyError(name)
    state.USERS[name]["role"] = role
    if not _write_users():
        raise OSError(f"could not write {config.USERS_FILE}")
    return role
