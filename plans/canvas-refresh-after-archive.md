# Task: canvas not refreshed after Archive action

## Plan
- [x] Trace the `after_success` chain `app_refresh_images_list` +
      `app_refresh_image`.
- [x] Fix: cache-bust the `imageEl.src` set inside `loadImage()` too, so the
      plain `/api/image/<idx>` URL can never be restored from the browser's
      decoded-image memory cache after the index mapping changes.
- [x] Docs: CHANGELOG (Unreleased → Fixed), VERSION bump.
- [ ] Tests: no JS test harness exists; frontend behaviour unchecked (deferred).

## Status
Implemented.

## Root cause
`app_refresh_images_list()` rescans, then calls `loadImage(idx)`, which
asynchronously sets `imageEl.src = '/api/image/' + currentIndex` (no
cache-buster). The chained `app_refresh_image()` sets the cache-busted URL
first, but `loadImage`'s label/tag fetch usually resolves afterwards and
overwrites it with the plain URL. That URL was already loaded *before* the
archive (same index, old file), so the `<img>` re-shows the stale decoded frame
even though `Cache-Control: no-store` is set. Now `loadImage` uses a unique
`?_=timestamp` like `app_refresh_image`, so whichever assignment wins is fresh.
