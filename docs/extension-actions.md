# Extension actions and backend plugins

An extension package can go beyond data files: it can ship **backend code** and
declare its own **app actions**. This page covers both, plus the app-action
**lifecycle bus** that lets extensions cooperate.

> The format is versioned by `EXTENSION_API_VERSION` (`5` as of this release);
> the sandboxed `YBE` API by `PLUGIN_API_VERSION` (`2`).

## Backend plugins

Add a `backend:` file to `extension.yaml`:

```yaml
api_version: 5
name: Tags
active: true
backend: backend.py
```

When the package is **active** (and **shipped** — see trust below), the server
imports `backend.py` and calls its `register(ctx)`. `register` may add Flask
routes to `ctx.app` and must return a capability table:

```python
def register(ctx):
    @ctx.app.route("/api/mytool", methods=["POST"])
    def api_mytool():
        ctx.require_writable()          # raises in read-only mode
        return {"ok": True}

    return {
        "mytool.do": lambda arg: do_it(arg),   # callable from the panel / API
    }
```

`ctx` exposes `app`, `state`, `config`, `package` and `require_writable()`.

Capabilities are reached from the package's panel as
`YBE.call('mytool.do', [arg])` (only the caller's own package is reachable) and
headlessly through `POST /api/extensions/call`
(`{"package": "...", "method": "...", "args": [...]}`). Read-only is enforced
inside the capability.

**Trust:** capabilities run in the server process, so by default only **shipped**
packages' backends are loaded. A user package can ship a `backend:` too, but it
is ignored unless/until you decide to trust it (matching the rule that evaluators
of untrusted code are opt-in).

## Extension app actions

Declare actions in the manifest:

```yaml
app_actions:
  - name: clear_tags
    label: Clear image tags
    shortcut: Alt+C          # optional default binding
    capability: tags.clear    # optional backend fallback
```

The action's fully-qualified id is `ext.<package>.<name>` (e.g.
`ext.tags.clear_tags`). It can be used:

- in an action/hook `steps` or `after_success`: `ext.tags.clear_tags`;
- as a shortcut (the manifest `shortcut`, rebindable in Settings → Shortcuts);
- from other JS through the host helper `callExtensionAction(package, name)`.

When the action runs, the host first emits an `app_action` event to the owning
package's **mounted panel** (the panel does the work and the UI updates). If the
panel is not mounted (e.g. a headless `steps` run), the declared `capability` is
called with the current image key `"<split>/<name>"`.

## The app-action lifecycle bus

Every app action — core `app_*` and extension `ext.*` — broadcasts
`before_app_action` and `after_app_action` to **all** mounted panels. Use it so
one extension can react to another (or to the app):

```js
YBE.on('after_app_action', (e) => {
  if (e.action === 'app_refresh_image_all') reloadMyData();
});
```

Payload: `{action, extension, name, source, depth, chain, ok?, error?}`.

### Recursion is bounded

The injected `YBE` stub remembers the `{chain, depth}` of the last lifecycle
event it saw and attaches it to any action call the panel makes while handling
that event. The host increments the depth; when `depth > MAX_EVENT_DEPTH`
(`8`) it **refuses the action** with an error instead of looping forever.
Actions started from the UI (a button or shortcut) begin at depth `0`.
