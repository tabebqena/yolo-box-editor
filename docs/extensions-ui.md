# Extension UI panels

An extension package can add a **UI panel** — a small interface of your own
(your own HTML/CSS/JS) that appears docked or floating like the built-in
widgets. The panel runs **sandboxed** in its own opaque-origin iframe with **no
network access** and **no access to the app's page**; it talks to the app only
through the async `YBE` object.

This is the one part of the extension system that is **code**, not data. Read
the [Trust & safety](#trust--safety) section before installing someone else's
panel.

## Manifest

Add a `ui:` block to `extension.yaml` (see
[extension packages](extensions.md)):

```yaml
api_version: 5
name: My Tools
active: true
ui:
  api_version: 3          # the YBE plugin API version your script expects
  title: My Panel         # frame header and Layout-tab label
  script: panel.js        # relative to the package folder
  location: float         # float | left | right | bottom (default float)
  height: 200             # optional initial body height in px
```

- Only **active** packages are mounted.
- `ui.api_version` is checked against the app's plugin API version; a panel
  written for a **newer** API is listed but not loaded.
- The panel appears in **Settings → Layout** with a **Show** checkbox and a
  **Location** selector, exactly like the built-in and custom widgets.

## `panel.js`

The host fetches your script and runs it inside the sandbox. There you build the
panel's DOM and call `YBE`:

```js
(async function () {
  const img = await YBE.state.getImage();
  const boxes = await YBE.state.getBoxes();
  document.body.textContent = img ? img.name + ' — ' + boxes.length + ' box(es)' : 'No image';

  YBE.on('image_loaded', () => location.reload()); // simple refresh hook
}());
```

Always write dataset strings (class names) with `textContent`, never
`innerHTML`.

## `YBE` reference

Everything is **async** — reads and writes return Promises.

### Read state
| Call | Returns |
| ---- | ------- |
| `YBE.state.getImage()` | `{split, name}` or `null` |
| `YBE.state.getImageIndex()` | current image index |
| `YBE.state.getBoxes()` | copy of the boxes (`[{class,cx,cy,w,h}]`) |
| `YBE.state.getClasses()` | copy of the class names |
| `YBE.state.getActiveSplit()` | active split name or `null` |
| `YBE.state.getImageCount()` | number of images in the current list |
| `YBE.state.isDatasetLoaded()` | boolean |
| `YBE.state.getConfig()` | read-only copy of the app's `/api/config` payload |
| `YBE.readonly` | boolean (kept up to date) |
| `YBE.apiVersion` | the plugin API version |

### Call the app's API

The sandbox has no network, so use the host as a proxy:

| Call | Effect |
| ---- | ------ |
| `YBE.api.get(path)` | GET a same-origin `/api/*` path |
| `YBE.api.post(path, body)` | POST JSON to a same-origin `/api/*` path |
| `YBE.api.request(method, path, body)` | GET/POST (only these two) |

Only `/api/*` paths are allowed and the auth routes
(`/api/login`, `/api/logout`, `/api/session`, `/api/password`) are refused, so a
panel cannot sign in/out or read the session. Writes are still gated by the
server's read-only rules.

### Write / act
All of these refuse in read-only mode.

| Call | Effect |
| ---- | ------ |
| `YBE.call(method, args)` | call one of **your package's** backend capabilities (see [backend plugins](extension-actions.md)); other packages are not reachable |
| `YBE.callbacks.setBoxes(list)` | replace the boxes (validated, clamped to 0..1) |
| `YBE.callbacks.selectBox(i)` / `clearSelection()` | change the box selection |
| `YBE.callbacks.markDirty()` / `draw()` | mark changed / repaint |
| `YBE.callbacks.save()` | save the current image |
| `YBE.callbacks.runAction(name, {confirm})` | run an action or extension action (confirm is on by default) |
| `YBE.callbacks.refreshImage(kind)` | `'pixels'` / `'labels'` / `'all'` |
| `YBE.callbacks.toast(msg, opts)` / `setStatus(msg)` | show a message |
| `YBE.callbacks.openSettings(tab)` | open Settings (optionally on a tab) |
| `YBE.callbacks.getSetting(key)` / `setSetting(key, value)` | per-panel prefs (no `localStorage` in the sandbox) |

### Events
`YBE.on(name, handler)` returns an unsubscribe function; `YBE.off` is also
available.

| Event | Payload |
| ----- | ------- |
| `image_loaded` | `{split, name}` |
| `images_list_loaded` | `{count}` |
| `boxes_changed` | `{}` |
| `selection_changed` | `{indices}` |
| `dataset_loaded` | `{dataYaml}` |
| `saved` | `{count}` |
| `readonly_changed` | `{readonly}` |
| `before_app_action` / `after_app_action` | `{action, extension, name, source, depth, chain, ok?, error?}` — see [extension actions](extension-actions.md) |
| `app_action` | `{action, extension, name, depth, chain}` — sent to a package's panel when one of its app actions runs |

The bridge also pushes `theme` (CSS variables) at start-up so the panel can match
the app's colours, reports the panel's height back so the frame sizes itself, and
sets the wrapper's `color-scheme` to the app's own so a transparent panel blends
in instead of showing a white canvas. Add your own `:root`/`body` background (or
`color-scheme`) in the panel to opt out and use a custom look.

## Trust & safety

- A panel is **code**. It runs with the sandbox's privileges and can call
  everything `YBE` exposes — including `runAction`, which can run commands. Treat
  installing a panel like installing an action: only from a source you trust.
- The sandbox is an **opaque-origin iframe** (`sandbox="allow-scripts"`): it
  cannot read or modify the app's page, DOM, `localStorage` or cookies.
- It has **no network**: the wrapper ships a strict Content-Security-Policy
  (`connect-src 'none'`, `img-src 'none'`, `form-action 'none'`), so it cannot
  call the app's API directly or phone home.
- The host answers **only** the whitelisted `YBE` methods and returns **copies**
  of state, so the panel can touch exactly what is documented here.
- `--readonly` is enforced both by the `YBE` callbacks and on the server.

## Limitations

- Everything is async; events can arrive in any order.
- Only plain data crosses the bridge (structured clone); no DOM nodes or
  functions from the host.
- The panel has no access to the host's CSS; use the `theme` variables.
- No `localStorage`; keep preferences through `getSetting`/`setSetting`.
- Each panel is a separate iframe (a little more memory, harder to debug).
