# Breaking changes

# One entry per line:  <version> | <note>
# Versions are compared numerically (2.10.0 > 2.9.0). `ybx.sh check-update`,
# `ybx.sh upgrade` and the app's update notice read this file and warn the user
# about every entry newer than the installed version and up to the latest one.
2.6.0 | `ybe` / `yolo-box-editor` no longer run the app directly: with no arguments they print help. Use `ybe start [--fg] OPTIONS` (e.g. `ybe start --data /path/to/data.yaml`).
