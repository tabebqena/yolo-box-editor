# Extension packages

An **extension package** is a folder that groups actions, hooks, filters and
widgets into one unit, with an optional **Settings → Extensions** subtab of its
own. Packages are an **additive layer**: the flat `actions/`, `hooks/`,
`filters/` and `widgets/` folders and their Settings tabs keep working exactly as
before. A package only changes *where* files may live — never *what* they do.

> If you just want one action, hook, filter or widget, use the flat folders and
> the existing Actions / Hooks / Filters tabs. A package is for grouping several
> related pieces (and adding a small settings panel).

## Layout

```
extensions/my-tools/
  extension.yaml          # the manifest (see below)
  backend.py              # optional backend plugin (routes + capabilities)
  panel.js                # optional sandboxed UI panel (see extensions-ui.md)
  actions/*.yaml          # same format as a flat action
  hooks/on_<event>.yaml   # same format as a flat hook
  filters/*.yaml          # same format as a flat filter
  widgets/*.yaml          # same format as a flat widget
  scripts/*.py            # optional helper scripts your steps call
  requirements.txt        # optional, if the manifest names it
  README.md               # optional
```

Shipped packages live in `app/extensions/`; yours live in `<home>/extensions/`.
The user folder is read after the shipped one and wins on an id clash.

## Versioning (`api_version`)

Every extension file may declare `api_version:`. The app keeps a **declared
support registry** (`app/ybe/compat.py`) — the history of what each format
version added, which versions were dropped, and the support window — so a format
change is an explicit decision, not a guess.

- **Within the window** — the app supports the newest
  `EXTENSION_API_SUPPORT_WINDOW` (3) format versions (currently `v3..v5`); they
  load normally.
- **Older than the window** — an explicitly-versioned file below the window is
  **skipped** with an explaining error: *"written for extension format vN, but
  this app supports the last 3 versions (v3..v5) — update the file, or start the
  app with `--allow-old-extensions` to force it"*. The user can **force** parsing
  with `--allow-old-extensions`.
- **Unversioned** — a file with no `api_version` is the original format and is
  read best-effort (the app has always parsed it).
- **Newer** — a file above `EXTENSION_API_VERSION` is never read: *"written for
  extension format vN, but this app supports vM — update yolo-box-editor to use
  it"*. A newer UI panel (`ui.api_version` above `PLUGIN_API_VERSION`, currently
  `3`) is likewise not mounted.

Errors appear in the actions/hooks/filters/widgets banner and, for packages, in
Settings → Extensions. The raw editor can still open a skipped file to read it,
and saving an edited file bumps its `api_version` to the current value.

The registry is exposed as `api_support` in `/api/config`; the older-version
fixtures under `tests/fixtures/ext_api/` are re-tested on every API update.

## Permissions and installing

Extensions are code, so an extension must ship a **`permissions.yaml`** that
declares what it uses. Built-in packages (`app/extensions/`) and installed ones
(`<home>/extensions/`) use the same file format; only their path differs.

```yaml
api_version: 1
ybe:                 # YBE bridge capabilities its panel uses (explained to you)
  - state.read
  - capabilities
backend: true        # ships backend.py (server-side Python)
ui: true             # ships panel.js (sandboxed)
routes: ["", /dir]   # HTTP routes, relative to /api/extension/<prefix>
actions: [My action]
hooks: [on_after_save]
filters: [By tag]
widgets: [My widget]
app_actions: [clear_tags]
events: [after_app_action]
scripts: [helper.py]
```

The app knows the meaning of every `ybe:` key, so it explains them when you
install; anything the package ships but does not declare is reported as a
**permission issue** in Settings → Extensions. The bridge enforces the `ybe:`
list per panel: a package may only call the methods it declared (a package with
no file is allowed, but flagged).

Install from the command line — it prints the declarations, explains each
permission and warns you before copying:

```bash
ybe install-extension /path/to/my-extension      # prompts for confirmation
ybe install-extension /path/to/my-extension --yes
ybe extensions                                   # list installed extensions
ybe extension-env my-extension                   # build its Python environment
ybe remove-extension my-extension
```

> **Only install extensions from authors you trust, or read their files
> yourself.** An extension may run server-side Python and shell commands.

## The manifest

```yaml
api_version: 5
id: my-tools              # optional; the folder name is used otherwise
name: My Tools
description: A short summary shown in the Extensions tab.
version: 1.0.0
author: you
active: true               # false keeps the package listed but loads nothing from it
prefix: mytool             # optional URL prefix for this package's routes (default: id)
backend: backend.py        # optional backend plugin (see extension-actions.md)

# Optional Python environment for this package's steps (see below). A package
# that needs packages the app does not ship declares them here.
python: venv               # venv (default) | current | /path/to/python
requirements:              # optional inline pip specs
  - ultralytics>=8.0
requirements_file: requirements.txt   # optional, relative to the package

# Optional extension-defined app actions, used as ext.<package>.<name>.
app_actions:
  - name: clear_tags
    label: Clear image tags
    shortcut: Alt+C

# Optional Settings > Extensions subtab. Its controls use the same format as a
# widget (buttons, select, checkbox, input). A button runs an action (by name)
# or inline steps; the other controls are passed as {WIDGET_<ID>} placeholders.
settings:
  title: My Tools
  controls:
    - type: checkbox
      id: dry_run
      label: Dry run
      default: true
    - type: button
      label: Refresh list
      steps:
        - app_refresh_images_list

# Optional extra event names this package emits. Hooks still fire on the
# built-in events (on_after_save, on_box_created, …) regardless.
events: []
```

