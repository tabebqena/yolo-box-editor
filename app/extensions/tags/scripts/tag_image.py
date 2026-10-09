#!/usr/bin/env python3
"""tags extension: add one tag to an image's tag file.

    python tag_image.py <image_path> <tag> [--tags-dir DIR]
                        [--split SPLIT] [--data-yaml PATH]

The tag file is `<tags-dir>/<stem>.txt` when `--tags-dir` is given, else it is
derived from the image path (last `images` segment -> `tags`). `--split` and
`--data-yaml` let it honour the dataset's custom tags folder. The write is
atomic (temp file + rename).
"""

import argparse
import json
import os
import sys


def override_tags_dir(data_yaml, split):
    home = os.environ.get("YBE_HOME", "")
    if not data_yaml or not split or not home:
        return ""
    try:
        with open(os.path.join(home, ".tags_extension.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return ""
    base = data.get(os.path.abspath(data_yaml)) if isinstance(data, dict) else None
    return os.path.join(base, split) if base else ""


def _replace_images_segment(image_path):
    parts = image_path.replace("\\", "/").rstrip("/").split("/")
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "images":
            parts[i] = "tags"
            return "/".join(parts)
    images_dir = os.path.dirname(image_path)
    tags_dir = os.path.normpath(
        os.path.join(images_dir, "..", "tags", os.path.basename(images_dir)))
    return os.path.join(tags_dir, os.path.basename(image_path))


def tag_file_path(image_path, tags_dir):
    if tags_dir:
        stem = os.path.splitext(os.path.basename(image_path))[0]
        return os.path.join(tags_dir, stem + ".txt")
    return os.path.splitext(_replace_images_segment(image_path))[0] + ".txt"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Add one tag to an image's tag file.")
    parser.add_argument("image_path")
    parser.add_argument("tag")
    parser.add_argument("--tags-dir", dest="tags_dir", default="")
    parser.add_argument("--split", default="")
    parser.add_argument("--data-yaml", dest="data_yaml", default="")
    args = parser.parse_args(argv)

    tags_dir = args.tags_dir or override_tags_dir(args.data_yaml, args.split)
    tag_path = tag_file_path(args.image_path, tags_dir)
    os.makedirs(os.path.dirname(tag_path), exist_ok=True)

    lines = []
    if os.path.isfile(tag_path):
        with open(tag_path, "r") as f:
            lines = [l.strip() for l in f.readlines()]
    lines.append(args.tag.strip())
    lines = [f"{l}\n" for l in lines]
    lines = set(lines)

    tmp_path = f"{tag_path}-tmp"
    with open(tmp_path, "w") as ff:
        ff.writelines(lines)
    os.replace(tmp_path, tag_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
