#!/usr/bin/env python3
"""Images whose tags do NOT contain `revised` — the ones still to review.

Run by the app as:  python no_revised.py <data.yaml> <split>
Prints one `split/name` per line (e.g. `val/0000002.jpg`). An image with no tag
file counts as "not revised" and is printed.

To look for a different tag, edit TAG below.
"""

import os
import sys

TAG = "revised"

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff", ".heic",
}


def _strip_comment(value):
    for i, ch in enumerate(value):
        if ch == "#" and (i == 0 or value[i - 1] == " "):
            return value[:i].strip()
    return value.strip()


def _parse_data_yaml(path):
    data = {}
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip()
            value = _strip_comment(value).strip().strip("'\"")
            if key in ("path", "train", "val", "test") and value:
                data[key] = value
    return data


def _tags_dir(images_dir):
    """Same derivation as the app: replace the last `images` segment with `tags`."""
    parts = images_dir.replace("\\", "/").rstrip("/").split("/")
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "images":
            parts[i] = "tags"
            return "/".join(parts)
    return os.path.normpath(
        os.path.join(images_dir, "..", "tags", os.path.basename(images_dir))
    )


def _has_tag(tags_dir, name):
    stem = os.path.splitext(name)[0]
    try:
        with open(os.path.join(tags_dir, stem + ".txt"), encoding="utf-8") as f:
            return any(line.strip() == TAG for line in f)
    except OSError:
        return False


def main(argv):
    data_yaml = argv[1]
    split = argv[2]
    data_yaml_dir = os.path.dirname(os.path.abspath(data_yaml))
    data = _parse_data_yaml(data_yaml) if os.path.isfile(data_yaml) else {}

    base = data.get("path") or data_yaml_dir
    if not os.path.isabs(base):
        base = os.path.normpath(os.path.join(data_yaml_dir, base))

    for key in ("train", "val", "test"):
        if split and key != split:
            continue
        rel = data.get(key)
        if not rel:
            continue
        images_dir = rel if os.path.isabs(rel) else os.path.join(base, rel)
        images_dir = os.path.normpath(images_dir)
        if not os.path.isdir(images_dir):
            continue
        tags_dir = _tags_dir(images_dir)
        for name in sorted(os.listdir(images_dir)):
            if os.path.splitext(name)[1].lower() not in IMAGE_EXTS:
                continue
            if not os.path.isfile(os.path.join(images_dir, name)):
                continue
            if not _has_tag(tags_dir, name):
                print(f"{key}/{name}")


if __name__ == "__main__":
    main(sys.argv)
