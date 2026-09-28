"""Move an image, its YOLO label and its tag file into an `archive/` folder.

Usage:
    python archive.py <data_yaml_path> <image_path> <label_path>

The split segment (train/val/test) is preserved *under* `archive`, so files
from different splits never collide and the rest of the structure is kept:

    a/b/c/train/images/i.png -> a/b/c/archive/train/images/i.png
    a/b/c/images/train/i.png -> a/b/c/images/archive/train/i.png

The label and tag files that sit beside the image are moved too, each skipped
when it is missing. The tag file is the label path with its last `labels`
segment replaced by `tags`.

The split names are read from the `train:`/`val:`/`test:` keys of the given
data.yaml; if it cannot be read, the standard names are used. Only the last
path segment matching a split name is moved (handles `<split>/images` and
`images/<split>` layouts). `archive/` directories are created as needed.
"""

import os
import shutil
import sys

DEFAULT_SPLITS = ("train", "val", "valid", "validate", "test")


def split_names(data_yaml_path):
    """Split names declared by the data.yaml, or the standard three as fallback."""
    found = set()
    if data_yaml_path:
        try:
            with open(data_yaml_path, encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#") or ":" not in line:
                        continue
                    key, _, value = line.partition(":")
                    key = key.strip()
                    if key in DEFAULT_SPLITS and value.strip():
                        found.add(key)
        except OSError:
            pass
    return found or set(DEFAULT_SPLITS)


def archive_path(path, splits):
    """Return `path` with its last split segment moved under `archive/`.

    `a/b/train/i.png` -> `a/b/archive/train/i.png`. Returns None when no split
    segment is present.
    """
    parts = path.replace("\\", "/").split("/")
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] in splits:
            parts[i] = f"archive/{parts[i]}"
            return "/".join(parts)
    return None


def tag_path_for(label_path):
    """The tag file beside a label file: last `labels` segment -> `tags`.

    Returns None when `label_path` is empty or has no `labels` segment.
    """
    if not label_path:
        return None
    parts = label_path.replace("\\", "/").split("/")
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "labels":
            parts[i] = "tags"
            return "/".join(parts)
    return None


def main(argv):
    if len(argv) != 3:
        print(
            "usage: archive.py <data_yaml_path> <image_path> <label_path>",
            file=sys.stderr,
        )
        return 2

    data_yaml_path, image_path, label_path = argv
    splits = split_names(data_yaml_path)

    if not os.path.isfile(image_path):
        print(f"error: image not found: {image_path}", file=sys.stderr)
        return 1

    dest_image = archive_path(image_path, splits)
    if dest_image is None:
        names = ", ".join(sorted(splits))
        print(
            f"error: no split ({names}) segment in image path: {image_path}",
            file=sys.stderr,
        )
        return 1

    moves = [(image_path, dest_image)]

    if label_path:
        if os.path.isfile(label_path):
            dest_label = archive_path(label_path, splits)
            if dest_label is None:
                print(
                    f"error: no split segment in label path: {label_path}",
                    file=sys.stderr,
                )
                return 1
            moves.append((label_path, dest_label))
        else:
            print(f"note: no label file to move: {label_path}")

    tag_path = tag_path_for(label_path)
    if tag_path and os.path.isfile(tag_path):
        dest_tag = archive_path(tag_path, splits)
        if dest_tag is None:
            print(
                f"error: no split segment in tag path: {tag_path}",
                file=sys.stderr,
            )
            return 1
        moves.append((tag_path, dest_tag))

    for src, dest in moves:
        if os.path.exists(dest):
            print(
                f"error: destination already exists, refusing to overwrite: {dest}",
                file=sys.stderr,
            )
            return 1

    for src, dest in moves:
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)

    for src, dest in moves:
        shutil.move(src, dest)
        print(f"moved: {src} -> {dest}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
