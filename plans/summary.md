# Plan summary

Condensed 2026-10-02 from all completed plans (originals removed). Every entry
below is implemented; version shown is the release that shipped it.

## Packaging / install / CLI
- **ybx.sh installer** (2.0.0→2.3.0): single downloadable script with
  `install`/`upgrade`/`version`/`check-update`, atomic `app/`-only upgrade with
  rollback, venv at `<dir>/.venv`, `--from PATH`, `--link` on by default.
  Replaces `install.sh` (which first added `.venv` + optional launcher).
- **Two-layer home refactor** (2.0.0): code in relocatable `app/`, user files in
  `YBX_HOME` (`--home` > `$YBX_HOME` > parent of `app.py`); loaders read shipped
  then user (user wins); runs use `cwd=YBX_HOME`; `.a.*` convention dropped.
- **`ybe` alias** (2.4.0), **launcher version/check-update/update** (2.5.0),
  **daemon mode + file logging** (2.6.0): `ybe start [--fg]`/`stop`/`restart`/
  `status`/`logs`; template `app/launcher.sh.in`; `--log-file`/`--no-reload`.
- **Update notifications** (2.7.0): weekly GitHub check (releases > tags > raw
  VERSION), cached in `.update_check.json`, daily UI notice + Settings group,
  `--no-update-check`.
- **Breaking-change warnings** (2.7.0/2.7.1): shipped `BREAKING.md`, applicable
  notes surfaced by `ybx.sh` and in the UI.

## Filters / action execution
- **Chainable filters** (1.0.0): replaces single filter; contract
  `filter.py <data.yaml> <split> <in_pipe> <out_pipe>` over absolute paths;
  topbar modal with up to 8 stacked selects; `--keep-filter-pipes`.
- **`{PIPE_PATH}` + backend-owned action chain** (0.7.2→0.10.0): `/api/actions/run`
  builds a work queue from `steps`+`after_success`, runs server entries inline
  and pauses at `app_*` entries (uid/resume); pipes auto-deleted (`--keep-pipe`).
- **Identity image refs** (0.11.0): all per-image endpoints/actions address
  `split/name` (`?key=`, `target`); per-dataset view persistence; backend rescan
  action. Fixes wrong-file actions when tab and server lists diverge.
- **Path-based image anchor** (0.7.1) and **canvas refresh after Archive**:
  current image follows `split/name` across list rebuilds; `loadImage`
  cache-busts so stale decoded frames can't reappear.

## UI / state
- **Resume screen state** (0.7.0): `--no-resume` + auto-resume newest dataset;
  per-dataset split+filter (`VIEW_KEY`) and show-boxes persisted; Tags-switch fix.
- **Reclaim image space** (2.2.0): all controls collapsed into one resizable
  right column; status text replaced by floating toasts + bell/unread badge;
  shortcuts moved into a Settings modal.
- **Debug flag**: `--debug` enables `[ybe]` verbose browser-console logging.
- **Multi-client presence** (0.10.1): server-tracked `POST /api/presence` with a
  TTL; dismissible banner whenever >1 client is active.
- **Fix infinite split/restore loop**: `maybeRestoreView` only restores a saved
  split when the server has none; `resumeLastImage` switches at most once.
- **Fix shortcuts `…` popup**: `.shortcuts` changed to `overflow: visible`.
