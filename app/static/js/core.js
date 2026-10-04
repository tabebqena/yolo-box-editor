// app/static/js/core.js — DOM helpers, modals, settings, notifications, update/changelog
'use strict';

const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');

/**
 * Look up a single element by id.
 * @param {string} id
 * @returns {HTMLElement|null}
 */
const el = (id) => document.getElementById(id);
/**
 * Query the first element matching a CSS selector.
 * @param {string} sel
 * @param {ParentNode} [root=document]
 * @returns {Element|null}
 */
const qs = (sel, root = document) => root.querySelector(sel);
/**
 * Query all matching elements as an array.
 * @param {string} sel
 * @param {ParentNode} [root=document]
 * @returns {Element[]}
 */
const qsa = (sel, root = document) => Array.from(root.querySelectorAll(sel));

// ------------------------------------------------------------------------- //
// reusable DOM helpers (used everywhere; keep them small and side-effect free)
// ------------------------------------------------------------------------- //

/**
 * Build an element in one call: `mk('button', 'primary', 'Save')`.
 * @param {string} tag - Tag name.
 * @param {string} [cls] - Class attribute.
 * @param {string} [text] - textContent.
 * @returns {HTMLElement}
 */
function mk(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

/**
 * Build an <option>; `text` defaults to the value when omitted.
 * @param {string} value
 * @param {string} [text]
 * @returns {HTMLOptionElement}
 */
function option(value, text) {
  const o = document.createElement('option');
  o.value = value;
  if (text !== undefined) o.textContent = text;
  return o;
}

/**
 * Toggle the shared `hidden` class on a node or element id.
 * @param {string|HTMLElement} node
 * @param {boolean} hidden
 */
function setHidden(node, hidden) {
  const n = typeof node === 'string' ? el(node) : node;
  if (n) n.classList.toggle('hidden', !!hidden);
}
/**
 * Show the element with the given id.
 * @param {string} id
 */
function showEl(id) { setHidden(id, false); }
/**
 * Hide the element with the given id.
 * @param {string} id
 */
function hideEl(id) { setHidden(id, true); }
/**
 * Whether the element with the given id is missing or hidden.
 * @param {string} id
 * @returns {boolean}
 */
function isHidden(id) { const n = el(id); return !n || n.classList.contains('hidden'); }

/**
 * addEventListener by id or node, ignoring missing elements.
 * @param {string|HTMLElement} id
 * @param {string} event
 * @param {EventListener} handler
 * @param {(boolean|AddEventListenerOptions)} [opts]
 * @returns {HTMLElement|null}
 */
function onEl(id, event, handler, opts) {
  const n = typeof id === 'string' ? el(id) : id;
  if (n) n.addEventListener(event, handler, opts);
  return n;
}

// ------------------------------------------------------------------------- //
// modals: one open/close/backdrop implementation for every overlay
// ------------------------------------------------------------------------- //
/**
 * Open (show) a modal by id.
 * @param {string} id
 */
function openModal(id) { showEl(id); }
/**
 * Close (hide) a modal by id.
 * @param {string} id
 */
function closeModal(id) { hideEl(id); }

/**
 * Close the modal when its dimmed backdrop (the wrapper itself, outside the
 * inner box) is clicked.
 * @param {string} id - Wrapper element id.
 * @param {Function} close - Called on a backdrop click.
 */
function bindModalBackdrop(id, close) {
  onEl(id, 'click', (e) => { if (e.target === el(id)) close(); });
}


// Login: a 401 from any API call means the session is gone, so surface the
// sign-in form; the auth probes themselves are excluded to avoid a loop.
const nativeFetch = window.fetch.bind(window);
window.fetch = async (...args) => {
  const res = await nativeFetch(...args);
  if (res.status === 401) {
    let url = '';
    try {
      url = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url) || '';
    } catch (e) { /* ignore */ }
    if (url.indexOf('/api/session') === -1 && url.indexOf('/api/login') === -1) {
      showLogin();
    }
  }
  return res;
};

// Resize handle hit-box size, in px.
const HANDLE_SIZE = 8;
// Delete button hit-box size, in px.
const DEL_BTN = 16;
const AUTO_SAVE_DELAY = 400; // ms to coalesce rapid edits into one auto-save

