# Plan: breaking-change warnings

## Goal

Warn the user (in the shell and in the UI) when a version has breaking changes,
driven by a file that lists them per version.

## Decisions

- Source of truth: shipped `app/BREAKING.md`, one line `<version> | <note>`
  (comments/blank lines ignored; versions compare numerically).
- Applicable notes = the installed version's own entry **plus** every entry in
  `current < version <= latest`, so a fresh install of a breaking release is
  warned (a pure update-range filter would hide it).
- `ybx.sh check-update` adds `breaking_changes:` and `breaking_notes:` lines;
  `upgrade` warns before installing; `install` warns about its own version.
- App: `parse/load/fetch_breaking_notes` + `applicable_breaking`; cache the list
  in `.update_check.json`; expose `breaking_changes`/`breaking` via
  `/api/config` and `/api/update-check`.
- UI: daily notice becomes a warning with a **What changed?** button; the update
  modal shows a **Breaking changes** section; Settings shows the marker.
- Also fixed latest-version detection to take the max of release and tags.
- `2.6.0` recorded as breaking (the `ybe OPTIONS` -> `ybe start OPTIONS` change).
- Minor change -> version 2.7.0.

## Status

- [x] implemented
- [ ] deferred
- [ ] cancelled

Notes:
- Verified with a temp install: fresh `2.6.0` and `2.5.0 -> 2.6.0` both warn.
- Pushed `main` and tag `2.6.0` first, then this as `2.7.0`.
