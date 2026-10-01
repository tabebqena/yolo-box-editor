# Plan: update check + daily update notice

## Goal

Tell the user when a newer yolo-box-editor is available:

- check at every app start, and at most once a week (network is throttled);
- notify the user in the UI **once per day** while an update is available;
- show clear **how to update** steps for Linux/macOS (`ybx.sh`) and for other
  setups (git clone / pip, incl. Windows).

## Decisions

- Backend checks GitHub the same way `ybx.sh` does: `releases/latest` > newest
  tag > raw `main` VERSION, with a short timeout and all errors swallowed.
- Result cached in `<home>/.update_check.json` (`checked_at`, versions,
  `update_available`); a check is skipped when the cache is under 7 days old and
  the current version is unchanged. `force=True` bypasses the cache.
- A daemon thread performs the start check and re-checks every 6 h (the weekly
  throttle means the network is only hit when the cache is stale).
- `--no-update-check` disables it; `GET /api/update-check` returns the cached
  info, `POST {"force": true}` runs a fresh check. `/api/config` stays
  network-free (only reports `version`).
- UI: a sticky **info** toast once per day (localStorage date key) with a
  **How to update** button, recorded in the notifications bell (deduped); plus
  an **Updates** group in Settings showing current/latest and a manual
  **Check now**.
- Toast gains an optional action button (`opts.action`) and `opts.log` to record
  info messages in the bell.

## Status

- [x] implemented
- [ ] deferred
- [ ] cancelled

Notes:
- Verified with pytest; network paths mocked via `fetch_latest_version`.
