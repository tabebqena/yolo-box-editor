# Custom widgets

A **widget** is a small panel you define in a YAML file. It can hold **buttons**,
**dropdowns (select)**, **checkboxes** and **text inputs**, and it docks or floats
exactly like the built-in Tags / Boxes / Actions / Navigation / Save widgets.
Open **Settings → Layout** to choose each widget's **Show** checkbox and
**Location** (floating window, left/right/bottom panel).

Widgets are useful to bundle a few related controls: a dropdown/checkbox/input
collects a value and a button runs an action with those values.

## Where widgets live

Each widget is **one YAML file** in a `widgets/` folder. Shipped widgets live in
`app/widgets/` (only a comments-only `example.yaml` ships — copy it to start);
your widgets live in `<home>/widgets/` (the same folder as your `actions/`,
`hooks/`, `filters/` — next to the app, or wherever `--home` points). The user
folder is read after the shipped one and wins on a name clash.

Widgets are loaded fresh from disk, so after saving a file just reload the page.

## Format

```yaml
api_version: 3
name: My tools              # optional; the file name is used otherwise
title: My tools             # optional; shown in the frame header
controls:
  - type: button
    label: Clean labels
    action: MyCleanAction    # run a named action ...
  - type: button
    label: Rescan
    steps:                   # ... or inline steps / after_success
      - backend_rescan_images
  - type: select
    id: mode                 # exposed as {WIDGET_MODE}
    label: Mode
    options: [fast, safe]    # inline list, or a block of `- item` lines
    default: safe
  - type: checkbox
    id: dry_run              # exposed as {WIDGET_DRY_RUN} -> "1" or "0"
    label: Dry run
    default: true
  - type: input
    id: suffix               # exposed as {WIDGET_SUFFIX}
    label: Suffix
    placeholder: _v2
    default: ""
```

### Controls

- **button** — needs an `action:` (the name of any action, including one from an
  extension package) or inline `steps:` / `after_success:`. `label` defaults to
  the action name.
- **select** — needs an `id` and `options`. `default` is used when it is one of
  the options, else the first option.
- **checkbox** — needs an `id`. `default` is `true`/`false`.
- **input** — needs an `id`. Optional `placeholder` and `default`.

A control `id` must be letters, digits and `_` only, and cannot start with a
digit. Ids must be unique within one widget. A widget whose controls are invalid
is skipped and the reason is reported in the app (see `widget_errors`).

### Passing values to an action

When a button runs, the other controls' current values are sent with it and
become `{WIDGET_<ID>}` placeholders (the id upper-cased), alongside the usual
placeholders such as `{IMAGE_PATH}` and `{PIPE_PATH}`:

```yaml
  - type: button
    label: Export
    steps:
      - python {USER_SCRIPT_DIR}/export.py {IMAGE_PATH} --mode {WIDGET_MODE} --suffix {WIDGET_SUFFIX}
```

A checkbox value is `"1"` when checked and `"0"` when not. Values are
shell-quoted for you (do not add quotes around the placeholder). Buttons run
through the same action engine as the toolbar, so the run timeout, cascade limit
and `after_success` app actions all behave identically: a widget cannot do
anything an action cannot.

## Layout

Every widget appears in **Settings → Layout** as its own section with a **Show**
checkbox and a **Location** selector. Floating widgets are dragged by their
title bar; the small dock buttons snap them to an edge, and the `×` hides the
widget (show it again from the Layout tab). The chosen location and visibility
are remembered per browser (and mirrored to the server).

## A note on safety

A widget file only describes controls; it never contains code that runs in your
browser. A button is an action or a command that goes through the normal action
runner — so in **read-only mode** (`--readonly`) widget buttons that would write
files should be avoided, exactly like any other action.
