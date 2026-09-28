# Task: resume the whole screen state on start

## Plan
- [x] Backend: factor `_load_dataset(path)` out of `main()`/`api_data()`; add
      `_resume_last_dataset()` (newest existing entry of
      `.recent_data_yamls.json`); new `--no-resume` flag.
- [x] Frontend: replace filter-only `FILTER_KEY` persistence with a per-dataset
      `VIEW_KEY` that stores split **and** filter; restore split even when no
      filter is active (`maybeRestoreView`).
- [x] Frontend: persist/restore the box-overlay show/hide (`app_show_hide`) via
      `SHOW_BOXES_KEY`.
- [x] Frontend: fix the `Tags` switch — its checked state was restored but the
      `taggingEnabled` flag was not, so the tag bar stayed hidden.
- [x] Tests: `_load_dataset` / `_resume_last_dataset` (most recent, skip missing,
      none clears state); helper now mkdirs its root.
- [x] Docs: README, TUTORIAL, CHANGELOG (Unreleased → Added), VERSION 0.7.0.
- [x] AGENTS.md run command needs `--no-resume` added — asked the user (AI rule
      files are never edited by me).

## Status
Implemented. `python -m pytest -q` → 125 passed. Auto-resume is default; the
existing `taggingEnabled` / `autoSave` / `sidePanelOpen` keys already covered
those switches. `readonly` is intentionally **not** persisted (a stale soft lock
would look like a broken app; `--readonly` remains server-enforced).
