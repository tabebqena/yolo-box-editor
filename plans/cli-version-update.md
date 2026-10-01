# Plan: version / check-update / update on the launcher

## Goal

`ybe` and `yolo-box-editor` should support `version`, `check-update` and
`update` directly (delegating to `ybx.sh`), alongside their normal app flags.

## Decisions

- The generated launcher inspects `$1`: for `version` / `check-update` /
  `update` / `upgrade` it execs the installed `<dir>/ybx.sh`, forwarding the
  command plus `--dir <dir>`; anything else runs the Flask app as before.
- `ybx.sh` accepts `update` as an alias of `upgrade`.
- If `<dir>/ybx.sh` is missing the launcher downloads it (needs `curl`).
- Minor change -> version 2.5.0.

## Status

- [x] implemented
- [ ] deferred
- [ ] cancelled

Notes:
- Existing installs get the new launcher on their next `ybx.sh upgrade`.
- Verified with a temp `--from .` install: `ybe version`, `ybe check-update`,
  `ybe update` all reach ybx.sh.
