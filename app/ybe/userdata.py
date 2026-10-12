"""Materialise an admin-designated dataset into a restricted user's home.

A restricted user never sees the admin's dataset path directly. Instead each
designated dataset is copied as a *skeleton* under:

    <home>/users/<uid>/datasets/<dsid>/

with the images **symlinked** (no bytes copied) and the labels a **real local**
folder the user writes to:

    <home>/users/<uid>/datasets/<dsid>/data.yaml
    <home>/users/<uid>/datasets/<dsid>/images/<split>  -> admin images dir
    <home>/users/<uid>/datasets/<dsid>/labels/<split>/  (real, writable)

The generated `data.yaml` uses a relative `path:` and `images/<split>` splits,
so the existing `images` -> `labels` path rule resolves labels into the user's
own folder. `user_bytes` measures the user's own (non-symlinked) bytes for the
size cap.
"""

import os

from ybe import config, policy
from ybe.dataset import parse_dataset


def dataset_dir(uid, dsid):
    """The user's local copy folder for one designated dataset."""
    return os.path.join(config.user_home(uid), "datasets", str(dsid))


def data_yaml_path(uid, dsid):
    """The generated data.yaml for a materialised dataset."""
    return os.path.join(dataset_dir(uid, dsid), "data.yaml")


def _write_data_yaml(base, classes, splits):
    """Write the user's data.yaml (relative path + images/<split> splits)."""
    lines = ["path: %s" % base, ""]
    for split in splits:
        lines.append("%s: images/%s" % (split["name"], split["name"]))
    if classes:
        lines.append("")
        lines.append("names: [%s]" % ", ".join(str(c) for c in classes))
    path = os.path.join(base, "data.yaml")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)
    return path


def materialize(uid, ds):
    """Create (or refresh) `uid`'s copy of designated dataset `ds`.

    Returns the generated data.yaml path. Images are symlinked to the admin's
    folders; labels are left as real local folders so the user's edits are theirs.
    """
    _dataset_path, classes, splits = parse_dataset(ds["data_yaml"])
    if not splits:
        raise OSError("dataset %r has no usable splits" % ds.get("id"))
    base = dataset_dir(uid, ds["id"])
    os.makedirs(base, exist_ok=True)
    for split in splits:
        name = split["name"]
        link = os.path.join(base, "images", name)
        os.makedirs(os.path.dirname(link), exist_ok=True)
        if not os.path.lexists(link):
            try:
                os.symlink(split["images_dir"], link)
            except OSError as exc:
                raise OSError(
                    "could not link images for split %r: %s" % (name, exc)
                )
        os.makedirs(os.path.join(base, "labels", name), exist_ok=True)
    return _write_data_yaml(base, classes, splits)


def select(uid, dsid):
    """Materialise dataset `dsid` for `uid` and return its data.yaml path.

    Raises KeyError when the dataset is not designated and PermissionError when
    the account is not allowed to use it.
    """
    ds = policy.dataset_by_id(dsid)
    if ds is None:
        raise KeyError(dsid)
    if dsid not in policy.user_dataset_ids(uid):
        raise PermissionError(dsid)
    return materialize(uid, ds)


def user_bytes(uid):
    """The account's own label bytes under its materialised datasets.

    Only the real `labels/` folders are counted (per the agreed cap): the
    symlinked images and the small state/config files are ignored.
    """
    root = os.path.join(config.user_home(uid), "datasets")
    total = 0
    if not os.path.isdir(root):
        return 0
    for entry in os.listdir(root):
        labels = os.path.join(root, entry, "labels")
        for dirpath, _dirnames, filenames in os.walk(labels, followlinks=False):
            for name in filenames:
                path = os.path.join(dirpath, name)
                if os.path.islink(path):
                    continue
                try:
                    total += os.path.getsize(path)
                except OSError:
                    pass
    return total


def within_quota(uid, label_path, new_length):
    """True when writing `new_length` bytes to `label_path` stays under the cap."""
    if not uid:
        return True  # the admin/anonymous home is not capped
    limit = policy.size_limit()
    if not limit:
        return True
    existing = 0
    try:
        if label_path and os.path.isfile(label_path):
            existing = os.path.getsize(label_path)
    except OSError:
        existing = 0
    return user_bytes(uid) - existing + new_length <= limit
