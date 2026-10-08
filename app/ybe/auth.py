"""Login accounts: a {username: password_hash} store in the user folder.

`state.USERS` maps username -> password hash, loaded from `users.json` at
startup. Passwords are only ever stored hashed (werkzeug PBKDF2); the file is
owner-only (`0600`) because the hashes are the keys to the accounts. Login is
opt-in: an empty store means no login, and registering any account (with
`--create-user`, or from a signed-in browser) turns the gate on. The Flask
session wiring (the cookie, the before_request gate) lives in `server.py`.
"""

import getpass
import json
import os
import sys

from werkzeug.security import check_password_hash, generate_password_hash

from ybe import config, state

def _valid_username(username):
    """A username may not be empty, contain ':', or include control chars."""
    return bool(username) and ":" not in username and not any(
        ord(ch) < 32 for ch in username
    )


def load_users():
    """Load config.USERS_FILE into the state.USERS map; missing/corrupt file means none."""
    try:
        with open(config.USERS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        state.USERS = {}
        return state.USERS
    raw = data.get("users") if isinstance(data, dict) else None
    state.USERS = (
        {str(name): str(hash_) for name, hash_ in raw.items()}
        if isinstance(raw, dict)
        else {}
    )
    return state.USERS


def _write_users():
    """Persist state.USERS atomically and owner-only; returns False on failure."""
    try:
        os.makedirs(os.path.dirname(config.USERS_FILE) or ".", exist_ok=True)
        tmp = config.USERS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "users": state.USERS}, f, indent=2, sort_keys=True)
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
    """Create or update a user; returns "created" or "updated"."""
    existed = username in state.USERS
    state.USERS[username] = generate_password_hash(password)
    if not _write_users():
        raise OSError(f"could not write {config.USERS_FILE}")
    return "updated" if existed else "created"


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
    hashed = state.USERS.get(str(username))
    if not hashed:
        return False
    return check_password_hash(hashed, str(password))


def auth_enabled():
    """True when at least one user is registered and a login is required."""
    return bool(state.USERS)
