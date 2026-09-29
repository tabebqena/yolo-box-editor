# Task: chainable filters

## Goal
Let several filters run as a chain: each receives the previous filter's output
list of image paths, narrows it, and hands its own result to the next filter.
Replaces the single-active-filter model.

## New contract (breaking)
`python filters/<Name>.py <data.yaml> <split> <input_pipe> <output_pipe>`
- `input_pipe` holds absolute image paths, one per line. The first filter gets
  the active split's images (all scanned images when the split is "All").
- `output_pipe`: the filter writes the kept absolute paths, one per line.
- Non-zero exit / timeout = failure; stderr is the detail. Empty output = empty.
- App maps each output path back to a scanned `{split, name}` (unknown paths are
  skipped and counted, duplicates dropped, order preserved).

## Runner
- Per invocation: a fresh temp dir (`FILTER_PIPES_DIR`), input pipe seeded with
  the active split's images; each filter's output becomes the next input.
- Chain stops at the first failure; previous state is kept.
- Temp dir is removed when done; `--keep-filter-pipes` keeps it (debugging).

## UI
- Topbar `Filters` button + summary replaces the single `<select>`.
- Modal with `min(count, 8)` stacked selects, pre-filled with the active chain,
  run top to bottom. Apply / Clear / Close.

## Status
- [x] Plan file
- [x] Backend: runner, STATE (`active_filters`), API, view persistence, CLI flag
- [x] Frontend: modal, summary button, array persistence
- [x] Migrate `filters/example.py` and `filters/no_revised.a.py`
- [x] Docs + `VERSION` 1.0.0 + CHANGELOG
- [x] Tests updated / added; `pytest -q` green

## Implemented
- `app.py`: `FILTER_PIPES_DIR`, `run_filter`/`run_filter_chain`/`apply_filters`,
  path-based `_parse_filter_output`, `active_filters` STATE, `api_filter` takes
  `{filters:[...]}` (legacy `{filter:name}` fallback), view stores `filters`,
  `--keep-filter-pipes`.
- `templates/index.html` + `static/app.js` + `static/style.css`: `Filters`
  button + modal with stacked selects (max 8).
- `filters/example.py`, `filters/no_revised.a.py`, README, CHANGELOG, VERSION.
- `tests/test_app.py`: rewritten filter tests + chain tests. 161 passed.

## Deferred
- `AGENTS.md` layout note still shows the old one-arg contract (AI rule file:
  user edits it).

## Notes
- `.view_state.json` stores `"filters": [...]`; a legacy `"filter"` string is
  still read as a one-item chain.
- `/api/filter` takes `{filters: [...]}`, falling back to `{filter: "Name"}`.
- AGENTS.md still documents the old contract; left for the user to edit (AI rule
  file).
