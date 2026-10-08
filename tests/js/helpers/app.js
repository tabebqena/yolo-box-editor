'use strict';

// Test harness for app/static/app.js.
//
// The frontend is a single classic script that expects a full DOM, so the
// suite loads app/templates/index.html into jsdom, installs the browser APIs
// jsdom lacks (canvas 2D, fetch, rAF, ...), then runs app.js in the window's
// own vm context. Running it as a script (not eval) puts its top-level
// `function` declarations on `window` and its `let`/`const` state in the global
// lexical scope, which the injected `window.__ybe` bridge exposes to tests.

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '..', '..', '..');
const INDEX_HTML = path.join(ROOT, 'app', 'templates', 'index.html');
const APP_JS = path.join(ROOT, 'app', 'static', 'app.js');

// Load order must match app/templates/index.html: the classic-script modules
// share one global lexical environment, then app.js (the entry point) runs.
const MODULE_FILES = [
  'core.js', 'api.js', 'canvas.js', 'navigation.js', 'extensions.js', 'shortcuts.js',
  'images.js', 'editing.js', 'appearance.js', 'help.js', 'events.js',
].map((f) => path.join(ROOT, 'app', 'static', 'js', f));

// Top-level `let` declarations in app.js that tests may need to set directly.
// (`const` objects such as dockState are mutated through the returned
// reference instead, because reassigning a const would throw.)
const LET_STATE = [
  'images', 'splits', 'filters', 'classes', 'currentIndex', 'activeSplit',
  'activeFilters', 'boxes', 'selected', 'lastSelected', 'defaultClass',
  'justDrawn', 'editingPoint', 'appShortcuts', 'actionShortcuts',
  'shortcutErrors', 'shortcutDefaults', 'userShortcutNames', 'shortcutEditMode',
  'shortcutDraft', 'shortcutResets', 'hookErrors', 'filterErrors', 'appActions',
  'backendActions', 'hookEvents', 'extensionApiVersion', 'placeholders',
  'actionDefs', 'hookDefs', 'filterDefs', 'yamlEditor', 'undoStack', 'redoStack',
  'moved', 'dragUndoPushed', 'imgW', 'imgH', 'dirty', 'readonly',
  'datasetLoaded', 'availableTags', 'imageTags', 'boxesVisible',
  'boxDetailsVisible', 'isolateSelected',
  'currentDataYaml', 'hooksByName', 'hookInFlight', 'autoSave', 'autoSaveTimer',
  'debugMode', 'updateInfo', 'serverSettings', 'settingsSaveTimer',
  'pendingSettings', 'notifLog', 'notifUnread', 'autoModalCurrent', 'mode',
  'start', 'dragStart', 'mouse', 'origBox', 'handle', 'loadDataAutoOpened',
  'tipChecked', 'actionsExpanded', 'shownShortcutErrors', 'presenceTimer',
  'presenceDismissed', 'presenceToast', 'shortcutCapture', 'sidePanelOpen',
  'panelSide', 'settingsInitialized', 'appStarted',
];

const CONST_NAMES = [
  'ESCAPE_CLOSERS', 'WIDGETS', 'APP_SHORTCUT_ORDER', 'APP_SHORTCUT_HANDLERS',
  'APP_SHORTCUT_ORDER', 'EXT_TYPE_LABELS', 'SHORTCUT_MODIFIERS',
  'DOCK_LOCATIONS', 'TOAST_MAX', 'NOTIF_LOG_MAX', 'FILTER_CHAIN_MAX',
  'LAST_IMAGE_KEY', 'VIEW_KEY', 'SHOW_BOXES_KEY', 'CLIENT_ID',
  'SHOW_BOX_DETAILS_KEY', 'ISOLATE_BOX_KEY',
];

function bridgeSource() {
  const setters = LET_STATE
    .map((name) => `      if ('${name}' in patch) ${name} = patch['${name}'];`)
    .join('\n');
  const stateKeys = LET_STATE.map((name) => `      ${name},`).join('\n');
  const constKeys = CONST_NAMES.map((name) => `      ${name},`).join('\n');
  // Function declarations in the app script are properties of the window, so
  // the window doubles as the callable API (`app.api.toast(...)`).
  return `
window.__ybe = (function () {
  return {
    state: () => ({
${stateKeys}
    }),
    set: (patch) => {
${setters}
    },
    // Function declarations live on the window; the few lexical const arrow
    // helpers (el, qs, qsa) are added explicitly.
    api: new Proxy({ el, qs, qsa }, {
      get(target, prop) {
        if (typeof prop === 'symbol' || prop in target) return target[prop];
        const value = window[prop];
        return typeof value === 'function' ? value.bind(window) : value;
      },
    }),
    consts: {
${constKeys}
    },
    imageEl: () => imageEl,
    canvasEl: () => canvas,
    context: () => ctx,
  };
})();
`;
}

// A 2D canvas context that accepts every call without doing anything. The one
// method whose return value app.js actually reads is measureText().
function makeContext() {
  const props = {};
  const calls = [];
  const target = {
    calls,
    measureText: (text) => ({ width: String(text).length * 7 }),
  };
  return new Proxy(target, {
    get(obj, prop) {
      if (typeof prop === 'symbol') return obj[prop];
      if (prop in obj) return obj[prop];
      if (prop in props) return props[prop];
      const fn = (...args) => { calls.push([String(prop), args]); };
      return fn;
    },
    set(obj, prop, value) {
      if (typeof prop === 'symbol') { obj[prop] = value; return true; }
      props[prop] = value;
      return true;
    },
  });
}

function makeResponse(spec = {}) {
  const status = spec.status != null ? spec.status : (spec.ok === false ? 400 : 200);
  const ok = spec.ok != null ? spec.ok : status >= 200 && status < 300;
  const body = spec.body !== undefined ? spec.body : {};
  return {
    ok,
    status,
    json: async () => body,
    text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
    headers: { get: () => null },
  };
}

