# Task: address images by identity (`split/name`), not index

## Plan
- [x] Backend: `_entry_by_key` + `_request_entry`; remove `_entry(idx)`.
- [x] `/api/actions/run` takes `target` (`split/name`); unknown/missing -> 400.
- [x] `/api/image`, `/api/labels`, `/api/tags` move to `?key=<split/name>`.
- [x] Frontend: `keyQuery()` for all per-image URLs; `target` in the action body.
- [x] Backend actions (`backend_*`): `backend_rescan_images` runs inline via
      `_advance_execution`; `_rescan_images()` shared with `POST /api/images/rescan`.
- [x] `GET /api/images` (in-memory list) + `app_reload_images_list` (UI re-read,
      no disk scan); `applyImagesPayload()` shared with `app_refresh_images_list`.
- [x] Per-dataset view persistence: `VIEW_FILE` (`.view_state.json`), saved on
      `/api/split` / `/api/filter`, restored by `_resume_last_dataset`.
- [x] `actions/Archive.a.yaml`: `backend_rescan_images` + `app_reload_images_list`
      + `app_refresh_image`.
- [x] Tests converted `idx` -> `target` / `?key=` + new tests (target resolution,
      wrong-position prevention, backend action, `GET /api/images`, persistence).
- [x] Docs (README, example yamls, CHANGELOG), VERSION 0.11.0, `.gitignore`.
- [ ] Reads on a client whose list is stale after a restart are not re-synced by
      the server (deferred; identity naming removes the data-loss risk).

## Status
Implemented.

## Why
The action request carried only `idx`, which the backend resolved against its own
`STATE["images"]`. An open tab and the server can diverge (a `--debug` reloader
restart dropped the server's active filter while the tab kept its filtered list),
so index `5` was `val/0014122.jpg` on screen but `val/0000012.jpg` on the server
— `Archive` moved the wrong file and the one on screen stayed. Identity naming
makes every action/hook/read hit the exact file the client names; per-dataset
view persistence removes the main divergence source. `backend_rescan_images`
lets an action refresh the server list explicitly (no rescan on every
`/api/config`, keeping page loads cheap), with `app_reload_images_list` doing the
UI re-read without a second disk scan.
