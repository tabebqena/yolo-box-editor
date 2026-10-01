# Plan: `ybe` command alias

## Goal

Let the installed launcher be invoked as either `yolo-box-editor` or `ybe`.

## Decisions

- `ybx.sh` keeps writing `~/.local/bin/yolo-box-editor` and adds a `ybe`
  symlink to it (relative, so both keep working if the folder moves together).
- `--no-link` still installs neither; docs mention both names.
- Minor change -> version 2.4.0.

## Status

- [x] implemented
- [ ] deferred
- [ ] cancelled

Notes:
- Existing installs get the alias on their next `ybx.sh upgrade`.
