"""Dataset scanning: data.yaml -> splits, image list, label paths.

The live dataset is held in `state.STATE`; these functions read and populate it.
By convention the labels folder is found by replacing the last `images` path
segment (`.../images/train` -> `.../labels/train`); `_replace_images_segment` is
the single place that rule lives (the tags extension reuses it for tag paths).

Startup resume (`app.py`) and the post-run image rescan (`commands.py`) live one
layer up because they also touch user config and the filter chain.
"""

import os

from ybe import config, state
from ybe.parsing import _parse_data_yaml


def is_image(name):
    return os.path.splitext(name)[1].lower() in config.IMAGE_EXTS


def _replace_images_segment(images_dir, component):
    """Replace the last `images` path segment with `component` (labels, tags, …)."""
    parts = images_dir.replace("\\", "/").rstrip("/").split("/")
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "images":
            parts[i] = component
            return "/".join(parts)
    # fallback: sibling `component` folder next to the images dir
    return os.path.normpath(os.path.join(images_dir, "..", component, os.path.basename(images_dir)))


def _labels_dir_for(images_dir):
    """Derive the labels dir by replacing the last `images` segment with `labels`."""
    return _replace_images_segment(images_dir, "labels")


def scan_splits():
    """Parse data.yaml and build the list of {name, images_dir, labels_dir} splits."""
    splits = []
    if not state.STATE["data_yaml"] or not os.path.isfile(state.STATE["data_yaml"]):
        return splits

    data = _parse_data_yaml(state.STATE["data_yaml"])
    data_yaml_dir = os.path.dirname(os.path.abspath(state.STATE["data_yaml"]))

    # The dataset root comes from `path:` when present (resolved relative to the
    # data.yaml file), else the folder holding data.yaml.
    base = data.get("path") or data_yaml_dir
    if not os.path.isabs(base):
        base = os.path.normpath(os.path.join(data_yaml_dir, base))
    state.STATE["dataset_path"] = os.path.abspath(base)
    state.STATE["classes"] = data.get("names") or []

    # Each split is `train`/`val`/`test` -> an images folder (absolute or
    # relative to the dataset root). A split whose folder does not exist is
    # skipped, so a dataset with only `train` still works.
    for key in ("train", "val", "test"):
        rel = data.get(key)
        if not rel:
            continue
        images_dir = rel if os.path.isabs(rel) else os.path.join(state.STATE["dataset_path"], rel)
        images_dir = os.path.normpath(images_dir)
        if not os.path.isdir(images_dir):
            continue
        splits.append(
            {
                "name": key,
                "images_dir": images_dir,
                "labels_dir": _labels_dir_for(images_dir),
            }
        )
    return splits


def scan_images():
    flat = []
    for split in state.STATE["splits"]:
        d = split["images_dir"]
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if os.path.isfile(os.path.join(d, f)) and is_image(f):
                flat.append({"split": split["name"], "name": f})
    return flat


def _load_dataset(path):
    """Activate the dataset at `path` in state.STATE. True when it has usable splits."""
    state.STATE["data_yaml"] = os.path.abspath(path)
    state.STATE["splits"] = scan_splits()
    state.STATE["images"] = scan_images()
    return bool(state.STATE["splits"])


def _split_by_name(name):
    for s in state.STATE["splits"]:
        if s["name"] == name:
            return s
    return None


def label_path(entry):
    split = _split_by_name(entry["split"])
    if split is None:
        return None
    stem = os.path.splitext(entry["name"])[0]
    return os.path.join(split["labels_dir"], stem + ".txt")


def _parse_label_file(path):
    """Return a list of (class, cx, cy, w, h) tuples from a YOLO label file."""
    boxes = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) < 5:
                    continue
                try:
                    cls = int(float(parts[0]))
                    cx, cy, w, h = (float(x) for x in parts[1:5])
                except ValueError:
                    continue
                boxes.append((cls, cx, cy, w, h))
    except OSError:
        pass
    return boxes


def read_classes():
    if state.STATE["classes"]:
        return state.STATE["classes"]
    # fallback: derive max class id from existing label files
    max_cls = -1
    for entry in state.STATE["images"]:
        p = label_path(entry)
        if p is None:
            continue
        if not os.path.isfile(p):
            continue
        for cls, *_ in _parse_label_file(p):
            max_cls = max(max_cls, cls)
    if max_cls >= 0:
        return [f"class_{i}" for i in range(max_cls + 1)]
    return ["class_0"]


def _entry_by_key(key):
    """Resolve a `split/name` key to a known image entry, or None.

    Identity (not position) is the stable way to name an image: the active
    filter/split can rebuild the list at any time, so an index may point at a
    different file than the client is showing.
    """
    if not key or "/" not in key:
        return None
    split, name = key.split("/", 1)
    for entry in state.STATE["images"]:
        if entry["split"] == split and entry["name"] == name:
            return entry
    return None


def _image_index(entry):
    """The 1-based position of `entry` in the visible list, else None."""
    visible = _current_images()
    for i, e in enumerate(visible):
        if e["split"] == entry["split"] and e["name"] == entry["name"]:
            return i + 1
    return None


def _current_images():
    """The images visible to the UI.

    A filter chain narrows the list to its own result (the chain's first filter
    already received the active split as its input); otherwise the list is
    filtered to the active split.
    """
    if state.STATE["active_filters"]:
        return state.STATE["filter_images"] or []
    if not state.STATE["active_split"]:
        return state.STATE["images"]
    return [e for e in state.STATE["images"] if e["split"] == state.STATE["active_split"]]
