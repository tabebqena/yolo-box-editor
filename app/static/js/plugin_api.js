// app/static/js/plugin_api.js — sandboxed UI-panel bridge (host side)
'use strict';

// ------------------------------------------------------------------------- //
// client-side extension API: sandboxed iframe panels + async YBE bridge
//
// An extension package may declare a `ui:` panel. The host fetches the panel
// script (the sandboxed iframe has no network of its own), builds an
// opaque-origin wrapper document (sandbox="allow-scripts" + a strict CSP) and
// mounts it in the dock registry. The extension inside talks only to `YBE`,
// which is a postMessage stub; every request is answered here by a whitelisted
// capability table, so a panel can touch exactly what this file exposes.
// ------------------------------------------------------------------------- //
// Mounted panels: name -> { packageId, name, iframe, target, listener }.
const PANELS = {};
// Monotonic counter for nothing security-critical; just a tie-breaker.
let panelSeq = 0;

// CSS custom properties forwarded into the sandbox so a panel can match the app.
const YBE_THEME_VARS = [
  '--bg', '--bg-raised', '--bg-sunken', '--bg-hover', '--bg-bar',
  '--text', '--muted', '--border', '--accent', '--green', '--red',
  '--radius', '--radius-sm',
];
// Minimal reset + variables for the injected wrapper document.
const YBE_PANEL_BASE_CSS = [
  'html,body{margin:0;padding:0}',
  'body{font:13px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;',
  'color:var(--text,#e6e6e6);background:transparent;padding:8px}',
  'button,input,select{font:inherit}',
].join('');

/**
 * Deep-copy a value so callers never receive a live internal reference.
 * @param {*} value
 * @returns {*}
 */
function ybeClone(value) {
  try {
    if (typeof structuredClone === 'function') return structuredClone(value);
  } catch (e) { /* fall through */ }
  try { return JSON.parse(JSON.stringify(value)); } catch (e) { return null; }
}

/**
 * Throw when an extension tries to mutate in read-only mode.
 * @returns {void}
 */
function ybeRequireWritable() {
  if (readonly) throw new Error('read-only mode');
}

/**
 * Validate a submitted box list (numbers clamped to [0,1]).
 * @param {*} raw
 * @returns {Array<Object>}
 */
function ybeNormalizeBoxes(raw) {
  if (!Array.isArray(raw)) throw new Error('boxes must be a list');
  return raw.map((b) => {
    const cls = Math.max(0, Math.floor(Number(b && b.class)) || 0);
    const num = (k) => {
      const n = Number(b && b[k]);
      if (!Number.isFinite(n)) throw new Error('invalid box');
      return Math.min(1, Math.max(0, n));
    };
    return { class: cls, cx: num('cx'), cy: num('cy'), w: num('w'), h: num('h') };
  });
}

/**
 * Validate/normalize a submitted tag list.
 * @param {*} raw
 * @returns {string[]}
 */
function ybeNormalizeStrings(raw) {
  if (!Array.isArray(raw)) throw new Error('tags must be a list');
  const out = [];
  raw.forEach((t) => {
    if (typeof t !== 'string') return;
    const s = t.trim();
    if (s && s.indexOf('\n') < 0 && out.indexOf(s) < 0) out.push(s);
  });
  return out;
}

/**
 * The whitelisted capability table. Every panel request resolves here; anything
 * not listed is rejected. State getters return copies; mutators reuse the real
 * editor functions so undo/dirty/read-only behave as for the built-in UI.
 * @returns {Object<string, Function>}
 */
