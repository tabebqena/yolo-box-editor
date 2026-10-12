"""Persist a signed-in account's live dataset state to disk and rehydrate it.

The anonymous/operator state is *not* stored here: a single-user install keeps
resuming through the recent-datasets list in `config.json` (unchanged, so case 1
behaves exactly as before). Only registered accounts get a state file, under the
per-user folder that multi-user mode introduces:

    <home>/users/<id>/state.json

Only the small preferences are written (`data_yaml`, `active_split`,
`active_filters`); the image list and split scan are derived and re-built from
the data.yaml on hydration. Writes are atomic and best-effort.
"""

import json
import os
import threading

from ybe import config, state

# The keys that survive a restart. Everything else in a user's state is a cache.
PERSISTED_KEYS = ("data_yaml", "active_split", "active_filters")

_HYDRATED = set()
_LOCK = threading.RLock()


def state_path(uid):
    """The state file for an account id (inside its future per-user folder)."""
    return os.path.join(config.YBX_HOME, "users", str(uid), "state.json")


def _read(uid):
    try:
        with open(state_path(uid), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save(uid):
    """Write `uid`'s current persisted preferences (atomic, never raises)."""
    if not uid:
        return
    with _LOCK:
        st = state.user_state(uid)
        payload = {key: st.get(key) for key in PERSISTED_KEYS}
    path = state_path(uid)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 1, **payload}, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except OSError:
        pass


def save_current():
    """Persist the active user's preferences (no-op for the anonymous state)."""
    save(state.current_uid())


def _valid_filters(raw):
    """Keep only filter entries whose name still exists (as `_restore_view` does)."""
    from ybe.extensions import load_filters

    if not isinstance(raw, list):
        return []
    known = load_filters()[0]
    chain = []
    for item in raw:
        if isinstance(item, str):
            item = {"name": item}
        if isinstance(item, dict) and item.get("name") in known:
            chain.append(item)
    return chain


def ensure(uid):
    """Hydrate `uid`'s state from disk once per process (idempotent)."""
    if not uid:
        return
    with _LOCK:
        if uid in _HYDRATED:
            return
        _HYDRATED.add(uid)
    data = _read(uid)
    if not data:
        return
    previous = state.current_uid()
    state.activate(uid)
    try:
        _hydrate(data)
    finally:
        state.activate(previous)


def _hydrate(data):
    """Rebuild the active user's dataset from persisted preferences."""
    from ybe.dataset import _load_dataset
    from ybe.filters import apply_filters

    path = data.get("data_yaml")
    if not (isinstance(path, str) and path and os.path.isfile(path)):
        return
    if not _load_dataset(path):
        state.STATE["data_yaml"] = None
        return
    split = data.get("active_split")
    known_splits = {s["name"] for s in state.STATE["splits"]}
    if split in known_splits:
        state.STATE["active_split"] = split
    chain = _valid_filters(data.get("active_filters"))
    if chain:
        apply_filters(chain)


def forget(uid):
    """Drop one account's hydration marker (when its state is reset/removed)."""
    with _LOCK:
        _HYDRATED.discard(uid)


def reset():
    """Forget every hydration marker (tests)."""
    with _LOCK:
        _HYDRATED.clear()
