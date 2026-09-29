# Plan: ybx.sh installer (Task 2 of 2)

## Goal

A single downloadable script that installs, reports and updates
yolo-box-editor, replacing `install.sh`.

## Decisions

- Name: `ybx.sh`; subcommands `install`, `upgrade`, `version`, `check-update`.
- `--link` on by default (`~/.local/bin/yolo-box-editor`); `--no-link` opts out.
- Default install dir: `$XDG_DATA_HOME/yolo-box-editor` or
  `~/.local/share/yolo-box-editor`.
- Version resolution: `--version` > `releases/latest` > newest tag
  (API, then `git ls-remote`) > `main`.
- `--from PATH` installs from a local folder or `.tar.gz` (offline / clone).
- Atomic upgrade: stage `<dir>/.app.staging.$$`, validate `app.py` + `VERSION`,
  `mv app -> .app.old.$$`, `mv staging -> app`, drop old; rollback on failure.
- venv at `<dir>/.venv`; the launcher passes `--home <dir>`.
- `check-update`: three lines (`exit code:`, `current_version:`,
  `latest_version:`); exit 0 = update, 1 = current, 2 = unknown.
- No `jq`: JSON is parsed with `sed`/`grep`; usage is a heredoc so
  `curl | bash -s -- …` works.

## Status

- [x] implemented
- [ ] deferred
- [ ] cancelled

Notes:
- `install.sh` removed; `ybx.sh` supersedes it.
- Verified locally: `--from .` install, reinstall preserves user files and
  `.venv`, launcher runs, `version` / `check-update` exit codes.
- Remote `main` still has the pre-`app/` layout until this is pushed, so the
  network `install`/`check-update` path is only fully exercisable after a push
  (or a tag/release is published).