function ybePanelMethods() {
  return {
    'state.getImage': () => (currentIndex >= 0 && images[currentIndex])
      ? { split: images[currentIndex].split, name: images[currentIndex].name } : null,
    'state.getImageIndex': () => currentIndex,
    'state.getBoxes': () => boxes.map((b) => ({
      class: b.class, cx: b.cx, cy: b.cy, w: b.w, h: b.h, fixed: !!b.fixed,
    })),
    'state.getTags': () => imageTags.slice(),
    'state.getAvailableTags': () => availableTags.slice(),
    'state.getClasses': () => classes.slice(),
    'state.getActiveSplit': () => activeSplit,
    'state.getImageCount': () => images.length,
    'state.isDatasetLoaded': () => !!datasetLoaded,
    'callbacks.addTag': (a) => { ybeRequireWritable(); addTag(String(a[0])); return true; },
    'callbacks.removeTag': (a) => { ybeRequireWritable(); removeTag(String(a[0])); return true; },
    'callbacks.toggleTag': (a) => {
      ybeRequireWritable();
      const name = String(a[0]);
      if (imageTags.indexOf(name) >= 0) removeTag(name); else addTag(name);
      return true;
    },
    'callbacks.setTags': (a) => {
      ybeRequireWritable();
      pushUndo();
      imageTags = ybeNormalizeStrings(a[0]);
      markDirty();
      renderTagBar();
      emitUiEvent('tags_changed', { tags: imageTags.slice() });
      return true;
    },
    'callbacks.setBoxes': (a) => {
      ybeRequireWritable();
      const list = ybeNormalizeBoxes(a[0]);
      pushUndo();
      boxes = list;
      clearBoxSelection();
      justDrawn = false;
      markDirty();
      renderSidePanel();
      draw();
      return true;
    },
    'callbacks.selectBox': (a) => {
      const i = Math.floor(Number(a[0]));
      selectOnlyBox(Number.isFinite(i) && i >= 0 ? i : -1);
      syncClassSelect(selected);
      justDrawn = false;
      draw();
      return true;
    },
    'callbacks.clearSelection': () => {
      clearBoxSelection();
      syncClassSelect(-1);
      justDrawn = false;
      draw();
      return true;
    },
    'callbacks.markDirty': () => { markDirty(); return true; },
    'callbacks.draw': () => { draw(); return true; },
    'callbacks.save': async () => { ybeRequireWritable(); return await save(); },
    'callbacks.runAction': async (a) => {
      const opts = (a[1] && typeof a[1] === 'object') ? a[1] : {};
      return await runAction(String(a[0]), opts);
    },
    'callbacks.refreshImage': async (a) => {
      const map = {
        pixels: 'app_refresh_image', labels: 'app_refresh_image_labels',
        tags: 'app_refresh_image_tags', all: 'app_refresh_image_all',
      };
      return await runAppAction(map[String(a[0])] || map.all, { preventDefault() {} });
    },
    'callbacks.toast': (a) => {
      toast(String(a[0]), (a[1] && typeof a[1] === 'object') ? a[1] : {});
      return true;
    },
    'callbacks.setStatus': (a) => { toast(String(a[0]), { type: 'info' }); return true; },
    'callbacks.openSettings': (a) => {
      openSettingsModal();
      if (a[0]) selectSettingsTab(String(a[0]));
      return true;
    },
    'callbacks.getSetting': (a) => {
      const v = settingsGet(String(a[0]));
      return v === null ? null : v;
    },
    'callbacks.setSetting': (a) => {
      const v = a[1];
      settingsSet(String(a[0]), (v === null || v === undefined) ? null : String(v));
      return true;
    },
  };
}

/**
 * Resolve one YBE request; rejects unknown methods and invalid arguments.
 * @param {string} method
 * @param {Array<*>} args
 * @returns {Promise<*>}
 */
async function ybeHandleRequest(method, args) {
  if (typeof method !== 'string') throw new Error('invalid YBE method');
  const table = ybePanelMethods();
  const fn = Object.prototype.hasOwnProperty.call(table, method) ? table[method] : null;
  if (!fn) throw new Error('unknown YBE method: ' + method);
  return await fn(Array.isArray(args) ? args : []);
}

/**
 * Build the `:root{...}` theme variables from the host's computed style.
 * @returns {string}
 */
