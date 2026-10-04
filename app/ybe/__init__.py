"""Internal support package for the yolo-box-editor Flask app.

`app/app.py` is the CLI entry point and the module the test suite imports; all
the reusable logic lives here. Nothing in this package imports `app`, so the
package can be reused without pulling in the CLI.

The modules, roughly bottom-up (each layer may use the ones above it):

    parsing         pure text/YAML/shortcut parsing (no globals)
    config          paths, catalogs and tuning constants (patched by tests)
    state           the live containers: STATE, USERS, EXECUTIONS, CLIENTS
    logging_setup   where log lines go, and the presence-heartbeat filter
    secret_key      the persistent Flask session-signing key
    pipes           shared command/pipe helpers for action and filter runs
    extensions      actions/hooks/filters: parse, validate, load, author YAML
    shortcuts       shortcuts.txt bindings
    tags            tags.yaml and per-image tag files
    dataset         data.yaml -> splits, image list, label/tag paths
    filters         the filter-chain runtime (narrow the image list)
    userconfig      config.json: recents, per-dataset views, UI settings
    commands        action execution (steps + after_success) as a queue
    auth            the login-account store
    update          the GitHub update check
    server          the Flask `app` and every HTTP route

`config` and `state` hold the values the tests monkeypatch, so every other
module reads them as `config.NAME` / `state.NAME` rather than importing the name
directly — that is what makes a patched value reach every caller.
"""
