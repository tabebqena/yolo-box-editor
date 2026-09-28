# Task: fix infinite switch/restore loop on startup

## Plan
- [x] `maybeRestoreView`: only restore a remembered split when the server has
      none. Previously it forced the saved split (including `null` = All splits)
      on every `loadConfig`, undoing the split `resumeLastImage` had just set.
- [x] `resumeLastImage`: hard guard — switch split at most once per page load and
      fall back to the first image, so a mismatch can never reload forever.
- [x] `CHANGELOG.md` / `VERSION` (patch bump, no public interface change).

## Status
Implemented. JS syntax checked with `node --check`; `.venv/bin/python -m pytest
-q` → 125 passed. Reproduction: remember an image in `val` while the saved view's
active split is `null` (All splits); on start `resumeLastImage` switched to `val`,
then `maybeRestoreView` reset it to `null`, repeating endlessly
(`config loaded` / `split changed` spam).