function buildYbeThemeCss() {
  try {
    const cs = getComputedStyle(document.documentElement);
    const parts = [];
    YBE_THEME_VARS.forEach((v) => {
      const value = cs.getPropertyValue(v).trim();
      if (value) parts.push(v + ':' + value);
    });
    return ':root{' + parts.join(';') + '}';
  } catch (e) {
    return '';
  }
}

/**
 * A random nonce for the wrapper's inline scripts.
 * @returns {string}
 */
function ybeRandomNonce() {
  const arr = new Uint8Array(16);
  if (window.crypto && window.crypto.getRandomValues) window.crypto.getRandomValues(arr);
  else for (let i = 0; i < arr.length; i++) arr[i] = Math.floor(Math.random() * 256);
  return Array.prototype.map.call(arr, (b) => ('0' + b.toString(16)).slice(-2)).join('');
}

/**
 * Neutralize a `</script>` sequence inside inlined source.
 * @param {string} src
 * @returns {string}
 */
function escapeScriptClose(src) {
  return String(src || '').replace(/<\/script/gi, '<\\/script');
}

/**
 * Build the sandboxed wrapper document: strict CSP, the YBE stub and the
 * extension source, all inlined with a shared nonce.
 * @param {string} scriptText - The extension's panel script source.
 * @returns {string}
 */
function buildPanelSrcdoc(scriptText) {
  const nonce = ybeRandomNonce();
  const csp = "default-src 'none'; script-src 'nonce-" + nonce + "'; "
    + "style-src 'unsafe-inline'; connect-src 'none'; img-src 'none'; "
    + "form-action 'none'; base-uri 'none'";
  const stub = escapeScriptClose('(' + __ybeIframeStub.toString() + ')();');
  return '<!doctype html><html><head><meta charset="utf-8">'
    + '<meta http-equiv="Content-Security-Policy" content="' + csp + '">'
    + '<style>' + YBE_PANEL_BASE_CSS + '</style></head><body>'
    + '<script nonce="' + nonce + '">window.__YBE_API_VERSION=' + Number(pluginApiVersion || 1) + ';</script>'
    + '<script nonce="' + nonce + '">' + stub + '</script>'
    + '<script nonce="' + nonce + '">' + escapeScriptClose(scriptText) + '</script>'
    + '</body></html>';
}

/**
 * Post a message into a panel's sandbox (no-op when it is gone).
 * @param {string} name - Panel widget name.
 * @param {Object} msg - Message body (a `__ybe:true` envelope is added).
 * @returns {void}
 */
function panelPost(name, msg) {
  const panel = PANELS[name];
  if (!panel) return;
  const target = panel.target || (panel.iframe && panel.iframe.contentWindow);
  if (!target || typeof target.postMessage !== 'function') return;
  try {
    target.postMessage(Object.assign({ __ybe: true }, msg), '*');
  } catch (e) {
    dbgWarn('panel postMessage failed', e);
  }
}

/**
 * Handle one message coming out of a panel sandbox.
 * @param {string} name - Panel widget name.
 * @param {*} data - The message data.
 * @returns {void}
 */
function handlePanelMessage(name, data) {
  if (!PANELS[name] || !data || data.__ybe !== true) return;
  if (data.kind === 'req') {
    Promise.resolve()
      .then(() => ybeHandleRequest(data.method, data.args))
      .then((value) => panelPost(name, {
        kind: 'res', id: data.id, ok: true, value: value === undefined ? null : value,
      }))
      .catch((err) => panelPost(name, {
        kind: 'res', id: data.id, ok: false,
        error: String((err && err.message) || err),
      }));
  } else if (data.kind === 'resize') {
    const panel = PANELS[name];
    const h = Math.max(40, Math.min(2000, Math.floor(Number(data.height) || 0)));
    if (panel && panel.iframe) panel.iframe.style.height = h + 'px';
  }
}

/**
 * Forward an editor event to every mounted panel.
 * @param {string} name - Event name.
 * @param {Object} [payload] - Event payload.
 * @returns {void}
 */
