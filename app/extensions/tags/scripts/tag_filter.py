#!/usr/bin/env python3
"""tags extension: keep images by tag presence.

    python tag_filter.py <input_pipe> <output_pipe> --tag NAME
                         [--invert] [--split SPLIT] [--data-yaml PATH]

An image's tags live in a sibling `.txt` file (one tag per line). By default the
path is found the same way the app does it: the last `images` path segment is
replaced with `tags` and the image extension with `.txt`. When the dataset has a
custom tags folder (stored in `.tags_extension.json` in the user home), the
`--split` and `--data-yaml` arguments let this helper honour it.
"""

import argparse
import json
import os
import sys


def override_tags_dir(data_yaml, split):
    """The custom tags folder for a split, or "" when the default rule applies."""
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


def default_tag_path(image_path):
    """Tag file when no tags folder is given: swap the last `images` segment."""
    parts = image_path.replace("\\", "/").rstrip("/").split("/")
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "images":
            parts[i] = "tags"
            path = "/".join(parts)
            return os.path.splitext(path)[0] + ".txt"
    images_dir = os.path.dirname(image_path)
    tags_dir = os.path.normpath(
        os.path.join(images_dir, "..", "tags", os.path.basename(images_dir)))
    stem = os.path.splitext(os.path.basename(image_path))[0]
    return os.path.join(tags_dir, stem + ".txt")


def tag_path(image_path, tags_dir):
    if tags_dir:
        stem = os.path.splitext(os.path.basename(image_path))[0]
        return os.path.join(tags_dir, stem + ".txt")
    return default_tag_path(image_path)


def image_tags(path):
    tags = set()
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                tag = line.strip()
                if tag:
                    tags.add(tag)
    except OSError:
        pass
    return tags


def main(argv=None):
    parser = argparse.ArgumentParser(description="Filter images by tag presence.")
    parser.add_argument("input_pipe")
    parser.add_argument("output_pipe")
    parser.add_argument("--tag", dest="tag_name", required=True)
    parser.add_argument("--invert", action="store_true")
    parser.add_argument("--split", default="")
    parser.add_argument("--data-yaml", dest="data_yaml", default="")
    args = parser.parse_args(argv)

    tags_dir = override_tags_dir(args.data_yaml, args.split)

    with open(args.input_pipe, encoding="utf-8") as f:
        paths = [line.strip() for line in f if line.strip()]

    kept = [
        path for path in paths
        if (args.tag_name in image_tags(tag_path(path, tags_dir))) != args.invert
    ]

    with open(args.output_pipe, "w", encoding="utf-8") as f:
        for path in kept:
            f.write(path + "\n")

    print(f"tag_filter: kept {len(kept)} of {len(paths)} "
          f"({'not ' if args.invert else ''}{args.tag_name})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
