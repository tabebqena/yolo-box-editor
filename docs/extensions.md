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
  actions/*.yaml          # same format as a flat action
  hooks/on_<event>.yaml   # same format as a flat hook
  filters/*.yaml          # same format as a flat filter
  widgets/*.yaml          # same format as a flat widget
  scripts/*.py            # optional helper scripts your steps call
  README.md               # optional
```

Shipped packages live in `app/extensions/`; yours live in `<home>/extensions/`.
The user folder is read after the shipped one and wins on an id clash.

## The manifest

```yaml
api_version: 3
id: my-tools              # optional; the folder name is used otherwise
name: My Tools
description: A short summary shown in the Extensions tab.
version: 1.0.0
author: you
active: true              # false keeps the package listed but loads nothing from it

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

## Events

A package's hooks fire on the built-in events (see
[actions and hooks](actions-and-hooks.md)). Declaring extra names under `events:`
reserves them for a future release where a widget control can emit them; for now
stick to the built-in event names.

## Prefix note

Reserved action prefixes (`app_`, `backend_`, `action_`, `on_`) still apply
inside packages: name a package action `Example: refresh` rather than `app_...`.