// All image paths in the dataset.
let images = [];
// Split names loaded from data.yaml.
let splits = [];
let filters = [];               // [{name, description, arguments}] (active only)
// Class names from data.yaml.
let classes = [];
// Index into `images` of the current image, or -1.
let currentIndex = -1;
// Name of the active split (e.g. 'train'), or null.
let activeSplit = null;
let activeFilters = [];         // active filter chain, run top to bottom
let boxes = [];        // normalized: {class, cx, cy, w, h, fixed?}
                       // `fixed` is transient (never saved / reloaded): it is
                       // dropped when the image changes and is not written to labels
// Index of the selected box, or -1.
let selected = -1;
let lastSelected = 0; // most recent selected index; Shift resumes here after Esc
// Default class index used when drawing a new box.
let defaultClass = 0;
let justDrawn = false; // whether the selected box was just created (Esc can drop it)
let editingPoint = null; // {i, name} -> coordinate input focused in the side panel (cx/cy/w/h)
let appShortcuts = {}; // app action  -> {shortcut, label} from shortcuts.txt
let actionShortcuts = {}; // user action -> {shortcut, label} from shortcuts.txt
let shortcutErrors = []; // validation errors from shortcuts.txt
let shortcutDefaults = {}; // shipped-only {shortcut, label} (for the reset button)
let userShortcutNames = new Set(); // names overridden in the user shortcuts.txt
let shortcutEditMode = false; // Settings > Shortcuts: edit view on/off
let shortcutDraft = {}; // name -> pending shortcut while editing
let shortcutResets = new Set(); // names to drop from the user file on save
let hookErrors = []; // validation errors from hooks/
let filterErrors = []; // validation errors from filters/
let appActions = []; // built-in app action names (Settings > Actions/Hooks)
let backendActions = []; // built-in server action names
let hookEvents = []; // known hook events
let extensionApiVersion = 1; // extension YAML format version the UI writes
let placeholders = { action: [], filter: [] }; // click-to-insert catalogs
let actionDefs = []; // [{name, steps, after_success, source, status, api_version}]
// Loaded hook definitions (Settings > Hooks).
let hookDefs = [];
// Loaded filter definitions (Settings > Filters).
let filterDefs = [];
let yamlEditor = null; // the file currently open in the raw YAML editor
let undoStack = [];   // snapshots of `boxes` before each edit (fresh per image)
// Snapshots replayed by the redo action, mirroring `undoStack`.
let redoStack = [];
let moved = false;    // whether the current drag actually changed anything yet
let dragUndoPushed = false; // whether the current move/resize drag pushed its undo snapshot
// Natural width of the current image, in px.
let imgW = 0;
// Natural height of the current image, in px.
let imgH = 0;
// Whether unsaved label changes exist.
let dirty = false;
// --readonly: block all writes.
let readonly = false;
// Whether a dataset has been loaded successfully.
let datasetLoaded = false;
let availableTags = [];     // dataset-wide list from tags.yaml (toggle order for Alt+n)
let imageTags = [];         // current image's tags
let boxesVisible = true;    // `app_show_hide`: draw the box overlay or not
let currentDataYaml = '';   // data.yaml of the loaded dataset (for resume)
let hooksByName = new Set(); // event hooks defined in hooks/ (on_<event>)
let hookInFlight = new Set(); // hooks currently running (re-entrancy guard)
let autoSave = false;        // save labels automatically after each edit
let autoSaveTimer = null;    // debounce timer for auto-save
let debugMode = false;       // --debug: log verbose messages to the browser console
let updateInfo = null;        // latest update-check result (see refreshUpdateInfo)
const LAST_IMAGE_KEY = 'ybe_last_image'; // localStorage key: last image reached
const VIEW_KEY = 'ybe_view';             // localStorage key: last split + filter per dataset
const SHOW_BOXES_KEY = 'ybe_show_boxes'; // localStorage key: box overlay shown/hidden
const CLIENT_ID_KEY = 'ybe_client_id';   // sessionStorage key: this tab's presence id
const UPDATE_NOTIFIED_KEY = 'ybe_update_notified'; // localStorage: version@date last shown
const CHANGELOG_SEEN_KEY = 'ybe_changelog_seen'; // localStorage: last version's changelog shown
const TIP_LAST_KEY = 'ybe_tip_last';   // localStorage: date the last tip was shown
const TIPS_SEEN_KEY = 'ybe_tips_seen'; // localStorage: tip indices already shown
const UPDATE_POLL_MS = [4000, 12000]; // retries to pick up the start-thread result

