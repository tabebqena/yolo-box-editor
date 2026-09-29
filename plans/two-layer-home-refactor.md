# Plan: two-layer home refactor (Task 1 of 2)

## Goal

Split the app into a relocatable code directory (`app/`) and a user directory
(`YBX_HOME`), so a git clone and an installed copy behave identically and an
upgrade can replace only `app/` without touching user files.

## Decisions

- `YBX_HOME` resolution: `--home <dir>` > env `YBX_HOME` > parent of `app.py`.
- cwd for every action/hook/filter run: `YBX_HOME`.
- `*.a.yaml` / `*.a.py` / `shortcuts.a.txt` convention: dropped (hard).
- Code subdir name: `app/`.
- Create the user folders at startup when missing.
- `install.sh` is patched here; the `ybx.sh` installer is Task 2.

## Layout

```
<root>/                      # YBX_HOME (user files, never overwritten)
├── .venv/
├── actions/ hooks/ filters/ scripts/ shortcuts.txt
├── .recent_data_yamls.json .view_state.json
└── app/                     # BASE_DIR (replaced on upgrade)
    ├── app.py static/ templates/ requirements.txt VERSION
    └── actions/ hooks/ filters/ scripts/ shortcuts.txt   # built-ins
```

## Steps

1. `git mv` app code + built-in extension files into `app/`.
2. `app.py`: add `YBX_HOME` resolver/`configure_home()`, split built-in vs user
   constants, add `--home`, create user dirs + log the home at startup.
3. `app.py`: two-layer loaders (built-ins then user, user wins), remove `.a.*`.
4. `app.py`: `cwd=YBX_HOME`, `{SCRIPTS_DIR}`/`{HOME_DIR}` placeholders, env
   (`YBE_HOME`/`YBE_APP_DIR`/`YBE_SCRIPTS_DIR`), per-run cwd logging.
5. `.gitignore` root-anchored user paths; `pytest.ini` `pythonpath = app`.
6. Update `tests/test_app.py`.
7. Update `README.md`, `TUTORIAL.md`, `CHANGELOG.md`, `VERSION` (2.0.0).
8. Patch `install.sh`; hand the user the `AGENTS.md` changes to apply.

## Status

- [ ] implemented
- [ ] deferred
- [ ] cancelled
