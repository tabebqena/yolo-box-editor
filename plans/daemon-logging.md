# Plan: daemon mode + file logging

## Goal

`ybe` / `yolo-box-editor` should start the app **in the background by default**,
with commands to manage it, and log to a file while daemonized.

## Decisions

- `ybe` with no arguments prints the help/usage; `ybe start [--fg] [APP OPTIONS]`
  runs it (background by default, `--fg` for the foreground). Aliases:
  `daemon` = `start`, `fg` = `start --fg`. Management: `stop`, `restart`,
  `status`, `logs [-f]`. `version`/`check-update`/`update`/`upgrade` still go
  to `ybx.sh`.
- The launcher logic lives in a shipped template `app/launcher.sh.in`;
  `ybx.sh` bakes in the install dir + venv and writes
  `~/.local/bin/yolo-box-editor` (with a `ybe` symlink).
- Background start: `nohup python app/app.py --home DIR --no-reload
  --log-file DIR/ybe.log`, PID in `DIR/ybe.pid`, output appended to the log.
- App: new `setup_logging()` (root logger + optional file handler), CLI
  `--log-file PATH` and `--no-reload`; the Werkzeug access log drops the
  frequent `/api/presence` heartbeat lines.
- Git-ignored user files: `ybe.log`, `ybe.pid` (in `YBX_HOME`, root-anchored).
- Minor change -> version 2.6.0.

## Status

- [x] implemented
- [ ] deferred
- [ ] cancelled

Notes:
- Existing installs pick up the new launcher on the next `ybx.sh upgrade`.
- Verified: daemon start/stop/status/logs, `--fg`, and presence filtering.
