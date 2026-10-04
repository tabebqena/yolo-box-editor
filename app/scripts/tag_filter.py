#!/usr/bin/env python3
"""yolo-box-editor tag filter helper.

Keeps the images whose tag file contains (or, with --invert, does not contain) a
given tag. Used by `app/filters/has_tag.yaml` and `app/filters/not_has_tag.yaml`.

    python tag_filter.py <input_pipe> <output_pipe> --tag NAME
                         [--invert] [--tags-dir DIR]

An image's tags live in a sibling `.txt` file (one tag per line). By default the
path is found the same way the app does it: the last `images` path segment is
replaced with `tags` and the image extension with `.txt`
(`train/images/a.jpg` -> `train/tags/a.txt`). When `--tags-dir` is given (the
loaded dataset's tags folder for the active split) it is used instead, so a
custom tags folder is honoured. An image with no tag file has no tags.
"""

import argparse
import os
import sys


def default_tag_path(image_path):
    """Tag file when no tags folder is given: swap the last `images` segment."""
    parts = image_path.replace("\\", "/").rstrip("/").split("/")
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "images":
            parts[i] = "tags"
            path = "/".join(parts)
            return os.path.splitext(path)[0] + ".txt"
    # fallback: a `tags` folder beside the images dir, matching the app's rule
    images_dir = os.path.dirname(image_path)
    tags_dir = os.path.normpath(
        os.path.join(images_dir, "..", "tags", os.path.basename(images_dir)))
    stem = os.path.splitext(os.path.basename(image_path))[0]
    return os.path.join(tags_dir, stem + ".txt")


def tag_path(image_path, tags_dir):
    """The tag file for an image: `tags_dir/<stem>.txt`, else the default rule."""
    if tags_dir:
        stem = os.path.splitext(os.path.basename(image_path))[0]
        return os.path.join(tags_dir, stem + ".txt")
    return default_tag_path(image_path)


def image_tags(path):
    """The set of tags in a tag file (missing/unreadable -> empty)."""
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
    parser.add_argument("--tag", dest="tag_name", required=True,
                        help="tag to look for")
    parser.add_argument("--invert", action="store_true",
                        help="keep images that do NOT contain the tag")
    parser.add_argument("--tags-dir", dest="tags_dir", default="",
                        help="tags folder for the active split (overrides the path rule)")
    args = parser.parse_args(argv)

    # Candidate images: one absolute path per line in the input pipe.
    with open(args.input_pipe, encoding="utf-8") as f:
        paths = [line.strip() for line in f if line.strip()]

    # Keep an image when it *contains* the tag (or, with --invert, when it does
    # not); `!= args.invert` flips the test without a second branch.
    kept = [
        path for path in paths
        if (args.tag_name in image_tags(tag_path(path, args.tags_dir))) != args.invert
    ]

    with open(args.output_pipe, "w", encoding="utf-8") as f:
        for path in kept:
            f.write(path + "\n")

    print(f"tag_filter: kept {len(kept)} of {len(paths)} "
          f"({'not ' if args.invert else ''}{args.tag_name})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
