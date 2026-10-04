"""yolo-box-editor helper: add one tag to an image's tag file.

Called by an action step, e.g.:

    steps:
      - {PYTHON} {APP_SCRIPT_DIR}/tag_image.py {IMAGE_PATH} {TAG}

An image's tags live in a sibling `.txt` file, found by swapping the last
`images` path segment for `tags` and the image extension for `.txt`
(`train/images/a.jpg` -> `train/tags/a.txt`). Tags are one per line and
de-duplicated (the on-disk order is not significant). The write goes to a temp
file first and is then renamed over the target, so a half-written tag file is
never left behind.
"""

import os
import sys


if __name__ == "__main__":
    argv = sys.argv[1:]
    if len(argv) == 2:
        image_path = argv[0]
        tag = argv[1]
        # train/images/image.jpeg  -> train/tags/image.jpeg
        # images/train/image.jpeg -> tags/train/image.jpeg
        dirname = os.path.dirname(image_path.replace("images", "tags"))
        basename = os.path.basename(image_path)
        filename, ext = os.path.splitext(basename)
        os.makedirs(dirname, exist_ok=True)
        tag_path = os.path.join(dirname, f"{filename}.txt")

        # Start from the tags already on the image, if any.
        lines = []
        if os.path.exists(tag_path) and os.path.isfile(tag_path):
            with open(tag_path, "r") as f:
                lines = [l.strip() for l in f.readlines()]
        lines.append(tag.strip())

        # Normalize (one per line) and drop duplicates via a set.
        lines = [f"{l}\n" for l in lines]
        lines = set(lines)

        # Atomic write: temp file + rename over the target.
        tmp_path = f"{tag_path}-tmp"
        with open(tmp_path, "w") as ff:
            ff.writelines(lines)
        os.replace(tmp_path, tag_path)
    else:
        sys.exit(f"Invalid execution, 2 arguments required, image_path & the tag, given ({len(argv)})")
