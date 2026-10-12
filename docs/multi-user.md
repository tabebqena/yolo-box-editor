# Users and roles

By default the app is a **single-user local tool**: no account is needed and you
have full access. You can turn on multi-user mode by creating accounts — then
every sign-in gets a **role**, and the app enforces what each role may do
**on the server**, not just in the UI.

> This is a boundary between accounts on one instance. It is **not** a reason to
> expose the app to the internet. An **admin** can define and run actions that
> are shell commands, so only make someone an admin if you'd let them run
> commands as you. Keep the app on `127.0.0.1` or a trusted LAN.

## Roles

| | Admin | Restricted user |
|---|---|---|
| Label images | ✅ | ✅ |
| Author / edit actions, hooks, filters | ✅ | ❌ |
| Install / enable / remove extensions | ✅ | ❌ |
| Run actions, hooks, widgets, packages | ✅ (all) | only what an admin grants |
| Apply filters | ✅ (all) | only what an admin grants |
| Open a dataset | any path | only an admin-designated dataset |

**A lone account is always an admin**, and **no accounts at all** means the
local operator is the admin. So a fresh install or a one-person setup behaves
exactly as before.

## Turning it on

Create the first account from **Settings → Users** (only admins see that tab) or
from the command line:

```sh
ybe users --create alice
```

The first account is an admin. Later accounts are restricted until you promote
them (Users tab → change the role dropdown). You can also manage accounts with
`ybe users` (list / `--create` / `--update` / `--delete`).

Account ids: each account gets a short random **id**. Per-user folders and saved
state are keyed by that id, so renaming an account never moves data.

## What an admin sets up

### Datasets (Settings → Datasets)

Designate the `data.yaml` files users may open:

- **Add dataset** — a display name + the path to the `data.yaml`.
- **Label size limit** — the maximum label bytes a restricted user may store
  (0 = unlimited). Only their own **labels** count; symlinked images are free.

When a restricted user opens a designated dataset, the app builds a skeleton in
their folder:

```
<home>/users/<id>/datasets/<dataset-id>/
  data.yaml            # generated: relative path + images/<split>
  images/<split>  ->   the admin's images dir (symlink, no copy)
  labels/<split>/      # real, local — the user's own labels live here
```

So many users label the same images at once, each with their own labels, and the
admin's label folder is never touched. (On Windows, symlinks need Developer
Mode; without it the app reports a clear error.)

A restricted user picks a dataset from the **Allowed datasets** dropdown in
Settings → Dataset.

### Access (Settings → Access)

Grant a restricted account permission to run specific **actions**, **filters**,
**hooks**, **widgets** and **extensions** (packages). Pick the account, tick the
allowed names, and Save. An admin always has everything.

Default for a restricted account is **nothing** from these lists: the built-in
client-side editor actions (drawing, save, next/prev, …) always work, but any
action/hook/filter/widget/package that could run a command must be granted.

The check is transitive: if you allow an action whose `steps` call another
action via `action_<Name>`, the nested action must also be allowed, or the run
stops with "action not allowed".

### Granting an extension (any package)

Granting a **package** id is the whole story for that extension, not just its
backend:

- its **routes** (`/api/extension/<id>/…`) and **capabilities** become available,
- its **settings buttons** (`Settings` controls) may run, and
- its **UI panel** mounts: the panel script is served to a restricted user only
  for packages they were granted (the panel iframe itself still has no network,
  and every host call it makes goes through the same per-user checks).

So an admin enables a shipped/installed package once (Settings → Extensions,
admin-only) and then grants it per user in **Access**. A package a user was not
granted is hidden from their config and its panel never mounts.

The `tags` package is one example: granting `tags` gives a user the tag bar and
the tag routes, and the tag data is written under **their** home (see below).

### Extension data and the size cap

An extension writes its own files wherever it chooses. The tags package, for
instance, writes `tags.yaml` beside the user's generated `data.yaml` and its
per-image tag files under `datasets/<id>/tags/<split>/` — all inside the user's
home. The **size cap counts labels only**, so extension data is not capped
today; only an admin grants that extension in the first place.

## Where things live

- `<home>/users.json` — accounts (`{name: {id, role, hash}}`, owner-only). v1
  files migrate automatically.
- `<home>/policy.json` — the admin policy: designated datasets, the size cap and
  the per-account allowlists (owner-only).
- `<home>/users/<id>/state.json` — a user's saved dataset/view.
- `<home>/users/<id>/datasets/<dataset-id>/` — the user's materialised datasets.

Admins keep using `<home>` itself (the program home) for their own actions,
hooks, filters, extensions and scripts.

## Command line

```sh
ybe users                   # list accounts
ybe users --create NAME     # add (first account is an admin)
ybe users --update NAME     # change a password
ybe users --delete NAME     # remove
```

There is no CLI for the policy yet — use the web admin tabs. To reset roles, edit
`users.json` directly while the server is stopped.
