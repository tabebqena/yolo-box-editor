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

// Extension app actions are named `ext.<extension_id>.<action>` in steps and
// events (must match EXTENSION_ACTION_PREFIX in ybe/config.py). The lifecycle
// bus below caps how many times an event may recursively trigger another action.
const EXT_ACTION_PREFIX = 'ext.';
const MAX_EVENT_DEPTH = 8;
// Monotonic id so one action chain's events share a label.
let actionChainSeq = 0;

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
 * The whitelisted capability table. Every panel request resolves here; anything
 * not listed is rejected. State getters return copies; mutators reuse the real
 * editor functions so undo/dirty/read-only behave as for the built-in UI.
 * @returns {Object<string, Function>}
 */
function ybePanelMethods(panel) {
  const packageId = (panel && panel.packageId) || '';
  return {
    'state.getImage': () => (currentIndex >= 0 && images[currentIndex])
      ? { split: images[currentIndex].split, name: images[currentIndex].name } : null,
    'state.getImageIndex': () => currentIndex,
    'state.getBoxes': () => boxes.map((b) => ({
      class: b.class, cx: b.cx, cy: b.cy, w: b.w, h: b.h, fixed: !!b.fixed,
    })),
    'state.getClasses': () => classes.slice(),
    'state.getActiveSplit': () => activeSplit,
    'state.getImageCount': () => images.length,
    'state.isDatasetLoaded': () => !!datasetLoaded,
    // Read-only copy of the app's `/api/config` payload.
    'state.getConfig': async () => await apiGet('/api/config'),
    // Proxy a same-origin `/api/*` request through the host (the sandbox has no
    // network of its own). Auth routes are off-limits.
    'api.request': async (a) => await ybeApiRequest(a[0], a[1], a[2]),
    // Package backend capabilities (only the caller's own package is reachable).
    'call': (a) => capabilityCall(packageId, String(a[0]), Array.isArray(a[1]) ? a[1] : []),
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
    'callbacks.runAction': async (a, ctx) => {
      const name = String(a[0]);
      const opts = (a[1] && typeof a[1] === 'object') ? a[1] : {};
      if (name.startsWith('app_') || name.startsWith(EXT_ACTION_PREFIX)) {
        const ev = { preventDefault() {} };
        return await invokeAppAction(name, ev, () => runCoreAppAction(name, ev), ctx);
      }
      return await runAction(name, opts);
    },
    'callbacks.refreshImage': async (a) => {
      const map = {
        pixels: 'app_refresh_image', labels: 'app_refresh_image_labels',
        all: 'app_refresh_image_all',
      };
      const name = map[String(a[0])];
      if (!name) return null;
      return await runAppAction(name, { preventDefault() {} });
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
async function ybeHandleRequest(method, args, ctx, panel) {
  if (typeof method !== 'string') throw new Error('invalid YBE method');
  ybeCheckPermission(panel, method);
  const table = ybePanelMethods(panel);
  const fn = Object.prototype.hasOwnProperty.call(table, method) ? table[method] : null;
  if (!fn) throw new Error('unknown YBE method: ' + method);
  return await fn(Array.isArray(args) ? args : [], ctx);
}

/**
 * Enforce a package's declared permission for a YBE method. A package that ships
 * a permissions.yaml may only call methods whose permission it declares; a
 * package without a file is allowed (the UI flags it instead).
 * @param {{packageId?:string}} panel
 * @param {string} method
 * @throws {Error} when the permission is not declared.
 */
function ybeCheckPermission(panel, method) {
  const packageId = (panel && panel.packageId) || '';
  const pkg = (extensionPackages || []).find((p) => p.id === packageId);
  if (!pkg || !pkg.permissions) return;
  const need = pluginPermissionMap[method];
  if (!need) return;
  if ((pkg.permissions.ybe || []).indexOf(need) < 0) {
    throw new Error(
      `permission denied: "${method}" needs "${need}" in permissions.yaml`);
  }
}

/**
 * Split a fully-qualified extension app-action id (`ext.<ext>.<name>`).
 * @param {string} id
 * @returns {{extension:string, name:string}|null}
 */
function actionExtId(id) {
  if (typeof id !== 'string' || !id.startsWith(EXT_ACTION_PREFIX)) return null;
  const rest = id.slice(EXT_ACTION_PREFIX.length);
  const dot = rest.indexOf('.');
  if (dot <= 0) return null;
  return { extension: rest.slice(0, dot), name: rest.slice(dot + 1) };
}

/**
 * The current image's `split/name` key, or null.
 * @returns {string|null}
 */
function currentImageKey() {
  return (currentIndex >= 0 && images[currentIndex])
    ? images[currentIndex].split + '/' + images[currentIndex].name : null;
}

/**
 * Call one of a package's backend capabilities through the host.
 * @param {string} packageId
 * @param {string} method
 * @param {Array<*>} args
 * @returns {Promise<*>}
 */
async function capabilityCall(packageId, method, args) {
  const { res, data } = await apiPost('/api/extensions/call',
    { package: packageId, method, args: args || [] });
  if (!res.ok || data.ok === false) {
    throw new Error((data && data.error) || ('capability failed: ' + method));
  }
  return data.value;
}

// Auth/session routes a panel may never touch (so it cannot log in/out or read
// the signed session).
const YBE_API_BLOCKED = ['/api/login', '/api/logout', '/api/session', '/api/password'];

/**
 * Proxy a same-origin API request for a panel. Only `/api/*` paths are allowed,
 * auth routes are refused, and only GET/POST are supported. The host performs
 * the fetch, so the sandbox never gets network access itself.
 * @param {string} method
 * @param {string} path
 * @param {*} [body] - JSON body for POST.
 * @returns {Promise<*>} The parsed response body.
 */
async function ybeApiRequest(method, path, body) {
  const m = String(method || 'GET').toUpperCase();
  const p = String(path || '');
  if (m !== 'GET' && m !== 'POST') throw new Error('only GET and POST are allowed');
  if (!p.startsWith('/api/')) throw new Error('only /api/ paths are allowed');
  if (YBE_API_BLOCKED.some((b) => p === b || p.startsWith(b + '?') || p.startsWith(b + '/'))) {
    throw new Error('auth routes are not available to panels');
  }
  if (m === 'GET') return await apiGet(p);
  return (await apiPost(p, body === undefined ? {} : body)).data;
}

/**
 * Run one extension app action. If the owning panel is mounted it receives an
 * `app_action` event; otherwise the action's declared backend capability is
 * called with the current image key (headless fallback for steps).
 * @param {string} extension
 * @param {string} name
 * @param {{depth?:number, chain?:string}} ctx
 * @returns {Promise<*>}
 */
async function callExtensionAction(extension, name, ctx) {
  const panelName = 'panel.' + extension;
  const payload = {
    action: EXT_ACTION_PREFIX + extension + '.' + name,
    extension, name,
    depth: ctx ? ctx.depth : 0, chain: ctx ? ctx.chain : null,
  };
  if (PANELS[panelName]) {
    panelPost(panelName, { kind: 'evt', event: 'app_action', payload });
    return null;
  }
  const pkg = (extensionPackages || []).find((p) => p.id === extension);
  const declared = pkg && (pkg.app_actions || []).find((a) => a.name === name);
  if (!declared || !declared.capability) {
    throw new Error('extension action not available: ' + extension + '.' + name);
  }
  const key = currentImageKey();
  return await capabilityCall(extension, declared.capability, key ? [key] : []);
}

/**
 * Run an app action through the lifecycle bus: broadcast `before_app_action`,
 * run it, then broadcast `after_app_action` to every panel. `ctx` carries the
 * recursion chain when the action was triggered from a panel handling an event;
 * exceeding MAX_EVENT_DEPTH refuses the action.
 * @param {string} name
 * @param {Event} e
 * @param {Function} coreRunner
 * @param {{depth?:number, chain?:string}} [ctx]
 * @returns {Promise<*>}
 */
async function invokeAppAction(name, e, coreRunner, ctx) {
  const depth = ctx ? (Number(ctx.depth) || 0) + 1 : 0;
  const chain = (ctx && ctx.chain) ? ctx.chain : ('c' + (++actionChainSeq));
  if (depth > MAX_EVENT_DEPTH) {
    const err = new Error('app action event chain exceeded ' + MAX_EVENT_DEPTH + ' levels');
    toast(err.message, { type: 'error' });
    throw err;
  }
  const ext = actionExtId(name);
  const info = {
    action: name,
    extension: ext ? ext.extension : null,
    name: ext ? ext.name : name,
    source: ctx ? 'event' : 'ui',
    depth, chain,
  };
  emitUiEvent('before_app_action', info);
  try {
    const out = ext
      ? await callExtensionAction(ext.extension, ext.name, { depth, chain })
      : (typeof coreRunner === 'function' ? await coreRunner() : null);
    emitUiEvent('after_app_action', Object.assign({ ok: true, error: null }, info));
    return out;
  } catch (err) {
    emitUiEvent('after_app_action', Object.assign(
      { ok: false, error: String((err && err.message) || err) }, info));
    throw err;
  }
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
      .then(() => ybeHandleRequest(data.method, data.args, data.ctx, PANELS[name]))
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
  // The chain context of the most recent lifecycle event. Attached to every
  // outgoing action call so the host can bound event-triggered recursion.
  var lastCtx = null;
  var ctxTimer = null;

  function rememberCtx(payload) {
    if (!payload) return;
    lastCtx = { chain: payload.chain || null, depth: Number(payload.depth) || 0 };
    if (ctxTimer) clearTimeout(ctxTimer);
    ctxTimer = setTimeout(function () { lastCtx = null; }, 1000);
  }

  function call(method, args, ctx) {
    return new Promise(function (resolve, reject) {
      var id = ++seq;
      pending[id] = { resolve: resolve, reject: reject };
      parent.postMessage({ __ybe: true, kind: 'req', id: id, method: method,
        args: args || [], ctx: ctx || null }, '*');
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
      if (d.event === 'after_app_action') rememberCtx(d.payload);
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
    call: function (method, args) { return call('call', [method, args], lastCtx); },
    api: {
      request: function (method, path, body) { return call('api.request', [method, path, body]); },
      get: function (path) { return call('api.request', ['GET', path]); },
      post: function (path, body) { return call('api.request', ['POST', path, body]); },
    },
    state: {
      getImage: function () { return call('state.getImage'); },
      getImageIndex: function () { return call('state.getImageIndex'); },
      getBoxes: function () { return call('state.getBoxes'); },
      getClasses: function () { return call('state.getClasses'); },
      getActiveSplit: function () { return call('state.getActiveSplit'); },
      getImageCount: function () { return call('state.getImageCount'); },
      isDatasetLoaded: function () { return call('state.isDatasetLoaded'); },
      getConfig: function () { return call('state.getConfig'); },
    },
    callbacks: {
      setBoxes: function (l) { return call('callbacks.setBoxes', [l]); },
      selectBox: function (i) { return call('callbacks.selectBox', [i]); },
      clearSelection: function () { return call('callbacks.clearSelection'); },
      markDirty: function () { return call('callbacks.markDirty'); },
      draw: function () { return call('callbacks.draw'); },
      save: function () { return call('callbacks.save'); },
      runAction: function (n, o) { return call('callbacks.runAction', [n, o], lastCtx); },
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
