# Task: Linux `install.sh`

## Plan
- [x] Add `install.sh`: checks for `python3`, creates `.venv`, installs
      `requirements.txt`, optional `--link` launcher in `~/.local/bin`.
- [x] Docs: README Run section, CHANGELOG, VERSION bump (minor).
- [x] Run `python -m pytest -q` and a `bash -n` syntax check.

## Status
Implemented. `bash install.sh` sets up `.venv` and prints how to run the app;
`--link` also adds a `yolo-box-editor` command on `PATH`.
