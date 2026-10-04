"""Internal support package for the yolo-box-editor Flask app.

`app/app.py` is the CLI entry point and the module the test suite imports; the
reusable pieces live here. Modules in this package must not import `app`:
shared, patchable configuration and runtime state belong in `ybe.config` and
`ybe.state`, everything else is plain functions.
"""
