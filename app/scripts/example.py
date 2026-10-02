#!/usr/bin/env python3
"""yolo-box-editor scripts: helper scripts invoked by user actions.

Put your own helper programs in <home>/scripts/ and call them from an action in
<home>/actions/. This shipped file lives in the app's own app/scripts/. The app
never scans either dir itself — a script runs only when a `steps:` command names
it, e.g.:

    # <home>/actions/MyAction.yaml
    steps:
      - {PYTHON} {USER_SCRIPT_DIR}/helper.py {DATA_YAML_PATH} {IMAGE_PATH} {LABEL_PATH}

The placeholders ({IMAGE_PATH}, {LABEL_PATH}, {DATASET_PATH}, {DATA_YAML_PATH},
{IMAGE_INDEX}, {APP_DIR}, {HOME_DIR}, {APP_SCRIPT_DIR}, {USER_SCRIPT_DIR},
{PYTHON}) are substituted and shell-quoted by the app before the command runs;
the single tool output is shown in the result popup. Start a Python step with
{PYTHON} (the interpreter running the app) rather than `python`, which may not be
on PATH. See the README "User actions" section for
the placeholder list. Steps run with the working directory set to your user
folder, so `scripts/helper.py` also works relatively (shipped helpers are
`{APP_SCRIPT_DIR}/...`).

This example file is comments only and does nothing. Copy it to a new <Name>.py
in <home>/scripts/ to add a script, or write your own.

Contract
--------
There is no fixed interface: the script gets whatever the action's `steps`
command passes as arguments. By convention a script:

  - is run with the current working directory set to your user folder
    ({HOME_DIR}, logged to the server console), so relative paths land there;
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

Your scripts: keep your own work in <home>/scripts/ (never shipped or
overwritten); this example file stays in the app's app/scripts/.
"""
