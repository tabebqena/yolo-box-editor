#!/usr/bin/env python3
"""yolo-box-editor scripts: helper scripts invoked by user actions.

Put your own helper programs in this scripts/ dir and call them from an action
in the actions/ folder. The app never scans this dir itself — a script runs only
when a `steps:` command names it, e.g.:

    # actions/MyAction.a.yaml
    steps:
      - python scripts/helper.py {DATA_YAML_PATH} {IMAGE_PATH} {LABEL_PATH}

The placeholders ({IMAGE_PATH}, {LABEL_PATH}, {DATASET_PATH}, {DATA_YAML_PATH},
{IMAGE_INDEX}) are substituted and shell-quoted by the app before the command
runs; the single tool output is shown in the result popup. See the README
"User actions" section for the placeholder list.

This example file is comments only and does nothing. Copy it (or any file here)
to a new <Name>.py to add a script, or write your own.

Contract
--------
There is no fixed interface: the script gets whatever the action's `steps`
command passes as arguments. By convention a script:

  - is run with the current working directory set to the app's folder, so
    relative paths resolve predictably;
  - prints to stdout (shown to the user) and exits 0 on success, non-zero on
    failure (a failing step stops the action and reports the error).

Example
-------
Tag the current image, then let the action refresh it (a shell-only command
would do; this shows the Python form):

    import sys
    from pathlib import Path

    image_path, tag = sys.argv[1], sys.argv[2]
    tag_file = Path(str(image_path).replace("images", "tags")).with_suffix(".txt")
    tag_file.parent.mkdir(parents=True, exist_ok=True)
    tags = tag_file.read_text(encoding="utf-8").split() if tag_file.exists() else []
    if tag not in tags:
        tags.append(tag)
        tag_file.write_text("".join(f"{t}\\n" for t in sorted(set(tags))),
                            encoding="utf-8")

Personal scripts: files ending in `.a.py` are git-ignored, so app updates never
touch them and they are never shipped. Keep your own work in `scripts/*.a.py`
and leave this example file as-is.
"""