function emitUiEvent(name, payload) {
  const keys = Object.keys(PANELS);
  for (let i = 0; i < keys.length; i++) {
    panelPost(keys[i], { kind: 'evt', event: name, payload: payload || {} });
  }
}

/**
 * Tell panels the read-only flag changed.
 * @returns {void}
 */
function emitReadonlyChange() {
  const keys = Object.keys(PANELS);
  for (let i = 0; i < keys.length; i++) {
    panelPost(keys[i], { kind: 'readonly', value: !!readonly });
  }
  emitUiEvent('readonly_changed', { readonly: !!readonly });
}

/**
 * Mount one extension package's sandboxed UI panel.
 * @param {Object} pkg - The package definition from /api/config.
 * @param {string} scriptText - The panel script source.
 * @returns {Object|null} The panel entry.
 */
function mountExtensionPanel(pkg, scriptText) {
  const name = 'panel.' + pkg.id;
  if (PANELS[name]) return PANELS[name];
  const ui = pkg.ui || {};
  const title = ui.title || pkg.name;
  const frame = createWidgetFrame(name, title);
  const iframe = mk('iframe', 'panel-iframe');
  iframe.setAttribute('sandbox', 'allow-scripts');
  iframe.setAttribute('title', title);
  if (ui.height) iframe.style.height = Math.max(40, Math.floor(ui.height)) + 'px';
  try {
    iframe.srcdoc = buildPanelSrcdoc(scriptText);
  } catch (e) {
    dbgWarn('panel srcdoc failed', e);
  }
  frame.body.appendChild(iframe);

  const panel = { packageId: pkg.id, name, iframe, target: null, listener: null };
  PANELS[name] = panel;
  panel.listener = (ev) => {
    if (panel.target && ev.source !== panel.target) return;
    handlePanelMessage(name, ev.data);
  };
  window.addEventListener('message', panel.listener);

  const controls = buildWidgetSetting({ name, title }, el('customWidgetSettings') || document.body);
  registerWidget(name, {
    frame: frame.frame, body: frame.body, content: iframe,
    select: controls.select.id, visibleSw: controls.checkbox.id,
    defaultDock: ui.location || 'float',
  });
  panel.target = iframe.contentWindow || null;

  const prime = () => {
    panel.target = iframe.contentWindow || panel.target;
    panelPost(name, { kind: 'theme', css: buildYbeThemeCss() });
    panelPost(name, { kind: 'readonly', value: !!readonly });
  };
  iframe.addEventListener('load', prime);
  setTimeout(prime, 0);

  controls.select.value = getDock(name);
  controls.select.addEventListener('change', () => setWidgetDock(name, controls.select.value));
  controls.checkbox.checked = getWidgetVisible(name);
  controls.checkbox.addEventListener('change', () => setWidgetVisible(name, controls.checkbox.checked));
  frame.hide.addEventListener('click', () => setWidgetVisible(name, false));
  panelSeq += 1;
  return panel;
}

/**
 * Tear down a mounted panel.
 * @param {string} name - Panel widget name.
 * @returns {void}
 */
function unmountExtensionPanel(name) {
  const panel = PANELS[name];
  if (!panel) return;
  window.removeEventListener('message', panel.listener);
  delete PANELS[name];
  unregisterWidget(name);
}

/**
 * The YBE stub injected into every panel document. Kept as a named function so
 * its source can be inlined via `.toString()`; it must not reference anything
 * from this module's scope.
 */
