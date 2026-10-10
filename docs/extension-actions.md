# Extension actions and backend plugins

An extension package can go beyond data files: it can ship **backend code** and
declare its own **app actions**. The backend is where an extension adds
**server-side Python** — chiefly **Flask HTTP routes** (its own API endpoints)
and **capabilities** (functions the sandboxed panel can call). This page covers
both, plus the app-action **lifecycle bus** that lets extensions cooperate.

> The format is versioned by `EXTENSION_API_VERSION` (`6` as of this release);
> the sandboxed `YBE` API by `PLUGIN_API_VERSION` (`5`). A package must also ship
> a [`permissions.yaml`](extensions.md#permissions-and-installing) declaring the
> `ybe:` capabilities and artifacts it uses; the bridge enforces it per panel.

## Backend plugins

A backend plugin is how an extension serves **its own Flask HTTP routes** and
exposes **capabilities**. Add a `backend:` file to `extension.yaml`:

```yaml
api_version: 6
name: Tags
active: true
backend: backend.py
```

When the package is **enabled** (and **shipped** — see trust below), the server
imports `backend.py` and calls `register(ctx)`. `register` returns a capability
table; HTTP routes are declared in a module-level `extension_routes` tuple:

```python
from flask import jsonify, request

def list_items():
    return jsonify({"items": []})

def do_it():
    return jsonify({"ok": True})

def register(ctx):
    return {
        "capabilities": {"mytool.do": lambda arg: do_it()},
    }

extension_routes = (
    {"rule": "/items", "methods": ["GET"], "handler": list_items},
    {"rule": "/items/<int:key>", "methods": ["POST"], "handler": do_it},
)
```

`ctx` exposes `app`, `state`, `config`, `package` and `require_writable()`.

`register` may also return the routes (`{"capabilities": {...}, "routes": [...]}`),
and it is optional if the package only declares routes.

### Filling a filter dropdown from live data

A package can contribute the options of one of its filters' arguments. Return a
`filter_options` map of `token -> callable()`, and use that token as the
argument's `options:` in the filter YAML:

```python
def register(ctx):
    return {
        "capabilities": {"mytool.do": lambda: do_it()},
        # the filter's `options: {MY_THINGS}` becomes this callable's list
        "filter_options": {"{MY_THINGS}": lambda: ["a", "b"]},
    }
```

The callable runs whenever the app builds the Filters dropdown (and again when it
validates the chain), so it can read the loaded dataset. The tags package uses
this to fill `{DATASET_TAGS}` from the dataset's `tags.yaml`; a filter with an
empty dropdown falls back to a text field.

### Routes are namespaced, and run through a dispatcher

Every route is mounted under a fixed host prefix plus the package's own prefix:

```
/api/extension/<prefix><rule>
```

`<prefix>` is the manifest `prefix:` when set, else the package id, sanitized to
`[a-z0-9_-]`. So with `prefix: mytool`, `rule: /items` is served at
`/api/extension/mytool/items`. **Prefixes must be unique**: if two discovered
packages claim the same one, the later one is refused on enable (the first in
discovery order wins). This is checked at setup, so rules can never collide with
each other or with core routes.

The app installs a **single** startup catch-all (`/api/<path:subpath>`) that asks
the host to match the request against the *currently enabled* packages. So:

- an extension **must not** use `@app.route` (Flask cannot accept rules after the
  first request); declare `extension_routes` instead;
- handlers run inside a normal Flask request context, so `request`, `session`,
  `g` and `current_app` all work, and the return value may be a `Response`, a
  `(body, status)` tuple, a `dict`/`list` (JSON), or a string;
- `rule` is relative to the mount (an empty rule is the mount point itself);
  handlers receive any URL parameters as keyword arguments;
- enabling/disabling a package swaps its routes in and out **with no restart**.

### Why not a plain `@app.route`?

The obvious way to add an endpoint would be for `backend.py` to call
`@app.route` (or `app.add_url_rule`) at import time. That does **not** work
here, for three reasons:

- **Flask freezes its URL map.** Routes are registered while the app starts up;
  calling `add_url_rule` after the app has handled its first request raises, and
  there is no supported way to add or remove a route later.
- **Packages are enabled and disabled at runtime.** The Settings → Extensions
  toggle applies immediately, with no restart. A route baked into the app's URL
  map could not be added or removed at that moment, so the toggle could not work.
- **A disabled (or broken) package must not affect startup.** Importing every
  backend eagerly would run arbitrary code for packages you never enable, and one
  bad backend could stop the app from booting.

So the app installs **one** catch-all rule (`/api/<path:subpath>`) whose view
asks the host to match the request against the **currently enabled** packages'
`extension_routes`. Enabling a package adds its routes to the live registry and
disabling removes them — both without touching Flask's URL map. A disabled
package simply returns 404. The `/api/extension/<prefix>` namespace plus the
unique-prefix check keep these routes from colliding with core routes or with
each other.

Capabilities are reached from the package's panel as
`YBE.call('mytool.do', [arg])` (only the caller's own package is reachable) and
headlessly through `POST /api/extensions/call`
(`{"package": "...", "method": "...", "args": [...]}`). Read-only is enforced
inside the capability (and each mutating route).

**Trust — backend code is shipped-only.** Capabilities and route handlers run
inside the server process with full app access, so a backend is loaded **only**
for a **shipped** package (`app/extensions/<id>/`). A user package
(`<home>/extensions/<id>/`) may declare `backend:`, but it is **never loaded** —
there is **no opt-in today**, no setting or flag that trusts it. To run
server-side Python, ship the package inside the app. Everything else a user
package provides (actions, hooks, filters, widgets, its panel and its Python
environment) works normally.

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
