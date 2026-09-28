# Task: `--debug` verbose browser-console logging

## Plan
- [x] Backend: add `STATE["debug"]`, `--debug` CLI flag, expose `debug` in `/api/config`.
- [x] Frontend: `debugMode` + `dbg()` / `dbgWarn()` helpers (prefix `[ybe]`).
- [x] Instrument key flows: config load, image load, navigation, save, tags,
      user actions / `after_success` chain, hooks, rescan, box create/edit/delete,
      undo/redo, uncaught errors.
- [x] Tests: `DEFAULT_STATE["debug"]`, assert `/api/config` reports it.
- [x] Docs: README run section, CHANGELOG (Unreleased), AGENTS.md run command.

## Status
Implemented. `python app.py --data … --debug` now enables verbose `[ybe]` logs in
the browser console; off by default. `python -m pytest -q` → 120 passed.
