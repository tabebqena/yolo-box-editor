"""Mutable, process-wide runtime state.

These are the live containers the routes mutate. Tests replace/reset them, so
callers must use `state.NAME` (module attribute access) rather than importing a
name directly.
"""

import threading

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
