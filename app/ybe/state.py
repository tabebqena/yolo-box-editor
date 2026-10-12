"""Mutable, process-wide runtime state.

The loaded dataset is held per user, not in one global dict: `state.STATE` is a
dict-like proxy (see `_StateProxy`) that resolves to the *active* user's state.
`before_request` calls `activate(<user id>)` so every existing `state.STATE[...]`
call site keeps working while operating on that user's dataset. Outside a
request (startup, background threads, tests) it falls back to the anonymous
state, which is what a single-user install uses.

CLI flags (`readonly`, `debug`, …) stay process-wide in `PROCESS`: they apply to
every user and are read/written through the same proxy, so `STATE["readonly"]`
behaves exactly as before.

Tests replace/reset these containers, so callers must use module attribute
access rather than importing a name directly.
"""

import contextvars
import threading

# Persistent login accounts as a {username: {id, role, hash}} map, loaded from
# USERS_FILE at startup. Empty (the default) means login is off and the local
# operator is the admin; any entry turns the gate on. Passwords are only ever
# stored hashed. `id` is a stable handle for per-user folders/state; `role` is
# "admin" or "user". See ybe/auth.py.
USERS = {}

# The shape of one user's state. The dataset keys are per user; the flag keys
# are process-wide and live in `PROCESS` (never in a user's dict).
_DEFAULT = {
    "data_yaml": None,
    "dataset_path": None,
    "splits": [],   # [{"name": "train", "images_dir": ..., "labels_dir": ...}]
    "images": [],   # flat navigation list: [{"split": "train", "name": "a.jpg"}]
    "active_split": None,  # None = all splits; or a single split name
    "active_filters": [],   # chain of {name, arguments} from filters/ ([] = none)
    "filter_images": None,  # cached filter-chain result (list of {split, name})
    "filter_error": None,   # last filter failure/notice message (shown in the UI)
    "classes": [],  # resolved class names from data.yaml `names`
    "readonly": False,
    "debug": False,  # --debug: the UI logs verbose messages to the browser console
    "keep_pipe": False,  # --keep-pipe: do not delete the {PIPE_PATH} file after a run
    "keep_filter_pipes": False,  # --keep-filter-pipes: keep the filter scratch dir
    "no_update_check": False,  # --no-update-check: never check GitHub for updates
}

# CLI flags shared by every user (set once at startup in `main()`).
PROCESS_FLAG_KEYS = (
    "readonly", "debug", "keep_pipe", "keep_filter_pipes", "no_update_check",
)
PROCESS = {key: _DEFAULT[key] for key in PROCESS_FLAG_KEYS}

# The anonymous state, used when no account is signed in (and outside requests).
ANONYMOUS_STATE = dict(_DEFAULT)

# Live per-account state, keyed by account id (see auth.user_id).
USER_STATES = {}
USER_STATES_LOCK = threading.RLock()

# The account id whose state the current request/thread should use; None means
# the anonymous state.
_active_uid = contextvars.ContextVar("ybe_active_user", default=None)


def new_state():
    """A fresh, empty per-user state dict."""
    return dict(_DEFAULT)


def activate(uid):
    """Make `uid`'s state current for this request/thread (None = anonymous)."""
    _active_uid.set(uid)


def deactivate():
    """Return to the anonymous state (called from the request teardown)."""
    _active_uid.set(None)


def current_uid():
    """The active account id, or None for the anonymous state."""
    return _active_uid.get()


def user_state(uid):
    """The live state dict for `uid`, creating an empty one on first use."""
    with USER_STATES_LOCK:
        st = USER_STATES.get(uid)
        if st is None:
            st = new_state()
            USER_STATES[uid] = st
        return st


def current():
    """The state dict for the active user (anonymous when none is active)."""
    uid = _active_uid.get()
    return ANONYMOUS_STATE if uid is None else user_state(uid)


def drop_user(uid):
    """Forget one account's live state (e.g. when the account is deleted)."""
    with USER_STATES_LOCK:
        USER_STATES.pop(uid, None)


def drop_all_users():
    """Forget every account's live state; the anonymous state is left alone."""
    with USER_STATES_LOCK:
        USER_STATES.clear()


class _StateProxy:
    """A dict-like view onto the active user's state.

    Flag keys are routed to `PROCESS` so CLI options stay process-wide even when
    the active user's dict is a fresh one. Everything else goes to `current()`.
    """

    def __getitem__(self, key):
        if key in PROCESS:
            return PROCESS[key]
        return current()[key]

    def __setitem__(self, key, value):
        if key in PROCESS:
            PROCESS[key] = value
        else:
            current()[key] = value

    def __delitem__(self, key):
        if key in PROCESS:
            del PROCESS[key]
        else:
            del current()[key]

    def __contains__(self, key):
        if key in PROCESS:
            return True
        return key in current()

    def get(self, key, default=None):
        if key in PROCESS:
            return PROCESS.get(key, default)
        return current().get(key, default)

    def setdefault(self, key, default=None):
        if key in PROCESS:
            return PROCESS.setdefault(key, default)
        return current().setdefault(key, default)

    def pop(self, key, *default):
        if key in PROCESS:
            return PROCESS.pop(key, *default)
        return current().pop(key, *default)

    def update(self, *args, **kwargs):
        items = dict(*args, **kwargs)
        for key, value in items.items():
            self[key] = value

    def clear(self):
        """Empty the active user's dataset state (CLI flags are kept)."""
        current().clear()

    def _merged(self):
        merged = dict(PROCESS)
        merged.update(current())
        return merged

    def keys(self):
        return self._merged().keys()

    def values(self):
        return self._merged().values()

    def items(self):
        return self._merged().items()

    def copy(self):
        return dict(self._merged())

    def __iter__(self):
        return iter(self._merged())

    def __len__(self):
        return len(self._merged())

    def __eq__(self, other):
        return self._merged() == other

    def __repr__(self):
        return "_StateProxy(%r)" % (self._merged(),)


STATE = _StateProxy()

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
