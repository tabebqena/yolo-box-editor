#!/usr/bin/env python3
"""yolo-box-editor filters: one Python script per filter, in this filters/ dir.

This example file is comments only and defines nothing (it prints no lines, so
if it were selected it would show zero images). Copy it (or any file here) to a
new <Name>.py to add a filter, or write your own.

Contract
--------
The app runs:

    python <this script> <data.yaml> <split>

  - <data.yaml> : path of the loaded dataset's data.yaml
  - <split>     : "train" / "val" / "test", or "" when the UI is on All splits
                  (the filter decides what to return in that case)

The script must print one ``split/name`` per line to stdout, e.g.:

    train/a.jpg
    val/b.png

Rules the app applies to the output:
  - blank lines are ignored;
  - order is preserved (so you can rank the results);
  - duplicates are dropped;
  - a line whose image is not in the dataset's scanned list is skipped and
    counted (a notice is shown in the UI);
  - a non-zero exit code or a timeout (120 s) is reported as a filter failure.

When a filter is active it replaces the split's own filtering: the split above
is just the filter's input, and the returned list is exactly what the app shows.

Examples
--------
Print every other image of the split (deterministic order):

    import sys
    from pathlib import Path

    data_yaml, split = sys.argv[1], sys.argv[2]
    if split:
        images_dir = Path(data_yaml).parent / "images" / split
        for i, path in enumerate(sorted(images_dir.glob("*"))):
            if i % 2 == 0:
                print(f"{split}/{path.name}")

Personal filters: files ending in `.a.py` are read after the shipped ones, win
on a name clash, and are never shipped/overwritten (they are git-ignored).
"""
