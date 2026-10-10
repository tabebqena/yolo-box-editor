# Building an extension from scratch to production

This is a hands-on guide to extending **yolo-box-editor**, from the smallest
possible action up to a full package with a backend, a sandboxed UI panel, its
own Python environment and self-contained tests. Two shipped packages are used
as **live examples** you can read end-to-end:

- **`app/extensions/tags/`** — the built-in Tags feature, a complete but focused
  package (backend + panel + filters + app actions).
- **`app/extensions/annotate/`** — a deliberately sophisticated example (model
  run, separate label folder, per-extension venv, canvas overlays). It ships
  `active: false`, so it is safe to read and to enable when you want to try it.

Everything an extension can do is already available to a loose file; a package
only changes **where** files may live and adds a few grouping features. Start
small and grow only as far as you need.

- [0. The pieces](#0-the-pieces)
- [1. A flat action](#1-a-flat-action)
- [2. A widget](#2-a-widget)
- [3. A package](#3-a-package)
- [4. Permissions](#4-permissions)
- [5. A settings form](#5-a-settings-form)
- [6. A backend plugin](#6-a-backend-plugin)
- [7. A sandboxed UI panel](#7-a-sandboxed-ui-panel)
- [8. Drawing on the canvas](#8-drawing-on-the-canvas)
- [9. A per-extension Python environment](#9-a-per-extension-python-environment)
- [10. Tests, next to the extension](#10-tests-next-to-the-extension)
- [11. Versioning, installing, shipping](#11-versioning-installing-shipping)
- [12. Production checklist](#12-production-checklist)
- [13. The two live examples](#13-the-two-live-examples)

## 0. The pieces

| Layer | Lives in | Use it for |
| ----- | -------- | ---------- |
| Action | `actions/*.yaml` | a shell command / step chain, bound to a key |
| Hook | `hooks/on_<event>.yaml` | run an action on an app event |
| Filter | `filters/*.yaml` | narrow the image list |
| Widget | `widgets/*.yaml` | a small dock form with controls |
| **Package** | `extensions/<id>/` | group the above + a backend + a panel |
| Backend plugin | `extensions/<id>/backend.py` | server-side Python: capabilities + HTTP routes |
| UI panel | `extensions/<id>/panel.js` | your own sandboxed interface |

Shipped code is read from `app/…`; **yours** is read from `YBX_HOME` (the folder
the app runs from, e.g. the repo root in a clone) and wins on a name clash.
There is no build step and no database.

The **format is versioned** by `EXTENSION_API_VERSION` (currently `6`). Put
`api_version: 6` at the top of every file you write. See
[extension packages](extensions.md#versioning-api_version).

## 1. A flat action

The smallest useful extension is an action — a named list of `steps`:

```yaml
# <home>/actions/hello.yaml
api_version: 6
name: Hello
steps:
  - echo "current image: {IMAGE_PATH}"
after_success:
  - app_refresh_images_list   # optional: run a core app action afterwards
```

Steps are shell commands with placeholders (`{IMAGE_PATH}`, `{LABEL_PATH}`,
`{DATASET_PATH}`, `{PYTHON}`, …). Bind it to a key in `shortcuts.txt`:

```
Hello <H> Say hello
```

Read [actions and hooks](actions-and-hooks.md) for the full placeholder table and
the `app_*` / `backend_*` / `action_<Name>` step kinds.

## 2. A widget

A widget is a dock form that runs actions with control values:

```yaml
# <home>/widgets/rename.yaml
api_version: 6
name: Rename
title: Rename
controls:
  - type: input
    id: suffix
    label: Suffix
    default: _v2
  - type: button
    label: Apply
    steps:
      - mv {IMAGE_PATH} {IMAGE_PATH}{WIDGET_SUFFIX}
```

Control ids become `{WIDGET_<ID>}` placeholders (upper-cased). See
[widgets](widgets.md).

## 3. A package

When you outgrow loose files, wrap them in a folder with a manifest:

```
<home>/extensions/my-tools/
  extension.yaml
  permissions.yaml
  actions/*.yaml
  hooks/on_<event>.yaml
  filters/*.yaml
  widgets/*.yaml
  scripts/*.py
  backend.py        # optional
  panel.js          # optional
  README.md
```

```yaml
# extension.yaml
api_version: 6
id: my-tools              # optional; the folder name is used otherwise
name: My Tools
description: A short summary shown in Settings → Extensions.
version: 1.0.0
author: you
active: true              # false lists the package but loads nothing from it
prefix: mytool            # optional route prefix (default: the id)
```

The package's subfolders are discovered automatically; there is no `provides:`
key. A flat file always wins over a package file of the same name, so packages
are strictly additive.

## 4. Permissions

Every package ships a `permissions.yaml` declaring what it uses. This is the
trust contract the app prints before installing and the honesty check it shows in
Settings → Extensions. **Lists are YAML block lists**, not inline `[...]`:

```yaml
# permissions.yaml
api_version: 1
ybe:                 # YBE methods the panel uses (explained on install)
  - state.read
  - capabilities
  - write.draw
backend: true        # ships backend.py (server-side Python)
ui: true             # ships panel.js (sandboxed)
routes:
  - ""
  - /dir
actions:
  - My action
app_actions:
  - clear_things
scripts:
  - helper.py
```

Anything shipped but not declared is reported as a permission issue. A panel may
only call the `ybe:` methods it declared. See
[permissions](extensions.md#permissions-and-installing) and the real
`app/extensions/tags/permissions.yaml`.

## 5. A settings form

A manifest `settings:` block becomes a Settings → Extensions subtab using the
same control format as a widget. A button runs an action (by name) or inline
steps; the other controls become `{WIDGET_*}`:

```yaml
settings:
  title: My Tools
  controls:
    - type: input
      id: suffix
      label: Suffix
      default: _v2
    - type: button
      label: Rename current
      action: rename          # runs actions/rename.yaml with {WIDGET_SUFFIX}
```

`app/extensions/example/extension.yaml` uses this for a small settings subtab;
the other controls are passed to the button's action as `{WIDGET_<ID>}`. (The
`annotate` example deliberately has **no** settings form: its sandboxed panel is
the single place its options live, so there is nothing to keep in sync.)

## 6. A backend plugin

A shipped package may add `backend.py` for server-side Python. It provides
**capabilities** (called from the panel as `YBE.call`) and **HTTP routes** — its
own Flask endpoints, mounted under `/api/extension/<prefix>`. Never use
`@app.route`: Flask cannot add routes after startup, and packages are
enabled/disabled live. Declare routes as a module-level `extension_routes` tuple
instead, which the app dispatches itself:

```python
# backend.py
from ybe import state

def _cap_get(key):
    # key is "<split>/<name>"; return plain JSON data
    return {"ok": True, "key": key}

def _get_thing():
    from flask import jsonify, request
    return jsonify(_cap_get(request.args.get("key", "")))

extension_routes = (
    {"rule": "", "methods": ["GET"], "handler": _get_thing},
)

def register(ctx):
    return {"capabilities": {"things.get": lambda key: _cap_get(key)}}
```

`ctx` is a `PluginContext` with `.app`, `.state`, `.config`, `.package` and
`require_writable()` (raises in read-only mode). The whole Tags feature lives in
`app/extensions/tags/backend.py` — read it as the reference, including its
per-dataset folder override (`<home>/.tags_extension.json`) and read-only guard.

> Backend plugins are trusted, in-process code and load **only from shipped
> packages** (`app/extensions/`). A user-installed package can still ship
> actions, hooks, filters, widgets, a panel and its own Python environment, but
> its `backend.py` is **never loaded** — there is **no opt-in** today. If you
> need server-side code, ship the package inside the app.

## 7. A sandboxed UI panel

Declare a `ui:` block to add your own interface:

```yaml
ui:
  api_version: 5          # the YBE plugin API version your script expects
  title: My Panel
  script: panel.js
  location: float         # float | left | right | bottom
  height: 220
```

`panel.js` runs in an **opaque-origin iframe** with no network and no access to
the app's page; it talks only through the async `YBE` object:

```js
(async function () {
  const img = await YBE.state.getImage();
  document.body.textContent = img ? img.name : 'No image';

  YBE.on('image_loaded', reload);
  async function reload() {
    const boxes = await YBE.state.getBoxes();     // a copy
    console.log(boxes.length, 'box(es)');
  }
})();
```

Reads: `state.getImage/getBoxes/getClasses/getActiveSplit/getImageCount/
isDatasetLoaded/getConfig`, plus `YBE.readonly` and `YBE.apiVersion`. Network is
proxied by `YBE.api.get/post`. Writes/actions: `callbacks.setBoxes`, `addBox`,
`selectBox`, `clearSelection`, `markDirty`, `draw`, `save`, `runAction`,
`refreshImage`, `toast`, `setStatus`, `openSettings`, `getSetting`/`setSetting`.
Events: `image_loaded`, `images_list_loaded`, `boxes_changed`,
`selection_changed`, `dataset_loaded`, `saved`, `readonly_changed`,
`before_/after_app_action`, `app_action`. The full list is in
[extension UI panels](extensions-ui.md).

`app/extensions/tags/panel.js` is a complete, small example (a tag bar that
reads/writes through `YBE.call('tags.*', …)` and reacts to `app_action`).

## 8. Drawing on the canvas

A panel can draw its **own** boxes on top of the dataset boxes, in a colour of
its choice, without touching the saved labels:

```js
// normalized {class, cx, cy, w, h}; optional color and label
await YBE.callbacks.drawBox({ class: 0, cx: 0.5, cy: 0.5, w: 0.2, h: 0.2,
                              color: '#e75480' });
// or replace them all at once
await YBE.callbacks.setDrawnBoxes(list, { color: '#e75480' });
await YBE.callbacks.setDrawnBoxesVisible(true);
await YBE.callbacks.clearDrawnBoxes();
```

These overlays are **render-only**: the app draws them but never hit-tests,
selects, drags or saves them, they are keyed per package, and they are cleared on
image change (so redraw on `image_loaded`). This is the annotate example's core:
the panel reads the model's boxes from its backend and overlays them.

If an extension wants its boxes **saved**, it is not special-cased — it pushes
them into the real list and saves:

```js
await YBE.callbacks.addBox({ class: 0, cx: 0.5, cy: 0.5, w: 0.2, h: 0.2 });
await YBE.callbacks.save();
// or replace the whole list:
await YBE.callbacks.setBoxes(list);
```

## 9. A per-extension Python environment

If your scripts need packages the app does not ship, declare them in the
manifest. The app can build a **dedicated virtualenv** (or use the app's
interpreter, or a specific one) and your steps reach it with `{EXT_PYTHON}`:

```yaml
# extension.yaml
python: venv                 # venv (default) | current | /path/to/python
requirements:
  - ultralytics>=8.0
requirements_file: requirements.txt   # optional, relative to the package
```

```yaml
# an action in your package
steps:
  - {EXT_PYTHON} {EXT_DIR}/scripts/run_model.py --data {DATA_YAML_PATH}
```

- `{EXT_PYTHON}` — the package's interpreter (falls back to `{PYTHON}` for loose
  files); `{EXT_ENV_DIR}` — its venv folder; `{EXT_DIR}` — the package folder.
- The venv lives in `<home>/extension_envs/<id>/` and survives updates.
- Build it with `ybe extension-env <id>`, the Settings → Extensions button, or
  the install prompt; it is never built silently.
- A backend plugin can also resolve the interpreter itself with
  `envs.resolve_id(<id>)` and run the script itself — that is how `annotate`
  starts a long model run in the background so the panel can poll progress
  instead of waiting on one request.

See [Python environments](extensions.md#python-environments) and
`app/extensions/annotate/extension.yaml` + `scripts/annotate_all.py`.

## 10. Tests, next to the extension

Keep a package self-contained by putting its tests in
`extensions/<id>/tests/test_<id>.py`. They are picked up by `python -m pytest -q`
from the repo root and can be run alone:

```bash
python -m pytest app/extensions/annotate -q
```

A test imports the app (`import app as ybe`), points the config paths at a
`tmp_path` fixture, and exercises the backend capabilities/routes directly
(no model or network needed):

```python
def test_backend_reads_separate_labels(clean_state, tmp_path):
    _module, caps = _backend()            # import this package's backend.py
    _dataset(tmp_path)
    out = tmp_path / "ext_labels"
    (out / "train").mkdir(parents=True)
    (out / "train" / "a.txt").write_text("0 0.5 0.5 0.2 0.2\n")
    assert caps["annotate.setDir"](str(out)) == {"output_dir": str(out)}
    assert caps["annotate.get"]("train/a.jpg")[0]["class"] == 0
```

Both live examples carry their tests: `app/extensions/annotate/tests/` and
`app/extensions/tags/tests/`.

## 11. Versioning, installing, shipping

- **`api_version`** — the file format version. Write the current one
  (`EXTENSION_API_VERSION`, now `6`); the app reads the last three versions and
  flags older files with an "outdated" badge. Bump it only when the format
  changes (never for your own package version).
- **Package `version:`** — your own free-text version shown in the UI.
- **`active:`** — the shipped default; a per-user override in
  `<home>/extensions.json` wins, toggled live from Settings → Extensions.
- **Install** a package you built:

  ```bash
  ybe install-extension /path/to/my-tools      # prints permissions + trust warning
  ybe extension-env my-tools                   # build its Python env, if declared
  ybe extensions                               # list installed packages
  ybe remove-extension my-tools
  ```

  Installed packages live in `<home>/extensions/<id>/`; the user copy wins over
  a shipped one on an id clash.

- **Keep docs in sync**: bump `app/VERSION` (major for a public-interface
  change, minor otherwise) and add a matching `CHANGELOG.md` entry (and an
  `app/CHANGES` note when user-facing).

## 12. Production checklist

- [ ] `api_version` set on every file; the package `version` and `author` filled.
- [ ] `permissions.yaml` lists **everything** shipped (the app flags gaps).
- [ ] Backend mutators call `ctx.require_writable()` / check read-only.
- [ ] Panel writes dataset strings with `textContent`, never `innerHTML`.
- [ ] Overlays redrawn on `image_loaded`; nothing saved unless intended.
- [ ] `python -m pytest -q` and `npm run test:js` pass.
- [ ] A short `README.md` and a Settings `settings:` form if it needs options.
- [ ] Installed and tried from a clean `<home>` with `ybe install-extension`.

## 13. The two live examples

| | `tags` | `annotate` |
| --- | --- | --- |
| Purpose | built-in tagging | model annotation + overlay |
| Manifest | `app/extensions/tags/extension.yaml` | `app/extensions/annotate/extension.yaml` |
| Permissions | `…/tags/permissions.yaml` | `…/annotate/permissions.yaml` |
| Backend | `…/tags/backend.py` (capabilities + routes) | `…/annotate/backend.py` (separate folder) |
| Panel | `…/tags/panel.js` (read/write via `YBE.call`) | `…/annotate/panel.js` (overlays) |
| Actions / scripts | `…/tags/filters/`, `scripts/` | `…/annotate/scripts/annotate_all.py` |
| Env | — | `python: venv` + `ultralytics` |
| Tests | `…/tags/tests/test_tags.py` | `…/annotate/tests/test_annotate.py` |
| Shipped | `active: false` (opt-in) | `active: false` (example) |

Read them side by side: `tags` shows the focused, everyday shape of a package;
`annotate` shows the advanced end — a per-extension environment, a backend that
owns files the core never sees, a long model run started in the background (the
panel polls its progress instead of blocking on one request), and canvas
overlays drawn from a sandboxed panel.

## Further reading

- [Extension packages](extensions.md) — manifest, permissions, enabling, envs.
- [Extension UI panels](extensions-ui.md) — the full `YBE` reference.
- [Extension actions & backend](extension-actions.md) — routes and capabilities.
- [Actions and hooks](actions-and-hooks.md) · [Filters](filters.md) · [Widgets](widgets.md).