The `parts` shown in the app are discovered automatically from the package's
subfolders, so `provides:` is not required.

## Python environments

A package's scripts often need packages the app does not ship (for example a
model runtime). The manifest can declare them:

```yaml
python: venv                 # venv (default) | current | /path/to/python
requirements:
  - ultralytics>=8.0
requirements_file: requirements.txt   # optional, relative to the package
```

- `python: venv` (the default when any requirements are declared) builds a
  **dedicated virtualenv** at `<home>/extension_envs/<id>/`, so the app's own
  environment stays clean and the env survives app updates.
- `python: current` installs the requirements into the app's interpreter.
- `python: /path/to/python` uses that interpreter as-is.

Inside the package's steps, use `{EXT_PYTHON}` to run with the package's
interpreter (it falls back to `{PYTHON}` for loose files), `{EXT_ENV_DIR}` for
the virtualenv folder and `{EXT_DIR}` for the package folder:

```yaml
steps:
  - {EXT_PYTHON} {EXT_DIR}/scripts/annotate.py {IMAGE_PATH}
```

The environment is **never built behind your back**:

- `ybe install-extension` prints what the package needs and offers to build it
  (`--env` builds without asking, `--no-env` skips);
- `ybe extension-env <id>` builds or refreshes it later (`--status` just prints
  the state, `--python CMD` chooses the base interpreter);
- Settings → Extensions shows the status and a **Set up environment** button.

Building runs `pip`, so it needs network access and may take a while.

## Enabling and disabling

A manifest's `active:` is the shipped default and is replaced on upgrade, so the
per-user on/off choice lives in `<home>/extensions.json`:

```json
{ "active": { "tags": true } }
```

This override wins over the manifest and survives updates. The tags extension
seeds it on first run/install: a **fresh install enables** it, while an **update
keeps the old tag-bar visibility** (`tags` / `ybe_tags_visible` in `config.json`).

Change it with the **Enabled** toggle on each package's **Settings →
Extensions** subtab (this applies immediately), by editing the file, or with the
helper script (a manual file/script change takes effect on the next start):

```bash
python app/scripts/migrate_tags_extension.py --home <user folder>          # migrate
python app/scripts/migrate_tags_extension.py --home <user folder> --disable
```

The Settings toggle applies **immediately**: the server loads/unloads the package's
backend (routes and capabilities) in place and the UI mounts/tears down its
panel, with no restart. Everything a package provides follows the flag — its
**actions, hooks, filters and widgets** disappear from the toolbar, Settings
builders, filter chain and Layout tab too, and come back when re-enabled. See
[extension actions](extension-actions.md) for how extensions declare routes.

## Precedence

Files are read in this order (later wins on a name clash):

1. shipped packages, then the shipped flat folders;
2. user packages, then the user flat folders.

A **flat file always wins over a package file** of the same name/source, so
adding a package can never change how an existing loose file resolves. Use the
manifest's `active: false` to keep a package visible under **Settings →
Extensions** while loading nothing from it (handy for examples).

## Settings → Extensions

The new **Extensions** tab lists every discovered package as a subtab showing its
manifest info (source, version, format status) and its parts. Each part has a
**YAML** button that opens it in the raw YAML editor. If the manifest has a
`settings:` block, that form appears at the bottom of the subtab.

The existing **Actions**, **Hooks** and **Filters** tabs are unchanged; they are
still where you edit loose (flat) extensions.

## UI panels

A package may also add a **sandboxed UI panel** — your own HTML/CSS/JS shown
like a widget. Panels are code and run isolated (opaque-origin iframe, no
network) and talk to the app only through the async `YBE` object. Declare one
with a `ui:` block in the manifest; see
[extension UI panels](extensions-ui.md).

## Events

A package's hooks fire on the built-in events (see
[actions and hooks](actions-and-hooks.md)). Declaring extra names under `events:`
reserves them for a future release where a widget control can emit them; for now
stick to the built-in event names.

## Prefix note

Reserved action prefixes (`app_`, `backend_`, `action_`, `on_`) still apply
inside packages: name a package action `Example: refresh` rather than `app_...`.
Extension **app actions**, however, are declared in the manifest's `app_actions:`
list under their bare name and reached as `ext.<package>.<name>` — so they never
collide with a core `app_*`. See [extension actions](extension-actions.md).
