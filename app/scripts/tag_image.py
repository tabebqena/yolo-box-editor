#!/usr/bin/env python3
"""yolo-box-editor helper: add one tag to an image's tag file.

Called by an action step, e.g.:

    steps:
      - {PYTHON} {APP_SCRIPT_DIR}/tag_image.py {IMAGE_PATH} {TAG} --tags-dir {TAGS_DIR}

An image's tags live in a sibling `.txt` file, one tag per line (de-duplicated;
the on-disk order is not significant). The path is found the same way the app
does it: the last path segment that is exactly `images` is replaced with `tags`
and the image extension with `.txt` (`train/images/a.jpg` -> `train/tags/a.txt`).
Only a whole segment is swapped, so a folder such as `images_backup` is left
alone. Pass `--tags-dir` (the `{TAGS_DIR}` placeholder) to honour a custom tags
folder: the file then lives at `<tags-dir>/<stem>.txt`. The write goes to a temp
file first and is then renamed over the target, so a half-written tag file is
never left behind.
"""

import argparse
import os
import sys


def _replace_images_segment(image_path):
    """Swap the last `images` path segment for `tags` (mirrors the app's rule)."""
    parts = image_path.replace("\\", "/").rstrip("/").split("/")
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "images":
            parts[i] = "tags"
            return "/".join(parts)
    # fallback: a sibling `tags` folder next to the images dir, matching the app
    images_dir = os.path.dirname(image_path)
    tags_dir = os.path.normpath(
        os.path.join(images_dir, "..", "tags", os.path.basename(images_dir)))
    return os.path.join(tags_dir, os.path.basename(image_path))


def tag_file_path(image_path, tags_dir=""):
    """The tag file for an image: `<tags_dir>/<stem>.txt`, else the derived path."""
    if tags_dir:
        stem = os.path.splitext(os.path.basename(image_path))[0]
        return os.path.join(tags_dir, stem + ".txt")
    return os.path.splitext(_replace_images_segment(image_path))[0] + ".txt"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Add one tag to an image's tag file.")
    parser.add_argument("image_path")
    parser.add_argument("tag")
    parser.add_argument("--tags-dir", dest="tags_dir", default="",
                        help="the image's split tags folder (honours a custom tags dir)")
    args = parser.parse_args(argv)

    tag_path = tag_file_path(args.image_path, args.tags_dir)
    os.makedirs(os.path.dirname(tag_path), exist_ok=True)

    # Start from the tags already on the image, if any.
    lines = []
    if os.path.isfile(tag_path):
        with open(tag_path, "r") as f:
            lines = [l.strip() for l in f.readlines()]
    lines.append(args.tag.strip())

    # Normalize (one per line) and drop duplicates via a set.
    lines = [f"{l}\n" for l in lines]
    lines = set(lines)

    # Atomic write: temp file + rename over the target.
    tmp_path = f"{tag_path}-tmp"
    with open(tmp_path, "w") as ff:
        ff.writelines(lines)
    os.replace(tmp_path, tag_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