// One id per tab, so the server can count concurrent clients (see /api/presence).
// sessionStorage keeps it across reloads but not across tabs; fall back to a
// random id when storage or crypto is unavailable.
const CLIENT_ID = (() => {
  let id = null;
  try { id = sessionStorage.getItem(CLIENT_ID_KEY); } catch (e) { /* storage unavailable */ }
  if (!id) {
    id = (window.crypto && crypto.randomUUID)
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    try { sessionStorage.setItem(CLIENT_ID_KEY, id); } catch (e) { /* ignore */ }
  }
  return id;
})();

/**
 * Verbose logging, enabled by `--debug`; writes to the browser console.
 * @param {...*} args
 */
function dbg(...args) {
  if (debugMode) console.log('[ybe]', ...args);
}
/**
 * Verbose warning logging, enabled by `--debug`.
 * @param {...*} args
 */
function dbgWarn(...args) {
  if (debugMode) console.warn('[ybe]', ...args);
}

// ------------------------------------------------------------------------- //
// settings: browser-local, mirrored to the backend for cross-browser use
//
// A key set in this browser (localStorage) always wins; the server value is the
// fallback a fresh browser starts from. Every write updates both, so another
// browser that never set the key inherits it. Loaded before appearance init.
// ------------------------------------------------------------------------- //
let serverSettings = {};      // {key: value} last seen from /api/config
let settingsSaveTimer = null; // debounce for batched POST /api/settings
let pendingSettings = {};     // changes waiting to be flushed

/**
 * Read a setting: localStorage first, then the server mirror.
 * @param {string} key
 * @returns {string|null}
 */
function settingsGet(key) {
  let local = null;
  try { local = localStorage.getItem(key); } catch (e) { /* storage unavailable */ }
  if (local !== null) return local;
  if (Object.prototype.hasOwnProperty.call(serverSettings, key)) {
    const v = serverSettings[key];
    return v === null || v === undefined ? null : String(v);
  }
  return null;
}

/**
 * Write a setting to localStorage and the server, debouncing the POST.
 * @param {string} key
 * @param {string|null} value
 */
function settingsSet(key, value) {
  const str = value === null || value === undefined ? null : String(value);
  try {
    if (str === null) localStorage.removeItem(key);
    else localStorage.setItem(key, str);
  } catch (e) { /* ignore */ }
  if (str === null) delete serverSettings[key];
  else serverSettings[key] = str;
  pendingSettings[key] = str;
  clearTimeout(settingsSaveTimer);
  settingsSaveTimer = setTimeout(flushSettings, 150);
}

/**
 * Send any pending settings changes in one POST.
 */
function flushSettings() {
  settingsSaveTimer = null;
  if (!Object.keys(pendingSettings).length) return;
  const body = { settings: pendingSettings };
  pendingSettings = {};
  apiPost('/api/settings', body, { keepalive: true }).then(({ data }) => {
    if (data && data.ok && data.settings) serverSettings = data.settings;
  }).catch(() => { /* offline: the local copy still wins */ });
}

// ------------------------------------------------------------------------- //
// notifications (fixed toasts + bell history; never in the layout flow)
// ------------------------------------------------------------------------- //
const TOAST_MAX = 5;       // at most this many toasts on screen at once
const NOTIF_LOG_MAX = 50;  // keep this many error/warning messages for the bell
let notifLog = [];         // [{type, msg, at}] newest first
let notifUnread = 0;       // sticky messages seen while the bell panel is closed

/**
 * Refresh the unread count badge on the notification bell.
 */
function updateNotifBadge() {
  const badge = el('notifBadge');
  if (!badge) return;
  badge.textContent = notifUnread > 99 ? '99+' : String(notifUnread);
  badge.classList.toggle('hidden', notifUnread <= 0);
}

/**
 * Rebuild the bell panel list from `notifLog`.
 */
function renderNotifPanel() {
  const list = el('notifList');
  if (!list) return;
  list.innerHTML = '';
  if (!notifLog.length) {
    list.appendChild(mk('div', 'notif-empty', 'No notifications.'));
    return;
  }
  notifLog.forEach((n) => {
    const row = mk('div', `notif-item notif-item-${n.type}`);
    row.append(mk('span', 'notif-item-type', n.type), mk('span', null, n.msg));
    list.appendChild(row);
  });
}

