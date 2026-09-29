# Task: fix shortcuts bar "…" popup showing nothing

## Goal
The shortcuts bar at the bottom hides overflowing entries and shows a `…`
button that should reveal the full list. Clicking it appeared to do nothing.

## Plan
- [x] Root cause: `#shortcutsMenu` is absolutely positioned *above* the bar
      (`bottom: calc(100% + 8px)`), but `.shortcuts` had `overflow: hidden`, so
      the popup was clipped and invisible even though the click toggled it.
- [x] Fix: `.shortcuts` now uses `overflow: visible`. The shortcut list still
      clips its own overflowing items via `.shortcut-items { overflow: hidden }`.
- [x] CHANGELOG (Fixed) and VERSION bump (patch 0.10.1 -> 0.10.2).

## Status
Implemented. CSS-only change; no public interface change.
