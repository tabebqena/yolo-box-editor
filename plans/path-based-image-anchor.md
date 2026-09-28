# Task: track the current image by path across image-list changes

## Plan
- [x] Add `imageKey(entry)` (`split/name`) as the stable identity.
- [x] Add `captureImageAnchor(follow)` — snapshot of the current image (and,
      when following, the images after it) before a list rebuild.
- [x] Add `resolveImageAnchor(anchor)` — same path, else first surviving
      follower (follow anchors), else clamped position (follow) / first image.
- [x] `app_refresh_images_list` (Archive/rescan) uses a follow anchor.
- [x] `setSplit` / `setFilter` use a non-follow anchor: keep the image when it
      is still present, otherwise start at the first.
- [x] `loadConfig` accepts `opts.anchor`; `resumeLastImage` uses `imageKey`.
- [x] Docs: README (actions table, after_success, filters), CHANGELOG
      (Unreleased → Changed), VERSION 0.7.1.
- [ ] Tests: no JS runner in the repo; anchored path resolution is untested
      (deferred). Backend suite still 125 passed.

## Status
Implemented.

## Why
`app_refresh_images_list` used to keep `currentIndex` (clamped), which only
happens to be right for a flat sorted list. Once a filter like `no_revised`
(non-deterministic result as images are reviewed) or an action that removes
files is involved, index → image is unstable. Anchoring by `split/name` makes
the current position independent of the list rebuild, and the last image was
already persisted by path, so resume state is untouched by list changes.
