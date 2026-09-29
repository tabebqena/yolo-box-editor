# Task: `{PIPE_PATH}` action/hook placeholder

## Plan
- [x] Backend: `PIPE_DIR`, create/validate/reuse pipe file, add `{PIPE_PATH}` to
      action values, `POST /api/actions/pipe/cleanup`, `--keep-pipe` CLI flag.
- [x] Frontend: forward the run's pipe path through the `after_success` chain and
      delete it when the top-level run ends (skipped when `--keep-pipe`).
- [x] Tests: placeholder resolves to a real file, path reused across
      `after_success`, cleanup removes it, `keep_pipe` keeps it, invalid path not
      reused/deleted.
- [x] Docs: README, `actions/example.yaml`, `hooks/example.yaml`, CHANGELOG,
      VERSION bump (minor 0.7.2 → 0.8.0).

## Design
One pipe file per *top-level* action/hook run. The server creates it (in a temp
dir) on the first `/api/actions/run` and returns `pipe_path`; the client forwards
it on nested `after_success` action requests so every step and chained action
shares the same file. When the top-level run finishes (success or failure) the
client asks the server to delete it; `--keep-pipe` makes the server keep it.

## Status
Implemented. `python -m pytest -q` → 131 passed. AGENTS.md was left untouched
(AI rule file) — its run-command line does not list `--keep-pipe` yet.
