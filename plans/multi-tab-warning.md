# Task: multi-tab / multi-client presence warning

## Goal
When more than one client (tab, browser or machine) is using a running app
instance, show a dismissible message in every connected client warning that
changes may overwrite each other. Everything else stays exactly as it is: one
global `STATE`, no takeover, no read-only enforcement, no locks.

## Plan
- [x] Backend: module-level `CLIENTS` (cid -> last-seen monotonic time),
      `CLIENTS_LOCK`, `PRESENCE_TTL` (15s), `_prune_clients()`, and a new
      `POST /api/presence` route.
- [x] `/api/presence` body `{cid}` registers/refreshes a client; `{cid, bye}`
      removes it (sent via `sendBeacon` on `pagehide`). Reply is
      `{ok, count, others}` where `count` counts clients seen within the TTL.
- [x] Frontend: per-tab `CLIENT_ID` in `sessionStorage`, ping on load + every
      5s and on `visibilitychange`, `sendBeacon` removal on `pagehide`.
- [x] Frontend: dismissible banner (`#presenceWarning`) shown in every client
      while `count > 1`; dismissing hides it for that tab and resets once the
      overlap ends, so a later overlap warns again.
- [x] Tests: register/count, multiple clients, same cid is one, `bye` removal,
      stale pruning, missing cid is a 400; fixture resets `CLIENTS`.
- [x] Docs: CHANGELOG, README note, VERSION bump (patch 0.10.0 -> 0.10.1).

## Design
The server is the single source of truth for presence so that different
browsers/machines are detected too (a frontend-only `BroadcastChannel` would
only cover tabs in the same browser). `time.monotonic()` is used for the TTL so
wall-clock changes cannot pin a dead client. Presence is purely informational:
no endpoint is blocked and no write behavior changes.

## Status
Implemented. `python -m pytest -q` -> 146 passed. AI rule files left untouched.
