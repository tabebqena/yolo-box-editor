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
api_version: 4
name: My Tools
active: true
ui:
  api_version: 1          # the YBE plugin API version your script expects
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
  const tags = await YBE.state.getAvailableTags();
  const current = await YBE.state.getTags();
  document.body.textContent = '';
  const h = document.createElement('h3');
  h.textContent = 'Tags';
  document.body.appendChild(h);
  tags.forEach((t) => {
    const b = document.createElement('button');
    b.textContent = t + (current.includes(t) ? ' ✓' : '');
    b.addEventListener('click', async () => {
      try { await YBE.callbacks.toggleTag(t); } catch (e) { /* read-only */ }
    });
    document.body.appendChild(b);
  });

  YBE.on('tags_changed', (p) => console.log('tags now', p.tags));
}());
```

Always write dataset strings (tag/class names) with `textContent`, never
`innerHTML`.

## `YBE` reference

Everything is **async** — reads and writes return Promises.

### Read state
| Call | Returns |
| ---- | ------- |
| `YBE.state.getImage()` | `{split, name}` or `null` |
| `YBE.state.getImageIndex()` | current image index |
| `YBE.state.getBoxes()` | copy of the boxes (`[{class,cx,cy,w,h}]`) |
| `YBE.state.getTags()` | copy of the current image's tags |
| `YBE.state.getAvailableTags()` | copy of the dataset's `tags.yaml` list |
| `YBE.state.getClasses()` | copy of the class names |
| `YBE.state.getActiveSplit()` | active split name or `null` |
| `YBE.state.getImageCount()` | number of images in the current list |
| `YBE.state.isDatasetLoaded()` | boolean |
| `YBE.readonly` | boolean (kept up to date) |
| `YBE.apiVersion` | the plugin API version |

### Write / act
All of these refuse in read-only mode.

| Call | Effect |
| ---- | ------ |
| `YBE.callbacks.addTag(name)` / `removeTag(name)` / `toggleTag(name)` | edit the current image's tags (undo/dirty aware) |
| `YBE.callbacks.setTags(list)` | replace the current image's tags |
| `YBE.callbacks.setBoxes(list)` | replace the boxes (validated, clamped to 0..1) |
| `YBE.callbacks.selectBox(i)` / `clearSelection()` | change the box selection |
| `YBE.callbacks.markDirty()` / `draw()` | mark changed / repaint |
| `YBE.callbacks.save()` | save the current image |
| `YBE.callbacks.runAction(name, {confirm})` | run an action (confirm is on by default) |
| `YBE.callbacks.refreshImage(kind)` | `'pixels'` / `'labels'` / `'tags'` / `'all'` |
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
| `tags_changed` | `{tags}` |
| `selection_changed` | `{indices}` |
| `dataset_loaded` | `{dataYaml}` |
| `saved` | `{count}` |
| `readonly_changed` | `{readonly}` |

The bridge also pushes `theme` (CSS variables) at start-up so the panel can match
the app's colours, and reports the panel's height back so the frame sizes itself.

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