function __ybeIframeStub() {
  'use strict';
  var pending = {};
  var seq = 0;
  var handlers = {};
  var TIMEOUT = 20000;

  function call(method, args) {
    return new Promise(function (resolve, reject) {
      var id = ++seq;
      pending[id] = { resolve: resolve, reject: reject };
      parent.postMessage({ __ybe: true, kind: 'req', id: id, method: method, args: args || [] }, '*');
      setTimeout(function () {
        if (pending[id]) { delete pending[id]; reject(new Error('YBE timeout: ' + method)); }
      }, TIMEOUT);
    });
  }
  function on(name, handler) {
    (handlers[name] = handlers[name] || []).push(handler);
    return function () { off(name, handler); };
  }
  function off(name, handler) {
    var list = handlers[name];
    if (!list) return;
    var i = list.indexOf(handler);
    if (i >= 0) list.splice(i, 1);
  }
  function dispatch(name, payload) {
    var list = (handlers[name] || []).concat(handlers['*'] || []);
    list.forEach(function (h) {
      try { h(payload); } catch (err) { if (window.console) console.error('[ybe panel]', err); }
    });
  }
  function applyTheme(css) {
    var style = document.getElementById('__ybe_theme');
    if (!style) {
      style = document.createElement('style');
      style.id = '__ybe_theme';
      document.head.appendChild(style);
    }
    style.textContent = css || '';
  }
  window.addEventListener('message', function (ev) {
    if (ev.source !== parent) return;
    var d = ev.data;
    if (!d || d.__ybe !== true) return;
    if (d.kind === 'res') {
      var p = pending[d.id];
      if (!p) return;
      delete pending[d.id];
      if (d.ok) p.resolve(d.value);
      else p.reject(new Error(d.error || 'YBE error'));
    } else if (d.kind === 'evt') {
      dispatch(d.event, d.payload);
    } else if (d.kind === 'theme') {
      applyTheme(d.css);
    } else if (d.kind === 'readonly') {
      YBE.readonly = !!d.value;
    }
  });

  var YBE = {
    apiVersion: window.__YBE_API_VERSION || 0,
    readonly: false,
    on: on,
    off: off,
    state: {
      getImage: function () { return call('state.getImage'); },
      getImageIndex: function () { return call('state.getImageIndex'); },
      getBoxes: function () { return call('state.getBoxes'); },
      getTags: function () { return call('state.getTags'); },
      getAvailableTags: function () { return call('state.getAvailableTags'); },
      getClasses: function () { return call('state.getClasses'); },
      getActiveSplit: function () { return call('state.getActiveSplit'); },
      getImageCount: function () { return call('state.getImageCount'); },
      isDatasetLoaded: function () { return call('state.isDatasetLoaded'); },
    },
    callbacks: {
      addTag: function (n) { return call('callbacks.addTag', [n]); },
      removeTag: function (n) { return call('callbacks.removeTag', [n]); },
      toggleTag: function (n) { return call('callbacks.toggleTag', [n]); },
      setTags: function (l) { return call('callbacks.setTags', [l]); },
      setBoxes: function (l) { return call('callbacks.setBoxes', [l]); },
      selectBox: function (i) { return call('callbacks.selectBox', [i]); },
      clearSelection: function () { return call('callbacks.clearSelection'); },
      markDirty: function () { return call('callbacks.markDirty'); },
      draw: function () { return call('callbacks.draw'); },
      save: function () { return call('callbacks.save'); },
      runAction: function (n, o) { return call('callbacks.runAction', [n, o]); },
      refreshImage: function (k) { return call('callbacks.refreshImage', [k]); },
      toast: function (m, o) { return call('callbacks.toast', [m, o]); },
      setStatus: function (m) { return call('callbacks.setStatus', [m]); },
      openSettings: function (t) { return call('callbacks.openSettings', [t]); },
      getSetting: function (k) { return call('callbacks.getSetting', [k]); },
      setSetting: function (k, v) { return call('callbacks.setSetting', [k, v]); },
    },
  };
  window.YBE = YBE;

  function reportSize() {
    var h = document.documentElement ? document.documentElement.scrollHeight : 0;
    parent.postMessage({ __ybe: true, kind: 'resize', height: h }, '*');
  }
  if (window.ResizeObserver) {
    try { new window.ResizeObserver(reportSize).observe(document.documentElement); } catch (e) { /* ignore */ }
  }
  window.addEventListener('load', reportSize);
  setTimeout(reportSize, 0);
}