// A tiny URL-routed fetch stub. Tests register routes with `fetchMock.on(...)`;
// unmatched requests return an empty 200 so unrelated calls stay harmless.
function makeFetch() {
  const routes = [];
  const history = [];
  async function fetchImpl(url, init = {}) {
    const u = typeof url === 'string' ? url : (url && url.url) || '';
    const method = String((init && init.method) || 'GET').toUpperCase();
    const entry = { url: u, method, body: init && init.body, init };
    history.push(entry);
    for (const route of routes) {
      if (route.match(u, method, entry)) {
        const spec = await route.handler(u, method, entry);
        return makeResponse(spec);
      }
    }
    return makeResponse({ body: {} });
  }
  fetchImpl.on = (match, handler) => {
    routes.push({ match: typeof match === 'string' ? (u) => u === match : match, handler });
    return fetchImpl;
  };
  fetchImpl.onPrefix = (prefix, handler) => {
    routes.push({ match: (u) => u.startsWith(prefix), handler });
    return fetchImpl;
  };
  fetchImpl.history = history;
  fetchImpl.reset = () => { routes.length = 0; history.length = 0; };
  return fetchImpl;
}

function loadHtml() {
  let html = fs.readFileSync(INDEX_HTML, 'utf8');
  // Drop the Jinja-templated stylesheet/script tags; we inject them ourselves.
  html = html.replace(/<link\b[^>]*>/gi, '');
  html = html.replace(/<script\b[\s\S]*?<\/script>/gi, '');
  return html;
}

function loadAppSource() {
  const parts = MODULE_FILES.map((f) => fs.readFileSync(f, 'utf8'));
  parts.push(fs.readFileSync(APP_JS, 'utf8'));
  const src = parts.join('\n');
  // Remove the trailing `boot();` so tests decide when startup runs.
  return src.replace(/\nboot\(\);\s*$/, '\n');
}

/**
 * Build a fresh app instance. Returns the jsdom window plus test helpers.
 * Call `app.cleanup()` when done (Node's test runner usually needs it to avoid
 * leaked timers/handles).
 */
function createApp(options = {}) {
  const { html = loadHtml() } = options;
  const dom = new JSDOM(html, {
    runScripts: 'outside-only',
    url: 'http://localhost/',
    pretendToBeVisual: true,
  });
  const { window } = dom;
  const { document } = window;

  // --- browser APIs jsdom does not provide (or provides differently) -------- //
  const context2d = makeContext();
  window.HTMLCanvasElement.prototype.getContext = function getContext() {
    return context2d;
  };
  window.requestAnimationFrame = (cb) => { if (typeof cb === 'function') cb(0); return 0; };
  window.cancelAnimationFrame = () => {};
  window.confirm = () => true;
  window.alert = () => {};
  if (!window.navigator.sendBeacon) window.navigator.sendBeacon = () => true;
  if (!window.crypto || !window.crypto.randomUUID) {
    const cryptoObj = window.crypto || {};
    cryptoObj.randomUUID = () => '00000000-0000-4000-8000-000000000000';
    try { Object.defineProperty(window, 'crypto', { value: cryptoObj, configurable: true }); } catch (e) { /* ignore */ }
  }

  const fetchMock = makeFetch();
  window.fetch = fetchMock;

  // --- run app.js in the window's vm context -------------------------------- //
  const context = dom.getInternalVMContext();
  vm.runInContext(loadAppSource(), context, { filename: 'app.js' });
  vm.runInContext(bridgeSource(), context, { filename: 'bridge.js' });

  const bridge = window.__ybe;

  function node(target) {
    return typeof target === 'string' ? document.getElementById(target) : target;
  }
  function click(target, init) {
    const el = node(target);
    if (!el) throw new Error(`click: no element ${target}`);
    el.dispatchEvent(new window.MouseEvent('click', Object.assign({ bubbles: true, cancelable: true }, init)));
    return el;
  }
  function change(target, value) {
    const el = node(target);
    if (value !== undefined) el.value = value;
    el.dispatchEvent(new window.Event('change', { bubbles: true }));
    return el;
  }
  function input(target, value) {
    const el = node(target);
    if (value !== undefined) el.value = value;
    el.dispatchEvent(new window.Event('input', { bubbles: true }));
    return el;
  }
  function keydown(target, init) {
    const el = node(target) || document;
    el.dispatchEvent(new window.KeyboardEvent('keydown', Object.assign({ bubbles: true, cancelable: true }, init)));
    return el;
  }
  function keyup(target, init) {
    const el = node(target) || document;
    el.dispatchEvent(new window.KeyboardEvent('keyup', Object.assign({ bubbles: true, cancelable: true }, init)));
    return el;
  }

  // Let queued microtasks (fetch callbacks, promises) settle.
  async function flush(times = 4) {
    for (let i = 0; i < times; i++) {
      await Promise.resolve();
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
  }

  return {
    dom,
    window,
    document,
    fetchMock,
    bridge,
    context2d,
    get api() { return bridge.api; },
    get consts() { return bridge.consts; },
    state: () => bridge.state(),
    set: (patch) => bridge.set(patch),
    imageEl: () => bridge.imageEl(),
    node,
    $(id) { return document.getElementById(id); },
    click,
    change,
    input,
    keydown,
    keyup,
    flush,
    cleanup() { try { dom.window.close(); } catch (e) { /* ignore */ } },
  };
}

// Normalise a value created inside the jsdom vm realm into host-realm plain
// data, so `assert.deepStrictEqual` can compare it to object literals.
function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

module.exports = { createApp, makeResponse, plain, ROOT };