/**
 * Open or close the bell panel.
 * @param {boolean} [show] - Force open/closed; toggles when omitted.
 */
function toggleNotifPanel(show) {
  const panel = el('notifPanel');
  if (!panel) return;
  const open = show !== undefined ? !!show : panel.classList.contains('hidden');
  panel.classList.toggle('hidden', !open);
  el('notifBtn').setAttribute('aria-expanded', open ? 'true' : 'false');
  if (open) {
    notifUnread = 0;
    updateNotifBadge();
    renderNotifPanel();
  }
}

/**
 * Show a toast; errors/warnings are sticky by default and recorded in the bell
 * history. Type is info | success | warning | error.
 * @param {string} msg
 * @param {Object} [opts] - type, sticky, log, timeout, action, onClose.
 * @returns {{node: HTMLElement, dismiss: Function}|null}
 */
function toast(msg, opts = {}) {
  const container = el('toasts');
  const text = String(msg == null ? '' : msg);
  if (!text) return;
  const type = opts.type || 'info';
  const sticky = opts.sticky !== undefined
    ? !!opts.sticky
    : (type === 'error' || type === 'warning');
  // errors/warnings are always recorded (recent ones count as unread); `log`
  // records an info/success message too (e.g. the daily update notice).
  const record = type === 'error' || type === 'warning' || opts.log;
  if (record) {
    const newest = notifLog[0];
    if (!(newest && newest.type === type && newest.msg === text)) {
      notifLog.unshift({ type, msg: text, at: Date.now() });
      if (notifLog.length > NOTIF_LOG_MAX) notifLog.length = NOTIF_LOG_MAX;
    }
    notifUnread += 1;
    updateNotifBadge();
    const panel = el('notifPanel');
    if (panel && !panel.classList.contains('hidden')) renderNotifPanel();
    // an auto-dismissing warning is history-only; it must not stay "unread"
    if (!sticky && !opts.log) { notifUnread = Math.max(0, notifUnread - 1); updateNotifBadge(); }
  }
  if (!container) return null;
  const node = mk('div', 'toast toast-' + type);
  const body = mk('div', 'toast-message', text);
  const close = mk('button', 'toast-close', '\u00d7');
  close.title = 'Dismiss';
  const dismiss = () => {
    if (node._gone) return;
    node._gone = true;
    clearTimeout(node._t);
    node.remove();
    if (typeof opts.onClose === 'function') opts.onClose();
  };
  close.addEventListener('click', dismiss);
  node.append(body);
  if (opts.action && opts.action.label) {
    const action = mk('button', 'toast-action', opts.action.label);
    action.addEventListener('click', () => {
      if (typeof opts.action.onClick === 'function') opts.action.onClick();
      dismiss();
    });
    node.append(action);
  }
  node.append(close);
  container.appendChild(node);
  while (container.children.length > TOAST_MAX) container.firstChild.remove();
  if (!sticky) {
    node._t = setTimeout(dismiss, opts.timeout || (type === 'success' ? 3000 : 4000));
  }
  dbg('toast', { type, sticky, msg: text });
  return { node, dismiss };
}

// ------------------------------------------------------------------------- //
// update check (see /api/update-check; cached server-side, checked weekly)
// ------------------------------------------------------------------------- //
/**
 * Paint the current update-check result into the Settings view.
 */
function renderUpdateStatus() {
  const status = el('updateStatus');
  if (!status) return;
  const how = el('updateHowBtn');
  if (!updateInfo) {
    status.textContent = 'Checking…';
    if (how) how.classList.add('hidden');
    return;
  }
  const cur = updateInfo.current_version || 'unknown';
  const latest = updateInfo.latest_version;
  if (updateInfo.update_available) {
    status.textContent = `Update available: ${latest} (you have ${cur})`;
    if (how) how.classList.remove('hidden');
  } else if (latest) {
    status.textContent = `Up to date (${cur})`;
    if (how) how.classList.add('hidden');
  } else {
    status.textContent = `Version ${cur} — latest unknown (offline?)`;
    if (how) how.classList.add('hidden');
  }
}

/**
 * Fetch the latest update-check result and refresh the UI.
 * @param {boolean} [force] - Bypass the server cache.
 * @returns {Promise<void>}
 */
