# Task: `{PIPE_PATH}` action/hook placeholder

## Plan
- [x] Backend: `PIPE_DIR`, create/validate/delete pipe file, `{PIPE_PATH}` value,
      `--keep-pipe` CLI flag.
- [x] Backend owns the run: `POST /api/actions/run` runs `steps` + the whole
      `after_success` chain, executing server-side actions inline and pausing at
      each client-side `app_*` entry (returned with a `uid`). The client posts
      `{uid, result}` to resume; the backend deletes the pipe at the end.
- [x] Frontend: `runAction` loops over `client_action`/`resume` instead of
      driving the chain itself; removed the old client-side after_success code
      and cleanup route/call.
- [x] Tests: mixed-order chain, pause/resume, unknown uid, client-action abort,
      unknown/hook after_success entry, cascade cap, pipe cleanup/keep.
- [x] Docs: README, `actions/example.yaml`, `hooks/example.yaml`, CHANGELOG,
      VERSION bump (minor 0.7.2 → 0.8.0).

## Design
One pipe file per run. The backend holds execution state (uid → remaining
after_success work) in `EXECUTIONS`. It runs server-side actions until an
`app_*` entry, returns it as `client_action` + `uid`, and resumes when the UI
posts the result back. Because the backend drives and finishes the run, it
deletes the `{PIPE_PATH}` file itself (unless `--keep-pipe`).

## Status
Implemented. `python -m pytest -q` → 136 passed. AGENTS.md was left untouched
(AI rule file) — its run-command line does not list `--keep-pipe` yet.
