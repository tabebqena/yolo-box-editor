#!/usr/bin/env python3
"""yolo-box-editor class filter helper.

Keeps the images whose label file contains (or, with --invert, does not contain)
a given class name. Used by `app/filters/contains_class.yaml` and
`app/filters/not_contains_class.yaml`.

    python class_filter.py <data.yaml> <split> <input_pipe> <output_pipe>
                           --class NAME [--invert]

YOLO labels store class *ids*; this helper reads `names:` from `data.yaml` to map
the requested name to its id, then scans each image's label file (found by
replacing the last `images` path segment with `labels`, extension `.txt`). An
image with no label file contains no class.
"""

import argparse
import os
import sys


def read_names(data_yaml):
    """The `names:` list from a data.yaml (inline or block form); [] when absent."""
    try:
        with open(data_yaml, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("names:"):
            continue
        value = stripped.split(":", 1)[1].split("#", 1)[0].strip()
        if value.startswith("["):
            inner = value[1 : value.rfind("]")]
            return [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
        if value:
            return [value.strip("'\"")]
        names = []
        for following in lines[i + 1 :]:
            item = following.strip()
            if not item:
                continue
            indent = len(following) - len(following.lstrip())
            if indent == 0:
                break
            if item.startswith("-"):
                name = item[1:].split("#", 1)[0].strip().strip("'\"")
            elif ":" in item:
                name = item.split(":", 1)[1].split("#", 1)[0].strip().strip("'\"")
            else:
                continue
            if name:
                names.append(name)
        return names
    return []


def label_path(image_path):
    """The label file for an image: swap the last `images` segment for `labels`."""
    parts = image_path.replace("\\", "/").rstrip("/").split("/")
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "images":
            parts[i] = "labels"
            path = "/".join(parts)
            return os.path.splitext(path)[0] + ".txt"
    return os.path.splitext(image_path)[0] + ".txt"


def class_ids(label_file):
    """The set of class ids in a YOLO label file (missing/first-token errors -> empty)."""
    ids = set()
    try:
        with open(label_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ids.add(int(float(line.split()[0])))
                except (ValueError, IndexError):
                    continue
    except OSError:
        pass
    return ids


def main(argv=None):
    parser = argparse.ArgumentParser(description="Filter images by class presence.")
    parser.add_argument("data_yaml")
    parser.add_argument("split")
    parser.add_argument("input_pipe")
    parser.add_argument("output_pipe")
    parser.add_argument("--class", dest="class_name", required=True,
                        help="class name to look for")
    parser.add_argument("--invert", action="store_true",
                        help="keep images that do NOT contain the class")
    args = parser.parse_args(argv)

    names = read_names(args.data_yaml)
    if args.class_name not in names:
        print(f"class '{args.class_name}' is not in {args.data_yaml}", file=sys.stderr)
        return 2
    target_id = names.index(args.class_name)

    with open(args.input_pipe, encoding="utf-8") as f:
        paths = [line.strip() for line in f if line.strip()]

    kept = [
        path for path in paths
        if (target_id in class_ids(label_path(path))) != args.invert
    ]

    with open(args.output_pipe, "w", encoding="utf-8") as f:
        for path in kept:
            f.write(path + "\n")

    print(f"class_filter: kept {len(kept)} of {len(paths)} "
          f"({'not ' if args.invert else ''}{args.class_name})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