async function refreshUpdateInfo(force = false) {
  try {
    const data = force
      ? (await apiPost('/api/update-check', { force: true })).data
      : await apiGet('/api/update-check');
    if (data && data.update) updateInfo = data.update;
  } catch (e) {
    dbgWarn('update check failed', e);
  }
  renderUpdateStatus();
  notifyUpdateDaily();
}

/**
 * Show one sticky update notice per version per day, with a details button.
 */
function notifyUpdateDaily() {
  if (!updateInfo || !updateInfo.update_available) return;
  const version = updateInfo.latest_version || '';
  const today = new Date().toISOString().slice(0, 10);
  const key = `${version}@${today}`;
  const seen = settingsGet(UPDATE_NOTIFIED_KEY);
  if (seen === key) return;
  settingsSet(UPDATE_NOTIFIED_KEY, key);
  dbg('update notice', updateInfo);
  toast(
    `A new version of YOLO Box Editor is available: ${updateInfo.latest_version} `
      + `(you have ${updateInfo.current_version}).`,
    {
      type: 'info',
      sticky: true,
      log: true,
      action: { label: 'How to update', onClick: openUpdateModal },
    }
  );
}

/**
 * Open the update instructions modal.
 */
function openUpdateModal() {
  const summary = el('updateModalSummary');
  if (summary) {
    if (updateInfo && updateInfo.update_available) {
      summary.textContent = `Version ${updateInfo.latest_version} is available `
        + `(you have ${updateInfo.current_version}). Update with the steps for your setup:`;
    } else {
      summary.textContent = 'Update with the steps for your setup:';
    }
  }
  openModal('updateModal');
}

/**
 * Close the update instructions modal.
 */
function closeUpdateModal() {
  closeModal('updateModal');
}

// ------------------------------------------------------------------------- //
// changelog: show app/CHANGES for the installed version once per version
// ------------------------------------------------------------------------- //
/**
 * Show the changelog once per installed version.
 * @param {Object} cfg - /api/config payload with `version` and `changelog`.
 */
function notifyChangelog(cfg) {
  const version = (cfg && cfg.version) || '';
  const changes = (cfg && Array.isArray(cfg.changelog)) ? cfg.changelog : [];
  if (!version || !changes.length) return;
  const seen = settingsGet(CHANGELOG_SEEN_KEY);
  if (seen === version) return;
  settingsSet(CHANGELOG_SEEN_KEY, version);
  dbg('changelog', version, changes);
  queueAutoModal('changelog', () => showChangelog(version, changes));
}

/**
 * Populate and open the changelog modal.
 * @param {string} version
 * @param {string[]} changes
 */
function showChangelog(version, changes) {
  const title = el('changelogTitle');
  if (title) title.textContent = `What's new in ${version}`;
  const list = el('changelogList');
  if (list) {
    list.innerHTML = '';
    changes.forEach((line) => list.appendChild(mk('li', null, line)));
  }
  openModal('changelogModal');
}

/**
 * Close the changelog modal and release the ambient-modal queue.
 */
function closeChangelog() {
  closeModal('changelogModal');
  releaseAutoModal('changelog');
}

// Ambient modals (dataset prompt, changelog, tip) are all triggered from
// loadConfig and would otherwise stack on a fresh install. Queue them so only
// one is visible at a time; each close releases the next.
let autoModalCurrent = null;
const autoModalQueue = [];

/**
 * Queue an ambient modal until no other one is open.
 * @param {string} id
 * @param {Function} show
 */
function queueAutoModal(id, show) {
  if (autoModalCurrent === id || autoModalQueue.some((m) => m.id === id)) return;
  autoModalQueue.push({ id, show });
  pumpAutoModals();
}

/**
 * Show the next queued ambient modal if none is open.
 */
function pumpAutoModals() {
  if (autoModalCurrent) return;
  const next = autoModalQueue.shift();
  if (!next) return;
  autoModalCurrent = next.id;
  next.show();
}

/**
 * Mark an ambient modal closed and show the next queued one.
 * @param {string} id
 */
function releaseAutoModal(id) {
  const qi = autoModalQueue.findIndex((m) => m.id === id);
  if (qi !== -1) autoModalQueue.splice(qi, 1);
  if (autoModalCurrent !== id) return;
  autoModalCurrent = null;
  pumpAutoModals();
}
