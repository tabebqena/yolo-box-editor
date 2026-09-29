# Task: `{PIPE_PATH}` placeholder + backend-owned action chain

## Plan
- [x] Backend: `PIPE_DIR`, create/validate/delete pipe file, `{PIPE_PATH}` value,
      `--keep-pipe` CLI flag.
- [x] Backend owns the run: `/api/actions/run` builds one work queue from
      `steps` + `after_success`, runs server entries inline and pauses at each
      client-side `app_*` entry (returned with a `uid`). The client posts
      `{uid, result}` to resume; the backend deletes the pipe at the end.
- [x] `steps` and `after_success` accept the same entries for actions and hooks:
      `app_*` (UI), `action_<Name>` (run inline), anything else (shell command).
- [x] Frontend: `runAction` loops over `client_action`/resume; removed the old
      client-side after_success driver and cleanup route/call.
- [x] Tests: mixed-order st/success, pause/resume, unknown uid, client-action
      abort, unknown `action_*` entry, cascade cap, pipe cleanup/keep, `steps`
      mixing an app action / `action_<Name>`, bare action name = shell command.
- [x] Docs: README, `actions/example.yaml`, `hooks/example.yaml`, CHANGELOG,
      VERSION bump (minor 0.7.2 → 0.8.0 → 0.9.0 → 0.10.0).

## Design
One pipe file per run. The backend holds execution state (uid → remaining work
queue) in `EXECUTIONS`. It runs server entries until an `app_*` entry, returns it
as `client_action` + `uid`, and resumes when the UI posts the result back.
Because it drives and finishes the run, it deletes the `{PIPE_PATH}` file itself
(unless `--keep-pipe`).

## Status
Implemented. `python -m pytest -q` → 140 passed. AGENTS.md was left untouched
(AI rule file) — its run-command line does not list `--keep-pipe` yet.
