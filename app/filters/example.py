#!/usr/bin/env python3
"""yolo-box-editor filters: one Python script per filter in a filters/ dir.

This file is a shipped, comments-only example and defines nothing (it never
writes its output pipe, so if it were selected it would show zero images). Your
own filters live in <home>/filters/ and are read after the shipped ones, so a
file with the same name wins and is never overwritten by an upgrade. Copy this
file to a new <Name>.py to add a filter, or write your own.

Contract
--------
The app runs filters as a chain. Each filter is run as:

    python <this script> <data.yaml> <split> <input_pipe> <output_pipe>

  - <data.yaml>    : path of the loaded dataset's data.yaml
  - <split>        : "train" / "val" / "test", or "" when the UI is on All
                     splits (the filter decides what to return in that case)
  - <input_pipe>   : file holding the images to narrow, one absolute path per
                     line. The first filter's input is the active split's
                     images (every scanned image when the split is All).
  - <output_pipe>  : file the filter must write its kept image paths to, one
                     absolute path per line.

The app then feeds that output pipe to the next filter (if any), and the last
filter's output is exactly what the app shows. Write an absolute path only if
you want to keep that image, and keep the order you want to see.

Rules the app applies to the output:
  - blank lines are ignored;
  - order is preserved (so you can rank the results);
  - duplicates are dropped;
  - a path that is not one of the dataset's scanned images is skipped and
    counted (a notice is shown in the UI);
  - a non-zero exit code or a timeout (120 s) fails the chain; the filters
    before it stay in effect (nothing is applied until the whole chain runs).

Examples
--------
Keep every other image (deterministic order):

    import sys

    in_path, out_path = sys.argv[3], sys.argv[4]
    with open(in_path, encoding="utf-8") as f:
        paths = [line.strip() for line in f if line.strip()]
    with open(out_path, "w", encoding="utf-8") as f:
        for path in paths[::2]:
            f.write(path + "\\n")

Keep only paths whose file name starts with "a" (reads the image file, so it
also demos why filters get absolute paths):

    import os, sys

    in_path, out_path = sys.argv[3], sys.argv[4]
    with open(in_path, encoding="utf-8") as f:
        paths = [line.strip() for line in f if line.strip()]
    with open(out_path, "w", encoding="utf-8") as f:
        for path in paths:
            if os.path.basename(path).startswith("a"):
                f.write(path + "\\n")

Filters run with the working directory set to your user folder ({HOME_DIR},
logged to the server console), so write files with explicit paths.

Your filters: files in <home>/filters/ are read after the shipped ones, win on a
name clash, and are never shipped/overwritten.
"""
