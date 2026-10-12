"""The admin policy: allowed datasets, the per-user size cap and allowlists.

Admin-owned `policy.json` in the user home (owner-only `0600`). It is separate
from `users.json` so editing policy never rewrites password hashes. Shape:

    {
      "version": 1,
      "size_limit": 0,                 # label bytes per user; 0 = unlimited
      "datasets": [                    # admin-designated allowed datasets
        {"id": "cats", "name": "Cats", "data_yaml": "/abs/data.yaml"}
      ],
      "users": {                       # per-account allowlists (by account id)
        "<uid>": {"datasets": ["cats"]}
      }
    }

A user with no `users` entry may use **all** designated datasets; listing a
subset (even empty) restricts them. The run allowlists (`actions`, `filters`,
`hooks`, `widgets`, `extensions`) default to **empty** for a restricted account
(deny), so an admin hands out capabilities explicitly. An admin bypasses every
check.
"""

import json
import os
import re
import threading

from ybe import config

_POLICY_LOCK = threading.RLock()
DATASET_ID_RE = re.compile(r"[^a-z0-9_-]+")

# The per-account allowlist keys. `datasets` defaults to all designated; the
# rest default to empty for a restricted account.
USER_KINDS = ("datasets", "actions", "filters", "hooks", "widgets", "extensions")


def _default():
    return {"version": 1, "size_limit": 0, "datasets": [], "users": {}}


def _slug(name, taken):
    """A stable, filesystem-safe dataset id derived from a display name."""
    base = DATASET_ID_RE.sub("-", str(name).strip().lower()).strip("-") or "dataset"
    candidate = base
    n = 2
    while candidate in taken:
        candidate = "%s-%d" % (base, n)
        n += 1
    return candidate


def _normalize(data):
    """Coerce a loaded policy into the known shape (never raises)."""
    policy = _default()
    if not isinstance(data, dict):
        return policy
    try:
        policy["size_limit"] = max(0, int(data.get("size_limit") or 0))
    except (TypeError, ValueError):
        policy["size_limit"] = 0
    datasets = []
    seen = set()
    for item in data.get("datasets") or []:
        if not isinstance(item, dict):
            continue
        data_yaml = item.get("data_yaml")
        if not isinstance(data_yaml, str) or not data_yaml:
            continue
        dsid = str(item.get("id") or _slug(item.get("name") or "dataset", seen))
        if dsid in seen:
            continue
        seen.add(dsid)
        datasets.append(
            {"id": dsid, "name": str(item.get("name") or dsid), "data_yaml": data_yaml}
        )
    policy["datasets"] = datasets
    users = {}
    raw_users = data.get("users")
    if isinstance(raw_users, dict):
        for uid, entry in raw_users.items():
            if not isinstance(entry, dict):
                continue
            users[str(uid)] = {
                kind: [str(x) for x in (entry.get(kind) or []) if x]
                for kind in USER_KINDS
            }
    policy["users"] = users
    return policy


def load():
    """Read and normalize `policy.json` (missing/corrupt file means defaults)."""
    with _POLICY_LOCK:
        try:
            with open(config.policy_file(), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return _default()
        return _normalize(data)


def save(policy):
    """Persist a policy atomically and owner-only; returns False on failure."""
    with _POLICY_LOCK:
        try:
            path = config.policy_file()
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(_normalize(policy), f, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            return True
        except OSError:
            return False


# --- datasets -------------------------------------------------------------- #
def datasets():
    """The designated datasets (each `{id, name, data_yaml}`)."""
    return load()["datasets"]


def dataset_by_id(dsid):
    """One designated dataset by id, or None."""
    return next((d for d in datasets() if d["id"] == dsid), None)


def add_dataset(name, data_yaml):
    """Designate a dataset; validates the data.yaml parses to a usable split.

    Returns `(policy, dataset)`; raises ValueError with a reason on bad input.
    """
    from ybe.dataset import parse_dataset

    name = str(name or "").strip()
    data_yaml = str(data_yaml or "").strip()
    if not name:
        raise ValueError("a name is required")
    if not os.path.isfile(data_yaml):
        raise ValueError("not a file: %s" % data_yaml)
    dataset_path, _classes, splits = parse_dataset(data_yaml)
    if not splits:
        raise ValueError("no train/val/test image folders found")
    policy = load()
    taken = {d["id"] for d in policy["datasets"]}
    ds = {"id": _slug(name, taken), "name": name, "data_yaml": data_yaml}
    policy["datasets"].append(ds)
    if not save(policy):
        raise OSError("could not write %s" % config.policy_file())
    return load(), ds


def remove_dataset(dsid):
    """Drop a designated dataset (and any per-user reference to it)."""
    policy = load()
    policy["datasets"] = [d for d in policy["datasets"] if d["id"] != dsid]
    for entry in policy["users"].values():
        entry["datasets"] = [x for x in entry.get("datasets", []) if x != dsid]
    if not save(policy):
        raise OSError("could not write %s" % config.policy_file())
    return load()


# --- size cap -------------------------------------------------------------- #
def size_limit():
    """The per-user label-byte cap; 0 means unlimited."""
    return load()["size_limit"]


def set_size_limit(value):
    """Set the per-user label-byte cap (0 = unlimited)."""
    policy = load()
    try:
        policy["size_limit"] = max(0, int(value))
    except (TypeError, ValueError):
        raise ValueError("size_limit must be a non-negative integer")
    if not save(policy):
        raise OSError("could not write %s" % config.policy_file())
    return policy["size_limit"]


# --- per-user dataset access ---------------------------------------------- #
def user_dataset_ids(uid):
    """The dataset ids `uid` may use (all designated when not explicitly set)."""
    policy = load()
    entry = policy["users"].get(str(uid))
    if not isinstance(entry, dict) or "datasets" not in entry:
        return [d["id"] for d in policy["datasets"]]
    return [x for x in entry["datasets"] if x]


def user_datasets(uid):
    """The designated datasets `uid` may use (in designation order)."""
    allowed = set(user_dataset_ids(uid))
    return [d for d in datasets() if d["id"] in allowed]


def set_user_datasets(uid, ids):
    """Explicitly set which datasets an account may use (overrides the default)."""
    return set_user_allowed(uid, "datasets", ids)


def user_allowed(uid, kind):
    """The names an account may run for `kind`.

    `datasets` defaults to every designated dataset; the run allowlists default
    to empty, so a restricted account gets nothing until an admin grants it.
    """
    if kind == "datasets":
        return user_dataset_ids(uid)
    policy = load()
    entry = policy["users"].get(str(uid))
    if not isinstance(entry, dict):
        return []
    return list(entry.get(kind, []))


def set_user_allowed(uid, kind, names):
    """Replace an account's allowlist for one `kind`. Returns the new list."""
    if kind not in USER_KINDS:
        raise ValueError("unknown allowlist: %s" % kind)
    policy = load()
    entry = policy["users"].setdefault(str(uid), {})
    entry[kind] = [str(x) for x in (names or [])]
    if not save(policy):
        raise OSError("could not write %s" % config.policy_file())
    return entry[kind]
