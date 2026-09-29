# Reclaim image space (UI layout)

## Goal
Maximize the canvas area. Today several in-flow strips (top bar, settings bar,
bottom hook-status bar, shortcut bar, and banners) change height at runtime and
resize the image. Relocate controls and replace status text with floating
notifications.

## Decisions (from user)
- "address bar" = the whole top toolbar row -> slim it down.
- Status -> **floating toasts** (never affect layout), with a **bell + unread
  badge** for sticky errors.
- Split / Filters / app Actions -> move into the right column (side panel).
- Shortcut bar -> removed from the bottom; Shortcuts section in the Settings
  modal that opens a modal listing all shortcuts.
- Shortcut-error and presence banners -> sticky toasts.
- Version: minor bump (UI-only).

## Plan
1. **Top bar**: keep only brand + `#notifBtn` (bell/badge) + `#settingsBtn`
   (gear) + `#sidePanelToggle`. Remove split/filters/actions/status/switches/
   change-dataset from it.
2. **Right column**: move `splitbox`, `filterBox` (`#filterBox`), `actionbox`
   markup into `#sidePanel` above `#boxList`. Add a left-edge drag handle to
   resize the panel; persist width in localStorage.
3. **Settings modal** (`#settingsModal`, gear): View switches (`readonlySw`,
   `taggingSw`, `autoSaveSw`) + Dataset (`recentSelect`, `dataYaml`,
   `setDataBtn`, `datasetPath`) + Shortcuts button. Auto-open once when no
   dataset is loaded.
4. **Shortcuts modal** (`#shortcutsModal`): shows the full shortcut list.
   Drop `applyShortcutOverflow` / "more" menu.
5. **Toasts** (`#toasts`, fixed, z-index above modals): `toast(msg, opts)`.
   info/success auto-dismiss; error/warning sticky + manual close; sticky ones
   bump the bell badge. Replace `#status`, `#folderStatus`, `#tagStatus`,
   `#hookStatusBar`, `#shortcutErrors`, `#presenceWarning`.
6. Docs/tests/version: README, TUTORIAL, CHANGELOG, `VERSION` 2.2.0; update
   `tests/test_app.py::test_index_serves_page`.

## Follow-up (2026-09-30): collapse everything into a right column
- Remove the full-width top bar; all controls live in a single right column.
- Order: app label + settings + bell + `Panel` button (always-visible header
  row) / dataset dirname / sep / split / sep / applied filter names in one line
  + `…` (opens the filter modal) / sep / actions (first few + `…` expander) /
  sep / boxes.
- `#sidePanelToggle` renamed to `Panel`; collapses the body only, keeps header.
- Column is resizable from its right edge.
- Toasts moved to the middle-bottom of the screen.

## Status
- [x] Implemented (2026-09-30)
- Deferred: none
- Cancelled: none
