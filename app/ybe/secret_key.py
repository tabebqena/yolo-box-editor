"""Persistent Flask session-signing key.

Generated once and stored in the user home, so a signed-in browser survives app
restarts and updates. The file is owner-only: holding the key is enough to forge
a session cookie.
"""

import os
import secrets

from ybe import config

_KEY_BYTES = 32  # 256 bits -> 64 hex characters


def load_or_create_secret_key():
    """Return the stored session key, creating one when it is missing.

    Reads `config.SECRET_KEY_FILE`; a missing, empty or unreadable file is
    replaced with a fresh random key written owner-only (0600). Never raises: a
    failed write still returns an in-process key so the app keeps working.
    """
    path = config.SECRET_KEY_FILE
    try:
        with open(path, encoding="utf-8") as f:
            key = f.read().strip()
        if key:
            return key
    except OSError:
        pass

    key = secrets.token_hex(_KEY_BYTES)
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(key + "\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError:
        pass
    return key
