# AGENTS.md

## Project
Single-file Flask app for labelling images in YOLO format. `app.py` (~1250 lines)
is the entire backend; the UI is plain `templates/index.html` + `static/app.js` +
`static/style.css` with **no build step**. No package layout, no database. The
`data.yaml` reader is hand-rolled — no PyYAML at runtime.

## Commands
- Run: `python app.py --data /path/to/data.yaml` (optional `--readonly` to
  block writes, `--debug` for verbose browser-console logging;
  `--host`/`--port`, default `127.0.0.1:5000`; Flask runs with `debug=True`).
- Tests (from repo root): `python -m pytest -q`; single test
  `python -m pytest tests/test_app.py::test_name -q`. `pytest.ini` puts the repo
  root on `pythonpath`.
- No lint / format / typecheck config exists.
- Tests import `PIL` (Pillow) but `requirements.txt` lists only `Flask`. Install
  Pillow (`pip install pillow`) or collection fails immediately.

## Layout / entrypoints
- `app.py` — CLI entry `main()`; module globals `BASE_DIR`, `STATE` (in-memory
  dataset state), and path constants `RECENT_FILE`, `ACTIONS_DIR`, `HOOKS_DIR`,
  `FILTERS_DIR`, `SHORTCUTS_FILE`, `SHORTCUTS_ADD_FILE`.
- Extension folders (rooted at repo root). A `.a` variant (`*.a.yaml`, `*.a.py`,
  `shortcuts.a.txt`) is read after the shipped file, wins on a name clash, and is
  git-ignored:
  - `actions/*.yaml` — one action per file (`steps`, optional `after_success`,
    optional `name`).
  - `hooks/on_<event>.yaml` — event taken from the filename, else `event_name:`;
    `active: false` skips it.
  - `filters/*.py` — run as `python filters/<Name>.py <data.yaml> <split>`; must
    print one `split/name` per line (`split` is `""` for All splits).
  - `scripts/*.py` — helpers named by action `steps`; the app never scans them.
  - `shortcuts.txt` / `shortcuts.a.txt` — `ACTION_NAME <KEY> label`.
- `VERSION` and `CHANGELOG.md` (Keep a Changelog); `README.md` / `TUTORIAL.md`
  are user-facing docs.

## Cross-file invariants
- Built-in actions are the `app_*` set in `APP_ACTIONS` (app.py:46) and are
  implemented in `static/app.js`. Adding/renaming one requires editing both.
- Hook events are `HOOK_EVENTS` (app.py:73), fired via `runHook('on_...')` in
  `static/app.js`, and documented in `hooks/example.yaml` — keep all in sync.
- Read-only is enforced server-side (label and tag writes return 403), not only
  in the UI.

## Tests
- `tests/test_app.py` monkeypatches the module-level path constants above and
  resets `STATE`; keep those names module-level so tests can patch them.
- Fixtures create real JPEGs (Pillow) in `tmp_path`; tests never touch the repo's
  own `actions/`, `shortcuts.txt`, or `.recent_data_yamls.json`.

## Repo conventions & boundaries

- **User standing workflow rules** (embodied here; sources of truth:
  `.roo/rules/Agents.md`):
  - Create/edit a short **plan file per task** under `plans/`; after
    implementing, record implemented/deferred/cancelled in the same file.
  - **Write a git commit after each change.**
  - Each Saturday, ask the user to condense the plans; if approved, summarize
    all completed plans into one file and remove the originals (keep the
    summary short).
  - **Never edit AI rule files yourself** — ask the user to edit them.
  - **Never use or store the user's passwords** unless explicitly asked; if you
    ever see one, give a notice only.
  - The user is a beginner — give advice when asked to do something stupid /
    anti-pattern, and **don't implement blindly**.

- If the public interface changed, update the major version, if you did minor changes , update the minot version.