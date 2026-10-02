'use strict';

const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');

const el = (id) => document.getElementById(id);

const HANDLE_SIZE = 8;
const DEL_BTN = 16;
const AUTO_SAVE_DELAY = 400; // ms to coalesce rapid edits into one auto-save

let images = [];
let splits = [];
let filters = [];
let classes = [];
let currentIndex = -1;
let activeSplit = null;
let activeFilters = [];         // active filter chain, run top to bottom
let boxes = [];        // normalized: {class, cx, cy, w, h, fixed?}
                       // `fixed` is transient (never saved / reloaded): it is
                       // dropped when the image changes and is not written to labels
let selected = -1;
let lastSelected = 0; // most recent selected index; Shift resumes here after Esc
let defaultClass = 0;
let justDrawn = false; // whether the selected box was just created (Esc can drop it)
let editingPoint = null; // {i, name} -> coordinate input focused in the side panel (cx/cy/w/h)
let appShortcuts = {}; // app action  -> {shortcut, label} from shortcuts.txt
let actionShortcuts = {}; // user action -> {shortcut, label} from shortcuts.txt
let shortcutErrors = []; // validation errors from shortcuts.txt
let hookErrors = []; // validation errors from hooks/
let undoStack = [];   // snapshots of `boxes` before each edit (fresh per image)
let redoStack = [];
let moved = false;    // whether the current drag actually changed anything yet
let imgW = 0;
let imgH = 0;
let dirty = false;
let readonly = false;
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

// Verbose logging, enabled by `python app.py --debug` (exposed via /api/config).
// Writes to the browser console so the whole client flow can be traced.
function dbg(...args) {
  if (debugMode) console.log('[ybe]', ...args);
}
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

function flushSettings() {
  settingsSaveTimer = null;
  if (!Object.keys(pendingSettings).length) return;
  const body = { settings: pendingSettings };
  pendingSettings = {};
  fetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    keepalive: true,
  }).then((r) => r.json()).then((data) => {
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

function updateNotifBadge() {
  const badge = el('notifBadge');
  if (!badge) return;
  badge.textContent = notifUnread > 99 ? '99+' : String(notifUnread);
  badge.classList.toggle('hidden', notifUnread <= 0);
}

function renderNotifPanel() {
  const list = el('notifList');
  if (!list) return;
  list.innerHTML = '';
  if (!notifLog.length) {
    const empty = document.createElement('div');
    empty.className = 'notif-empty';
    empty.textContent = 'No notifications.';
    list.appendChild(empty);
    return;
  }
  notifLog.forEach((n) => {
    const row = document.createElement('div');
    row.className = `notif-item notif-item-${n.type}`;
    const type = document.createElement('span');
    type.className = 'notif-item-type';
    type.textContent = n.type;
    const msg = document.createElement('span');
    msg.textContent = n.msg;
    row.append(type, msg);
    list.appendChild(row);
  });
}

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

// type: info | success | warning | error. Errors/warnings are sticky by default:
// they stay until dismissed and are recorded in the bell history.
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
  const node = document.createElement('div');
  node.className = 'toast toast-' + type;
  const body = document.createElement('div');
  body.className = 'toast-message';
  body.textContent = text;
  const close = document.createElement('button');
  close.className = 'toast-close';
  close.textContent = '\u00d7';
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
    const action = document.createElement('button');
    action.className = 'toast-action';
    action.textContent = opts.action.label;
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

async function refreshUpdateInfo(force = false) {
  try {
    const res = force
      ? await fetch('/api/update-check', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ force: true }),
        })
      : await fetch('/api/update-check');
    const data = await res.json();
    if (data && data.update) updateInfo = data.update;
  } catch (e) {
    dbgWarn('update check failed', e);
  }
  renderUpdateStatus();
  notifyUpdateDaily();
}

// One sticky notice per day (and per version) with a details button.
function notifyUpdateDaily() {
  if (!updateInfo || !updateInfo.update_available) return;
  const version = updateInfo.latest_version || '';
  const today = new Date().toISOString().slice(0, 10);
  const key = `${version}@${today}`;
  let seen = null;
  try { seen = localStorage.getItem(UPDATE_NOTIFIED_KEY); } catch (e) { /* ignore */ }
  if (seen === key) return;
  try { localStorage.setItem(UPDATE_NOTIFIED_KEY, key); } catch (e) { /* ignore */ }
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
  el('updateModal').classList.remove('hidden');
}

function closeUpdateModal() {
  el('updateModal').classList.add('hidden');
}

// ------------------------------------------------------------------------- //
// changelog: show app/CHANGES for the installed version once per version
// ------------------------------------------------------------------------- //
function notifyChangelog(cfg) {
  const version = (cfg && cfg.version) || '';
  const changes = (cfg && Array.isArray(cfg.changelog)) ? cfg.changelog : [];
  if (!version || !changes.length) return;
  let seen = null;
  try { seen = localStorage.getItem(CHANGELOG_SEEN_KEY); } catch (e) { /* ignore */ }
  if (seen === version) return;
  try { localStorage.setItem(CHANGELOG_SEEN_KEY, version); } catch (e) { /* ignore */ }
  dbg('changelog', version, changes);
  queueAutoModal('changelog', () => showChangelog(version, changes));
}

function showChangelog(version, changes) {
  const title = el('changelogTitle');
  if (title) title.textContent = `What's new in ${version}`;
  const list = el('changelogList');
  if (list) {
    list.innerHTML = '';
    changes.forEach((line) => {
      const li = document.createElement('li');
      li.textContent = line;
      list.appendChild(li);
    });
  }
  el('changelogModal').classList.remove('hidden');
}

function closeChangelog() {
  el('changelogModal').classList.add('hidden');
  releaseAutoModal('changelog');
}

// Ambient modals (dataset prompt, changelog, tip) are all triggered from
// loadConfig and would otherwise stack on a fresh install. Queue them so only
// one is visible at a time; each close releases the next.
let autoModalCurrent = null;
const autoModalQueue = [];

function queueAutoModal(id, show) {
  if (autoModalCurrent === id || autoModalQueue.some((m) => m.id === id)) return;
  autoModalQueue.push({ id, show });
  pumpAutoModals();
}

function pumpAutoModals() {
  if (autoModalCurrent) return;
  const next = autoModalQueue.shift();
  if (!next) return;
  autoModalCurrent = next.id;
  next.show();
}

function releaseAutoModal(id) {
  const qi = autoModalQueue.findIndex((m) => m.id === id);
  if (qi !== -1) autoModalQueue.splice(qi, 1);
  if (autoModalCurrent !== id) return;
  autoModalCurrent = null;
  pumpAutoModals();
}

// interaction state
let mode = 'idle';     // idle | drawing | moving | resizing
let start = null;      // canvas px
let dragStart = null;  // canvas px
let mouse = null;      // canvas px
let origBox = null;    // normalized snapshot at drag start
let handle = null;

const imageEl = new Image();
imageEl.onload = () => {
  imgW = imageEl.naturalWidth;
  imgH = imageEl.naturalHeight;
  canvas.width = imgW;
  canvas.height = imgH;
  dbg('image loaded', { src: imageEl.src, size: `${imgW}x${imgH}` });
  draw();
};
imageEl.onerror = () => {
  // the image file is gone (e.g. removed by an action): blank the canvas so
  // no stale frame keeps showing a deleted image.
  dbgWarn('image failed to load', { src: imageEl.src });
  imgW = 0;
  imgH = 0;
  canvas.width = 0;
  canvas.height = 0;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  boxes = [];
  selected = -1;
  imageTags = [];
  draw();
};

function clamp01(v) {
  return Math.max(0, Math.min(1, v));
}

function toPx(b) {
  return {
    x: (b.cx - b.w / 2) * imgW,
    y: (b.cy - b.h / 2) * imgH,
    w: b.w * imgW,
    h: b.h * imgH,
  };
}

function toNorm(r) {
  return {
    class: defaultClass,
    cx: clamp01((r.x + r.w / 2) / imgW),
    cy: clamp01((r.y + r.h / 2) / imgH),
    w: clamp01(r.w / imgW),
    h: clamp01(r.h / imgH),
  };
}

function normRect(a, b) {
  return {
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    w: Math.abs(a.x - b.x),
    h: Math.abs(a.y - b.y),
  };
}

function clampToImage(p) {
  return {
    x: Math.max(0, Math.min(imgW, p.x)),
    y: Math.max(0, Math.min(imgH, p.y)),
  };
}

function handlePoints(r) {
  const midX = r.x + r.w / 2;
  const midY = r.y + r.h / 2;
  return [
    { x: r.x, y: r.y, name: 'nw' },
    { x: midX, y: r.y, name: 'n' },
    { x: r.x + r.w, y: r.y, name: 'ne' },
    { x: r.x + r.w, y: midY, name: 'e' },
    { x: r.x + r.w, y: r.y + r.h, name: 'se' },
    { x: midX, y: r.y + r.h, name: 's' },
    { x: r.x, y: r.y + r.h, name: 'sw' },
    { x: r.x, y: midY, name: 'w' },
  ];
}

function draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (imgW && imgH && imageEl.complete && imageEl.naturalWidth) {
    ctx.drawImage(imageEl, 0, 0);
  }

  // a coordinate input highlight only survives while that input keeps focus
  const f = document.activeElement;
  if (editingPoint && (!f || f.dataset.name !== editingPoint.name)) editingPoint = null;

  if (boxesVisible) {
    boxes.forEach((b, idx) => {
      const r = toPx(b);
      const active = idx === selected;
      // fixed boxes: muted dashed outline, no resize handles (they ignore
      // dragging but can still be clicked / selected)
      const fixed = !!b.fixed;
      ctx.strokeStyle = fixed ? '#8a93a6' : active ? '#ffd166' : '#2ecc71';
      ctx.lineWidth = active && !fixed ? 3 : 2;
      if (fixed) ctx.setLineDash([7, 4]);
      ctx.strokeRect(r.x, r.y, r.w, r.h);
      ctx.setLineDash([]);

      const label = `${b.class}: ${classes[b.class] || 'class ' + b.class}`;
      ctx.font = '14px system-ui, sans-serif';
      const tw = ctx.measureText(label).width;
      const ly = Math.max(0, r.y - 18);
      ctx.fillStyle = fixed
        ? 'rgba(138,147,166,0.9)'
        : active ? 'rgba(255,209,102,0.92)' : 'rgba(46,204,113,0.85)';
      ctx.fillRect(r.x, ly, tw + 8, 18);
      ctx.fillStyle = '#111';
      ctx.fillText(label, r.x + 4, ly + 13);

      if (!readonly) {
        drawDeleteButton(r);
        drawClassButton(r);
      }
      if (active && !readonly && !fixed) drawHandles(r);
      if (editingPoint && editingPoint.i === idx) drawPointGuide(r, editingPoint.name);
    });
  }

  if (mode === 'drawing' && start && mouse) {
    const r = normRect(start, mouse);
    ctx.strokeStyle = '#4cc9f0';
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);
    ctx.strokeRect(r.x, r.y, r.w, r.h);
    ctx.setLineDash([]);
  }

  syncSidePanel();
}

function drawHandles(r) {
  ctx.fillStyle = '#fff';
  ctx.strokeStyle = '#111';
  ctx.lineWidth = 1;
  for (const p of handlePoints(r)) {
    ctx.fillRect(p.x - HANDLE_SIZE / 2, p.y - HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE);
    ctx.strokeRect(p.x - HANDLE_SIZE / 2, p.y - HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE);
  }
}

// Highlight the coordinate currently edited in the side panel, so the user
// sees which value (cx / cy / w / h) the focused input controls. cx/cy show
// only the box center point in colour; w/h also mark the box edges they span.
function drawPointGuide(r, name) {
  const midX = r.x + r.w / 2;
  const midY = r.y + r.h / 2;
  ctx.save();
  ctx.strokeStyle = '#ff9f1c';
  ctx.fillStyle = '#ff9f1c';
  ctx.lineWidth = 2;
  ctx.setLineDash([6, 4]);
  const dashLine = (x1, y1, x2, y2) => {
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
  };
  if (name === 'w') {
    dashLine(r.x, midY - r.h / 2 - 10, r.x, midY + r.h / 2 + 10);
    dashLine(r.x + r.w, midY - r.h / 2 - 10, r.x + r.w, midY + r.h / 2 + 10);
  } else if (name === 'h') {
    dashLine(midX - r.w / 2 - 10, r.y, midX + r.w / 2 + 10, r.y);
    dashLine(midX - r.w / 2 - 10, r.y + r.h, midX + r.w / 2 + 10, r.y + r.h);
  }
  ctx.setLineDash([]);
  ctx.beginPath();
  ctx.arc(midX, midY, name === 'cx' || name === 'cy' ? 6 : 5, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function deleteBtnRect(r) {
  return { x: r.x + r.w - DEL_BTN, y: r.y, w: DEL_BTN, h: DEL_BTN };
}

function classBtnRect(r) {
  return { x: r.x, y: r.y, w: DEL_BTN, h: DEL_BTN };
}

function drawClassButton(r) {
  const d = classBtnRect(r);
  ctx.fillStyle = 'rgba(76, 201, 240, 0.9)';
  ctx.fillRect(d.x, d.y, d.w, d.h);
  ctx.strokeStyle = '#111';
  ctx.lineWidth = 1;
  ctx.strokeRect(d.x, d.y, d.w, d.h);
  ctx.fillStyle = '#111';
  ctx.font = 'bold 13px system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('/', d.x + d.w / 2, d.y + d.h / 2 + 1);
  ctx.textAlign = 'start';
  ctx.textBaseline = 'alphabetic';
}

function drawDeleteButton(r) {
  const d = deleteBtnRect(r);
  ctx.fillStyle = 'rgba(231, 76, 60, 0.9)';
  ctx.fillRect(d.x, d.y, d.w, d.h);
  ctx.strokeStyle = '#111';
  ctx.lineWidth = 1;
  ctx.strokeRect(d.x, d.y, d.w, d.h);
  const cx = d.x + d.w / 2;
  const cy = d.y + d.h / 2;
  const inset = 4;
  ctx.strokeStyle = '#fff';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(cx - inset, cy - inset);
  ctx.lineTo(cx + inset, cy + inset);
  ctx.moveTo(cx + inset, cy - inset);
  ctx.lineTo(cx - inset, cy + inset);
  ctx.stroke();
}

function canvasPos(e) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  return {
    x: (e.clientX - rect.left) * scaleX,
    y: (e.clientY - rect.top) * scaleY,
  };
}

function hitTest(p) {
  // hidden boxes are not drawn, so they must not swallow clicks either
  if (!boxesVisible) return { type: 'none' };
  if (selected >= 0 && !boxes[selected].fixed) {
    const r = toPx(boxes[selected]);
    for (const hp of handlePoints(r)) {
      if (Math.abs(p.x - hp.x) <= HANDLE_SIZE && Math.abs(p.y - hp.y) <= HANDLE_SIZE) {
        return { type: 'handle', handle: hp.name, index: selected };
      }
    }
  }
  for (let i = boxes.length - 1; i >= 0; i--) {
    const d = deleteBtnRect(toPx(boxes[i]));
    if (p.x >= d.x && p.x <= d.x + d.w && p.y >= d.y && p.y <= d.y + d.h) {
      return { type: 'delete', index: i };
    }
  }
  for (let i = boxes.length - 1; i >= 0; i--) {
    const c = classBtnRect(toPx(boxes[i]));
    if (p.x >= c.x && p.x <= c.x + c.w && p.y >= c.y && p.y <= c.y + c.h) {
      return { type: 'class', index: i };
    }
  }
  for (let i = boxes.length - 1; i >= 0; i--) {
    const r = toPx(boxes[i]);
    if (p.x >= r.x && p.x <= r.x + r.w && p.y >= r.y && p.y <= r.y + r.h) {
      return { type: 'box', index: i };
    }
  }
  return { type: 'none' };
}

// Cursor shown while hovering each resize handle, so the user can see the box
// is ready to resize (and in which direction) before pressing the mouse.
const RESIZE_CURSORS = {
  nw: 'nwse-resize', se: 'nwse-resize',
  ne: 'nesw-resize', sw: 'nesw-resize',
  n: 'ns-resize', s: 'ns-resize',
  e: 'ew-resize', w: 'ew-resize',
};

function updateCursor(p) {
  if (mode !== 'idle' || readonly || !boxesVisible) return;
  const hit = hitTest(p);
  canvas.style.cursor =
    hit.type === 'handle' ? RESIZE_CURSORS[hit.handle] || 'crosshair' : '';
}

// True when the force-draw modifier is held for this event. The modifier is
// configured by the `app_force_draw` binding in your shortcuts.txt
// (e.g. <Ctrl>, <Alt> or <Ctrl+Shift>); it is not a keydown action. Falls back
// to Ctrl when unbound. Ctrl/Meta are the Linux-safe choices — many window
// managers swallow Alt+drag, and Shift is reserved for selecting boxes.
function forceDrawActive(e) {
  const info = appShortcuts['app_force_draw'];
  const spec = (info && info.shortcut) || 'Ctrl';
  const mods = spec.split('+').map((s) => s.trim().toLowerCase()).filter(Boolean);
  if (!mods.length) return false;
  return mods.every((m) => {
    if (m === 'ctrl' || m === 'control') return e.ctrlKey;
    if (m === 'alt') return e.altKey;
    if (m === 'shift') return e.shiftKey;
    if (m === 'meta' || m === 'cmd' || m === 'command') return e.metaKey;
    return false;
  });
}

function syncClassSelect(idx) {
  if (idx >= 0) lastSelected = idx;
  const sel = el('classSelect');
  if (!sel) return;
  sel.value = idx >= 0 ? boxes[idx].class : defaultClass;
}

function moveBox(p) {
  const dx = (p.x - dragStart.x) / imgW;
  const dy = (p.y - dragStart.y) / imgH;
  // clamp the centre so the whole box stays inside the image, not just its
  // centre point (the window-level drag can report coordinates off-canvas)
  const cx = Math.max(origBox.w / 2, Math.min(1 - origBox.w / 2, origBox.cx + dx));
  const cy = Math.max(origBox.h / 2, Math.min(1 - origBox.h / 2, origBox.cy + dy));
  boxes[selected] = { ...origBox, cx, cy };
  moved = true;
  draw();
}

function resizeBox(p) {
  p = clampToImage(p);
  const b = origBox;
  const left = (b.cx - b.w / 2) * imgW;
  const right = (b.cx + b.w / 2) * imgW;
  const top = (b.cy - b.h / 2) * imgH;
  const bottom = (b.cy + b.h / 2) * imgH;

  let x1 = left;
  let y1 = top;
  let x2 = right;
  let y2 = bottom;
  if (handle.includes('w')) x1 = p.x;
  if (handle.includes('e')) x2 = p.x;
  if (handle.includes('n')) y1 = p.y;
  if (handle.includes('s')) y2 = p.y;
  // keep every edge within the image
  x1 = Math.max(0, Math.min(imgW, x1));
  x2 = Math.max(0, Math.min(imgW, x2));
  y1 = Math.max(0, Math.min(imgH, y1));
  y2 = Math.max(0, Math.min(imgH, y2));
  if (x2 < x1) [x1, x2] = [x2, x1];
  if (y2 < y1) [y1, y2] = [y2, y1];

  const w = Math.max(x2 - x1, 1);
  const h = Math.max(y2 - y1, 1);
  boxes[selected] = {
    ...origBox,
    cx: clamp01((x1 + x2) / 2 / imgW),
    cy: clamp01((y1 + y2) / 2 / imgH),
    w: clamp01(w / imgW),
    h: clamp01(h / imgH),
  };
  moved = true;
  draw();
}

// ------------------------------------------------------------------------- //
// read-only mode
// ------------------------------------------------------------------------- //
function applyReadonly() {
  const sw = el('readonlySw');
  sw.checked = readonly;
  // When the server was started with --readonly it is a hard lock.
  sw.disabled = !!readonly && !!sw.dataset.server;
  const classSel = el('classSelect');
  if (classSel) classSel.disabled = readonly;
  setActionButtonsDisabled(readonly);
  updateHistoryButtons();
  renderTagBar();
  draw();
}

el('readonlySw').addEventListener('change', (e) => {
  readonly = e.target.checked;
  if (readonly) {
    selected = -1;
    clearTimeout(autoSaveTimer); // no writes in read-only mode
    autoSaveTimer = null;
  }
  applyReadonly();
});

// ------------------------------------------------------------------------- //
// navigation & data loading
// ------------------------------------------------------------------------- //
function updateNav() {
  const total = images.length;
  el('counter').value = total ? `${currentIndex + 1} / ${total}` : '0 / 0';
  el('prevBtn').disabled = total === 0 || currentIndex <= 0;
  el('nextBtn').disabled = total === 0 || currentIndex >= total - 1;
}

// jump to image N (1-based) typed into the counter input
async function jumpToImage(text) {
  if (!images.length) return;
  const m = String(text).match(/\d+/);
  const n = m ? parseInt(m[0], 10) : NaN;
  if (isNaN(n) || n < 1) {
    updateNav();
    return;
  }
  const idx = Math.min(Math.max(n - 1, 0), images.length - 1);
  if (idx !== currentIndex && dirty) {
    if (autoSave) {
      if (!(await flushAutoSave())) {
        updateNav();
        return;
      }
    } else if (!confirm('You have unsaved changes. Discard them?')) {
      updateNav();
      return;
    }
  }
  loadImage(idx);
}

let loadDataAutoOpened = false;
let tipChecked = false; // the daily tip is considered at most once per page load

// Show one random, not-yet-seen tip at most once per day. The tip list ships in
// the backend (config.tips); this browser remembers the date and which indices
// it has seen, and resets the seen list once every tip has appeared.
function maybeShowTip(tips) {
  if (tipChecked) return;
  tipChecked = true;
  if (settingsGet('ybe_tips_enabled') === '0') return;
  if (!Array.isArray(tips) || !tips.length) return;

  const today = new Date().toISOString().slice(0, 10);
  let last = null;
  try { last = localStorage.getItem(TIP_LAST_KEY); } catch (e) { /* ignore */ }
  if (last === today) return;

  let seen = [];
  try { seen = JSON.parse(localStorage.getItem(TIPS_SEEN_KEY) || '[]'); } catch (e) { seen = []; }
  if (!Array.isArray(seen)) seen = [];

  let pool = tips.map((_, i) => i).filter((i) => !seen.includes(i));
  if (!pool.length) { pool = tips.map((_, i) => i); seen = []; }
  const idx = pool[Math.floor(Math.random() * pool.length)];
  seen.push(idx);

  try {
    localStorage.setItem(TIP_LAST_KEY, today);
    localStorage.setItem(TIPS_SEEN_KEY, JSON.stringify(seen));
  } catch (e) { /* ignore */ }

  queueAutoModal('tip', () => {
    el('tipText').textContent = tips[idx];
    el('tipModal').classList.remove('hidden');
  });
}

function closeTipModal() {
  el('tipModal').classList.add('hidden');
  releaseAutoModal('tip');
}

function selectSettingsTab(name) {
  document.querySelectorAll('.settings-tab').forEach((tab) => {
    tab.classList.toggle('active', tab.dataset.tab === name);
  });
  document.querySelectorAll('.settings-panel').forEach((panel) => {
    panel.classList.toggle('active', panel.dataset.panel === name);
  });
}

function openSettingsModal() {
  el('settingsModal').classList.remove('hidden');
  // With no dataset, the Dataset tab is the only useful one.
  if (!datasetLoaded) selectSettingsTab('dataset');
  if (!datasetLoaded) {
    const input = el('dataYaml');
    input.focus();
    input.select();
  }
}

function closeSettingsModal() {
  el('settingsModal').classList.add('hidden');
}

function openLoadDataModal() {
  queueAutoModal('loadData', () => {
    el('loadDataModal').classList.remove('hidden');
    const input = el('loadDataYaml');
    input.focus();
    input.select();
  });
}

function closeLoadDataModal() {
  el('loadDataModal').classList.add('hidden');
  releaseAutoModal('loadData');
}

function populateSplitSelect() {
  const sel = el('splitSelect');
  sel.innerHTML = '';
  const all = document.createElement('option');
  all.value = '';
  all.textContent = 'All splits';
  sel.appendChild(all);
  splits.forEach((s) => {
    const opt = document.createElement('option');
    opt.value = s.name;
    opt.textContent = s.name;
    sel.appendChild(opt);
  });
  sel.value = activeSplit || '';
}

const FILTER_CHAIN_MAX = 8;

function populateFilterPanel() {
  const body = el('filterPanelBody');
  if (!body) return;
  body.innerHTML = '';
  if (!filters.length) {
    const empty = document.createElement('div');
    empty.className = 'filter-empty';
    empty.textContent = 'No filters found in filters/.';
    body.appendChild(empty);
    return;
  }
  const count = Math.min(filters.length, FILTER_CHAIN_MAX);
  for (let i = 0; i < count; i++) {
    const sel = document.createElement('select');
    const none = document.createElement('option');
    none.value = '';
    none.textContent = i === 0 ? 'No filter' : '(none)';
    sel.appendChild(none);
    filters.forEach((name) => {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      sel.appendChild(opt);
    });
    sel.value = activeFilters[i] || '';
    body.appendChild(sel);
  }
}

function selectedFilterChain() {
  const names = [];
  const body = el('filterPanelBody');
  if (body) body.querySelectorAll('select').forEach((s) => {
    if (s.value) names.push(s.value);
  });
  return names;
}

function populateRecent(paths) {
  const sel = el('recentSelect');
  sel.innerHTML = '';
  const list = paths || [];
  // Nothing to pick from: hide the dropdown entirely.
  sel.classList.toggle('hidden', list.length === 0);
  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = 'Recent…';
  sel.appendChild(placeholder);
  list.forEach((p) => {
    const opt = document.createElement('option');
    opt.value = p;
    opt.textContent = p;
    sel.appendChild(opt);
  });
  sel.value = '';
}

const ACTIONS_VISIBLE = 3;
let actionsExpanded = false;

// Show only the first ACTIONS_VISIBLE action buttons; reveal the rest when the
// expand button (…) is toggled.
function applyActionOverflow() {
  const box = el('actionBtns');
  const expand = el('actionsExpandBtn');
  if (!box || !expand) return;
  const items = Array.from(box.querySelectorAll('button.action'));
  const overflow = items.length > ACTIONS_VISIBLE;
  expand.classList.toggle('hidden', !overflow);
  box.classList.toggle('expanded', actionsExpanded);
  items.forEach((b, i) => {
    b.classList.toggle('hidden', overflow && !actionsExpanded && i >= ACTIONS_VISIBLE);
  });
  expand.title = actionsExpanded ? 'Show fewer actions' : 'Show all actions';
}

function populateActions(names) {
  const box = el('actionBtns');
  box.innerHTML = '';
  actionsExpanded = false;
  (names || []).forEach((n) => {
    const btn = document.createElement('button');
    btn.className = 'action';
    btn.textContent = n;
    const sc = actionShortcuts[n] && actionShortcuts[n].shortcut;
    btn.title = sc ? `Run action "${n}" on the current image (${sc})` : `Run action "${n}" on the current image`;
    if (sc) {
      const badge = document.createElement('span');
      badge.className = 'btn-shortcut';
      badge.textContent = sc;
      btn.appendChild(badge);
    }
    btn.addEventListener('click', () => runAction(n));
    box.appendChild(btn);
  });
  applyActionOverflow();
}

function setActionButtonsDisabled(disabled) {
  el('actionBtns').querySelectorAll('button').forEach((b) => { b.disabled = disabled; });
}

// ------------------------------------------------------------------------- //
// shortcuts (modal)
// ------------------------------------------------------------------------- //
function shortcutKbd(text) {
  const k = document.createElement('kbd');
  k.textContent = text;
  return k;
}

function menuRow(label, keys) {
  const row = document.createElement('div');
  row.className = 'menu-row';
  const lbl = document.createElement('span');
  lbl.className = 'menu-label';
  lbl.textContent = label;
  const keyBox = document.createElement('span');
  keyBox.className = 'menu-keys';
  (Array.isArray(keys) ? keys : [keys]).forEach((k) => keyBox.appendChild(shortcutKbd(k)));
  row.append(lbl, keyBox);
  return row;
}

const APP_SHORTCUT_ORDER = ['app_prev', 'app_next', 'app_del', 'app_drop', 'app_undo', 'app_redo', 'app_save', 'app_ch_box', 'app_sel_box', 'app_sel_points', 'app_escape', 'app_show_hide', 'app_fix_box', 'app_force_draw', 'app_refresh_images_list', 'app_reload_images_list', 'app_refresh_image'];

let shownShortcutErrors = '';

function renderShortcutErrors() {
  const dismissed = JSON.parse(sessionStorage.getItem('dismissedShortcutErrors') || '[]');
  // messages are self-describing ("'shortcuts.txt': ..." / "'hooks/x.yaml': ...")
  const all = shortcutErrors.concat(hookErrors);
  const visible = all.filter((msg) => !dismissed.includes(msg));
  if (!visible.length) return;
  const msg = visible.join(' | ');
  if (msg === shownShortcutErrors) return; // config reloads must not re-toast it
  shownShortcutErrors = msg;
  toast(msg, {
    type: 'error',
    sticky: true,
    onClose: () => {
      const updated = dismissed.concat(visible);
      sessionStorage.setItem('dismissedShortcutErrors', JSON.stringify(updated));
    },
  });
}

// --------------------------------------------------------------------------- //
// Concurrent-client warning: ping /api/presence and show a dismissible message
// while more than one client is using the app. Informational only; it never
// blocks editing. The server is the source of truth so different browsers and
// machines are counted too.
// --------------------------------------------------------------------------- //
const PRESENCE_INTERVAL = 5000; // ms between presence pings
let presenceTimer = null;
let presenceDismissed = false;
let presenceToast = null;

function renderPresenceWarning(count) {
  if (count <= 1) {
    // overlap is over: hide the toast, and warn again on a later overlap
    presenceDismissed = false;
    if (presenceToast) { presenceToast.dismiss(); presenceToast = null; }
    return;
  }
  if (presenceDismissed || presenceToast) return;
  presenceToast = toast(
    'Another user is using this app. It is designed for one user at a time and is ' +
    'not meant to be served to multiple clients, so your changes may overwrite theirs.',
    {
      type: 'warning',
      sticky: true,
      onClose: () => { presenceDismissed = true; presenceToast = null; },
    });
}

async function pingPresence(bye = false) {
  try {
    const res = await fetch('/api/presence', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cid: CLIENT_ID, bye }),
      keepalive: bye,
    });
    const data = await res.json();
    dbg('presence', { count: data.count, bye });
    if (!bye) renderPresenceWarning(data.count || 0);
  } catch (e) { /* presence is best-effort */ }
}

function startPresence() {
  pingPresence();
  clearInterval(presenceTimer);
  presenceTimer = setInterval(pingPresence, PRESENCE_INTERVAL);
  // background tabs get their timers throttled; ping again as soon as we are visible
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') pingPresence();
  });
  window.addEventListener('pagehide', () => {
    const body = JSON.stringify({ cid: CLIENT_ID, bye: true });
    if (navigator.sendBeacon) {
      navigator.sendBeacon('/api/presence', new Blob([body], { type: 'application/json' }));
    }
  });
}

function shortcutSection(title) {
  const h = document.createElement('div');
  h.className = 'shortcut-section';
  h.textContent = title;
  return h;
}

function renderShortcuts() {
  const wrap = el('shortcutItems');
  if (!wrap) return;
  wrap.innerHTML = '';

  const appNames = APP_SHORTCUT_ORDER.filter((name) => appShortcuts[name]);
  if (appNames.length) {
    wrap.appendChild(shortcutSection('App'));
    appNames.forEach((name) => {
      const info = appShortcuts[name];
      wrap.appendChild(menuRow(info.label, info.shortcut));
    });
  }
  if (Object.keys(actionShortcuts).length) {
    wrap.appendChild(shortcutSection('Actions'));
    Object.entries(actionShortcuts).forEach(([name, info]) => {
      wrap.appendChild(menuRow(`${name}: ${info.label}`.trim(), info.shortcut));
    });
  }
  wrap.appendChild(shortcutSection('Mouse'));
  const mouse = document.createElement('div');
  mouse.className = 'menu-row';
  const mlabel = document.createElement('span');
  mlabel.className = 'menu-label';
  mlabel.textContent = 'Drag to draw · \u2715 to delete box';
  mouse.appendChild(mlabel);
  wrap.appendChild(mouse);
}

function populateClasses() {
  if (classes.length === 0) classes = ['class_0'];
  if (defaultClass >= classes.length) defaultClass = 0;
  const sel = el('classSelect');
  if (!sel) return;
  sel.innerHTML = '';
  classes.forEach((name, i) => {
    const opt = document.createElement('option');
    opt.value = i;
    opt.textContent = `${i}: ${name}`;
    sel.appendChild(opt);
  });
  sel.value = defaultClass;
}

async function loadConfig(startIdx = 0, opts = {}) {
  const cfg0 = await (await fetch('/api/config')).json();
  console.log(`[ybe] yolo-box-editor v${cfg0.version || '?'}`);
  serverSettings = cfg0.settings || {};
  initSettings();
  debugMode = !!cfg0.debug;
  if (cfg0.update) updateInfo = cfg0.update;
  if (debugMode) console.log('[ybe] debug mode on — verbose logging enabled (--debug)');
  const cfg = opts.skipFilterRestore ? cfg0 : await maybeRestoreView(cfg0);
  dbg('config loaded', {
    data_yaml: cfg.data_yaml, dataset_path: cfg.dataset_path,
    images: (cfg.images || []).length, splits: (cfg.splits || []).map((s) => s.name),
    classes: cfg.classes, active_split: cfg.active_split,
    filters: cfg.filters, active_filters: cfg.active_filters, filter_error: cfg.filter_error,
    actions: cfg.actions, hooks: cfg.hooks, hook_errors: cfg.hook_errors,
    readonly: cfg.readonly, debug: cfg.debug,
  });
  images = cfg.images || [];
  splits = cfg.splits || [];
  filters = cfg.filters || [];
  activeSplit = cfg.active_split || null;
  activeFilters = cfg.active_filters || [];
  classes = cfg.classes || ['class_0'];
  availableTags = cfg.tags || [];
  datasetLoaded = !!cfg.data_yaml;
  el('dataYaml').value = cfg.data_yaml || '';
  el('tagsDirInput').value = cfg.tags_dir || '';
  currentDataYaml = cfg.data_yaml || '';
  {
    const dsPath = cfg.dataset_path || cfg.data_yaml || '';
    const dsName = dsPath ? dsPath.replace(/[\\/]+$/, '').split(/[\\/]/).pop() : '';
    el('datasetPath').textContent = dsName || 'No dataset';
    el('datasetPath').title = dsPath || 'No dataset loaded';
  }
  readonly = !!cfg.readonly;
  if (!datasetLoaded && !loadDataAutoOpened) {
    loadDataAutoOpened = true;
    openLoadDataModal();
  }
  el('readonlySw').dataset.server = cfg.readonly ? '1' : '';
  applyReadonly();
  populateClasses();
  populateSplitSelect();
  populateFilterPanel();
  populateRecent(cfg.recent_data_yamls || []);
  actionShortcuts = cfg.action_shortcuts || {};
  appShortcuts = cfg.shortcuts || {};
  shortcutErrors = cfg.shortcut_errors || [];
  hookErrors = cfg.hook_errors || [];
  hooksByName = new Set(cfg.hooks || []);
  renderShortcutErrors();
  populateActions(cfg.actions || []);
  renderShortcuts();
  persistView(cfg);
  if (cfg.filter_error) showTransientFilterMessage(cfg.filter_error);
  if (images.length) {
    if (opts.explicit) {
      loadImage(startIdx);
    } else if (opts.anchor) {
      loadImage(resolveImageAnchor(opts.anchor));
    } else if (!opts.noResume) {
      resumeLastImage(cfg);
    } else {
      loadImage(0);
    }
  } else {
    currentIndex = -1;
    boxes = [];
    selected = -1;
    justDrawn = false;
    imageTags = [];
    imgW = 0;
    imgH = 0;
    canvas.width = 0;
    canvas.height = 0;
    updateNav();
    renderSidePanel();
    renderTagBar();
  }
  renderUpdateStatus();
  notifyUpdateDaily();
  notifyChangelog(cfg0);
  maybeShowTip(cfg0.tips);
  runHook('on_images_list_loaded');
}

// The active split and filter (and the split a filter was selected with) live
// in the server's STATE, which a restart clears. Persist them per dataset so the
// view is restored.
function persistView(cfg) {
  try {
    if (!cfg.data_yaml) return;
    localStorage.setItem(VIEW_KEY, JSON.stringify({
      dataYaml: cfg.data_yaml,
      split: cfg.active_split || null,
      filters: cfg.active_filters || [],
    }));
  } catch (e) { /* storage unavailable */ }
}

function readSavedView() {
  try {
    return JSON.parse(localStorage.getItem(VIEW_KEY) || 'null');
  } catch (e) { return null; }
}

function clearSavedView() {
  try { localStorage.removeItem(VIEW_KEY); } catch (e) { /* ignore */ }
}

async function postJson(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json();
}

// On load, re-apply the remembered split and/or filter when the server has none
// (e.g. after a restart). Direct fetches only — never re-enters loadConfig.
async function maybeRestoreView(cfg) {
  if (!cfg.data_yaml) return cfg;
  const saved = readSavedView();
  if (!saved || saved.dataYaml !== cfg.data_yaml) {
    clearSavedView();
    return cfg;
  }
  // Only restore a remembered split when the server has none (a restart). If the
  // server already has one it is authoritative — e.g. `resumeLastImage` switched
  // to the last image's split, or the user picked one — so never override it,
  // especially not with null ("All splits"), which would fight `resumeLastImage`
  // in an endless switch/restore loop.
  const wantedSplit = saved.split || null;
  if (wantedSplit && !cfg.active_split) {
    const valid = (cfg.splits || []).some((s) => s.name === wantedSplit);
    if (valid) {
      const data = await postJson('/api/split', { split: wantedSplit });
      if (data.ok) cfg = data;
    }
  }
  const wanted = Array.isArray(saved.filters) ? saved.filters
    : (saved.filter ? [saved.filter] : []);
  const valid = wanted.filter((f) => (cfg.filters || []).includes(f));
  if (!cfg.active_filters.length && valid.length) {
    const data = await postJson('/api/filter', { filters: valid });
    if (data.ok) return data;
    clearSavedView();
  }
  return cfg;
}

function showTransientFilterMessage(msg) {
  if (showTransientFilterMessage._last === msg) return; // don't re-toast on reload
  showTransientFilterMessage._last = msg;
  toast(msg, { type: 'error' });
}

function loadImage(i) {
  i = Math.max(0, Math.min(images.length - 1, i));
  currentIndex = i;
  const requested = i; // this image may be replaced before the fetches resolve
  selected = -1;
  justDrawn = false;
  dirty = false;
  clearTimeout(autoSaveTimer); // a stale auto-save must not fire on the new image
  autoSaveTimer = null;
  updateNav();
  updateHistoryButtons();
  const entry = images[currentIndex];
  dbg('loadImage', { index: currentIndex, of: images.length,
    image: entry ? `${entry.split}/${entry.name}` : null });

  const q = keyQuery(entry);
  Promise.all([
    fetch('/api/labels' + q).then((r) => (r.ok ? r.json() : null)),
    fetch('/api/tags' + q).then((r) => (r.ok ? r.json() : null)),
  ]).then(([labelData, tagData]) => {
    if (requested !== currentIndex) return; // a newer loadImage superseded us
    boxes = Array.isArray(labelData) ? labelData : [];
    imageTags = (tagData && tagData.tags) || [];
    imageEl.src = '/api/image' + q + '&_=' + Date.now();
    rememberLastImage();
    renderTagBar();
    dbg('loadImage resolved', { index: currentIndex, boxes: boxes.length,
      tags: imageTags.length, src: imageEl.src });
    runHook('on_image_loaded');
  }).catch((err) => {
    // e.g. the key is no longer in the server list (a stale tab): blank it
    // rather than surfacing an unhandled rejection, and let the image onerror
    // clear the canvas.
    dbgWarn('loadImage failed', { image: imageKey(entry), error: String(err) });
  });
}

// Remember the current image so the app can resume here on reload. One entry
// per split is kept, plus a global `last`, so switching back to a split returns
// to the image you were on there.
function rememberLastImage() {
  if (currentIndex < 0 || !images[currentIndex]) return;
  const entry = images[currentIndex];
  let mem = readLastImage();
  if (!mem || mem.dataYaml !== currentDataYaml) {
    mem = { dataYaml: currentDataYaml, bySplit: {}, last: null };
  }
  if (!mem.bySplit || typeof mem.bySplit !== 'object') mem.bySplit = {};
  mem.bySplit[entry.split] = entry.name;
  mem.last = { split: entry.split, name: entry.name };
  try {
    localStorage.setItem(LAST_IMAGE_KEY, JSON.stringify(mem));
  } catch (e) { /* storage unavailable; just don't resume */ }
}

function readLastImage() {
  try {
    const raw = localStorage.getItem(LAST_IMAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (e) { return null; }
}

// A stable identity for an image, independent of its position in the list
// (indices shift whenever the list is rescanned or a filter is re-applied).
function imageKey(entry) {
  return entry ? `${entry.split}/${entry.name}` : null;
}

// Identity query for an image, e.g. `?key=val%2F0014122.jpg`. All per-image
// requests use this instead of an index: the list can be rebuilt (rescan,
// filter) so an index may point at a different file than the one on screen.
function keyQuery(entry) {
  return '?key=' + encodeURIComponent(imageKey(entry));
}

// Snapshot where the user is *by path* before the image list is rebuilt: the
// current image, plus (when `follow`) the ones that followed it. This is
// filter/order agnostic, so a user without any filter keeps the plain "same
// image / next image" behaviour.
function captureImageAnchor(follow = true) {
  if (currentIndex < 0 || !images[currentIndex]) return null;
  return {
    path: imageKey(images[currentIndex]),
    following: follow ? images.slice(currentIndex + 1).map(imageKey) : [],
    follow,
  };
}

// Find the image to show after the list was rebuilt: the same image by path;
// else, when the anchor asked to `follow`, the first still-present image that
// came after it (a removed/archived image thus shows its successor); else the
// first image.
function resolveImageAnchor(anchor) {
  if (!images.length) return -1;
  if (anchor && anchor.path) {
    const same = images.findIndex((im) => imageKey(im) === anchor.path);
    if (same >= 0) return same;
  }
  if (anchor && anchor.follow && anchor.following && anchor.following.length) {
    const present = new Set(images.map(imageKey));
    for (const p of anchor.following) {
      if (present.has(p)) return images.findIndex((im) => imageKey(im) === p);
    }
  }
  // a follow anchor with nothing left after it stays near the old position
  // (e.g. archiving the last image shows the new last one); otherwise start over
  return anchor && anchor.follow
    ? Math.max(0, Math.min(currentIndex, images.length - 1))
    : 0;
}

// Resume the image last reached: for the active split when one is set, else the
// global last image. `bySplit` is the new per-split memory; the old single-split
// shape (`{split, name}`) is still understood.
async function resumeLastImage(cfg) {
  const mem = readLastImage();
  if (!mem || mem.dataYaml !== cfg.data_yaml || !images.length) {
    loadImage(0);
    return;
  }
  const bySplit = mem.bySplit || (mem.split ? { [mem.split]: mem.name } : {});
  const split = cfg.active_split || (mem.last && mem.last.split) || mem.split || null;
  const name = cfg.active_split
    ? bySplit[cfg.active_split]
    : (mem.last ? mem.last.name : mem.name);
  if (name) {
    const idx = images.findIndex((im) => im.name === name && (!split || im.split === split));
    if (idx >= 0) { loadImage(idx); return; }
  }
  loadImage(0);
}

async function go(delta) {
  if (currentIndex < 0) return;
  const next = currentIndex + delta;
  if (next < 0 || next >= images.length) { dbg('go blocked', { delta, next, of: images.length }); return; }
  dbg('go', { delta, from: currentIndex, to: next, dirty });
  if (dirty) {
    if (autoSave) {
      if (!(await flushAutoSave())) return; // stay put if the save failed
    } else if (!confirm('You have unsaved changes. Discard them?')) {
      return;
    }
  }
  // navigation hooks run on the image being left; they capture its index before
  // loadImage advances currentIndex
  runHook(delta < 0 ? 'on_prev' : 'on_next');
  loadImage(next);
}

// ------------------------------------------------------------------------- //
// tagging (per-image tag bar)
// ------------------------------------------------------------------------- //
function setTagStatus(msg, type = 'info') {
  toast(msg, { type, timeout: type === 'error' ? undefined : 2500 });
}

function tagBadge(name, active, num) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'tag-badge' + (active ? ' active' : '');
  if (num) {
    const n = document.createElement('span');
    n.className = 'tag-badge-num';
    n.textContent = String(num);
    b.appendChild(n);
  }
  b.appendChild(document.createTextNode(name));
  b.title = active
    ? `Remove tag "${name}" from this image${num ? ` (Alt+${num})` : ''}`
    : `Add tag "${name}" to this image${num ? ` (Alt+${num})` : ''}`;
  b.addEventListener('click', () => {
    if (readonly || currentIndex < 0) return;
    if (active) removeTag(name);
    else addTag(name);
  });
  return b;
}

// Show the (…) button when the tag badges are wider than the row. Expanding
// lets them wrap onto more lines (the bottom row grows on demand).
function applyTagOverflow() {
  const bar = el('tagBar');
  const badges = el('tagBadges');
  const btn = el('tagExpandBtn');
  if (!bar || !badges || !btn || bar.classList.contains('hidden')) return;
  if (bar.classList.contains('expanded')) {
    btn.classList.remove('hidden');
    return;
  }
  const overflow = badges.scrollWidth > badges.clientWidth + 1;
  btn.classList.toggle('hidden', !overflow);
}

function renderTagBar() {
  const bar = el('tagBar');
  const show = getWidgetVisible('tags') && datasetLoaded && currentIndex >= 0;
  bar.classList.toggle('hidden', !show);
  if (getDock('tags') !== 'default') el('tagFloat').classList.toggle('hidden', !show);
  if (!show) {
    bar.classList.remove('expanded');
    el('tagExpandBtn').classList.add('hidden');
    updateDockPanels();
    return;
  }

  const wrap = el('tagBadges');
  wrap.innerHTML = '';
  const on = new Set(imageTags);
  const shown = new Set();
  availableTags.forEach((t, i) => {
    if (shown.has(t)) return;
    shown.add(t);
    wrap.appendChild(tagBadge(t, on.has(t), i + 1));
  });
  imageTags.forEach((t) => {
    if (shown.has(t)) return; // orphan image tag not in tags.yaml
    shown.add(t);
    wrap.appendChild(tagBadge(t, true, null));
  });

  el('tagInput').disabled = readonly;
  el('tagSubmitBtn').disabled = readonly;
  el('addTagBtn').disabled = readonly;
  el('tagHint').classList.toggle('hidden', availableTags.length === 0);

  // Explain why a tag on the image is not a normal (defined) badge: either
  // there is no tags.yaml at all, or the tag is new and only reaches tags.yaml
  // on the next save (the update_tags action).
  const warn = el('tagWarn');
  const fresh = imageTags.filter((t) => !availableTags.includes(t));
  let warnMsg = '';
  if (!availableTags.length) {
    warnMsg = 'No tags.yaml found beside data.yaml — add tags with +';
  } else if (fresh.length) {
    warnMsg = readonly
      ? `${fresh.length} tag(s) not in tags.yaml`
      : `${fresh.length} tag(s) not in tags.yaml — added on save`;
  }
  warn.textContent = warnMsg;
  warn.classList.toggle('hidden', !warnMsg);

  const dl = el('tagSuggestions');
  dl.innerHTML = '';
  availableTags.forEach((t) => {
    const opt = document.createElement('option');
    opt.value = t;
    dl.appendChild(opt);
  });

  // measure after the badges are laid out
  requestAnimationFrame(applyTagOverflow);
  updateDockPanels();
}

async function saveImageTags() {
  if (currentIndex < 0) return;
  try {
    const res = await fetch('/api/tags' + keyQuery(images[currentIndex]), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tags: imageTags }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      dbg('tags saved', { index: currentIndex, count: data.count, tags: imageTags });
      setTagStatus(`Saved ${data.count} tag(s)`);
    } else {
      dbgWarn('tag save failed', { status: res.status, error: data.error });
      setTagStatus('Tag save failed: ' + (data.error || res.status), 'error');
    }
  } catch (err) {
    dbgWarn('tag save error', err);
    setTagStatus('Tag save failed: ' + err.message, 'error');
  }
  renderTagBar();
}

// Built-in app action `app_update_tags`: write the current image's tag file
// and, only when the image carries a tag not yet in tags.yaml, append the new
// names to tags.yaml (no rewrite when there is nothing new). The shipped
// on_after_save hook calls it as `action_update_tags` after every save.
async function updateTagsForImage() {
  if (readonly || currentIndex < 0) return;
  await saveImageTags(); // persist the image's tag file
  const fresh = imageTags.filter((t) => !availableTags.includes(t));
  if (!fresh.length) {
    dbg('update_tags: no new tags, tags.yaml untouched');
    renderTagBar();
    return;
  }
  const next = [...availableTags, ...fresh];
  try {
    const res = await fetch('/api/tags.yaml', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tags: next }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      availableTags = data.tags || next;
      dbg('update_tags: added to tags.yaml', fresh);
    } else {
      dbgWarn('update_tags: tags.yaml update failed', { status: res.status, error: data.error });
    }
  } catch (err) {
    dbgWarn('update_tags: tags.yaml update error', err);
  }
  renderTagBar();
}

// Add a tag to the current image only. A brand-new name reaches tags.yaml on
// the next save, via the built-in update_tags action (see updateTagsForImage).
async function addTag(name) {
  if (readonly || currentIndex < 0) return;
  if (imageTags.includes(name)) return;
  imageTags = [...imageTags, name];
  await saveImageTags();
  setTagStatus(`Tag "${name}" added`);
}

async function removeTag(name) {
  if (readonly || currentIndex < 0) return;
  imageTags = imageTags.filter((t) => t !== name);
  await saveImageTags();
  setTagStatus(`Tag "${name}" removed`);
}

function openTagInput() {
  if (readonly) return;
  el('tagInput').classList.remove('hidden');
  el('tagSubmitBtn').classList.remove('hidden');
  el('tagInput').focus();
}

function closeTagInput() {
  el('tagInput').classList.add('hidden');
  el('tagSubmitBtn').classList.add('hidden');
}

function addTagFromInput() {
  if (readonly || currentIndex < 0) return;
  const input = el('tagInput');
  const name = input.value.trim();
  if (!name) return;
  input.value = '';
  if (imageTags.includes(name)) {
    setTagStatus(`Tag "${name}" is already on this image`);
    return;
  }
  addTag(name);
}

function toggleTagByNumber(n) {
  if (readonly || currentIndex < 0) return;
  const i = n - 1;
  if (i < 0 || i >= availableTags.length) return;
  if (!getWidgetVisible('tags')) setWidgetVisible('tags', true);
  const name = availableTags[i];
  if (imageTags.includes(name)) removeTag(name);
  else addTag(name);
}

// ------------------------------------------------------------------------- //
// actions
// ------------------------------------------------------------------------- //
function snapshot() {
  return boxes.map((b) => ({ ...b }));
}

function updateHistoryButtons() {
  const undo = el('undoBtn');
  const redo = el('redoBtn');
  const save = el('saveBtn');
  if (undo) undo.disabled = readonly || !undoStack.length;
  if (redo) redo.disabled = readonly || !redoStack.length;
  if (save) save.disabled = readonly || !dirty || currentIndex < 0;
}

function pushUndo() {
  undoStack.push(snapshot());
  if (undoStack.length > 100) undoStack.shift();
  redoStack = [];
  updateHistoryButtons();
}

function undo() {
  if (readonly || !undoStack.length) return;
  redoStack.push(snapshot());
  boxes = undoStack.pop();
  selected = -1;
  justDrawn = false;
  markDirty();
  syncClassSelect(-1);
  updateHistoryButtons();
  dbg('undo', { boxes: boxes.length, undo: undoStack.length, redo: redoStack.length });
  draw();
}

function redo() {
  if (readonly || !redoStack.length) return;
  undoStack.push(snapshot());
  boxes = redoStack.pop();
  selected = -1;
  justDrawn = false;
  markDirty();
  syncClassSelect(-1);
  updateHistoryButtons();
  dbg('redo', { boxes: boxes.length, undo: undoStack.length, redo: redoStack.length });
  draw();
}

function deleteSelected() {
  if (selected >= 0) {
    pushUndo();
    dbg('box deleted', { index: selected, box: boxes[selected], remaining: boxes.length - 1 });
    boxes.splice(selected, 1);
    selected = -1;
    justDrawn = false;
    markDirty();
    draw();
    updateHistoryButtons();
    runHook('on_box_deleted');
  }
}

// Fix / unfix the selected box. A fixed box ignores dragging (moving and
// resizing) but can still be clicked / selected and deleted. The flag is
// transient UI state: it is never saved and is cleared when the image changes.
function toggleFixSelected() {
  if (readonly || selected < 0) return;
  boxes[selected].fixed = !boxes[selected].fixed;
  draw();
  updateSidePanelState();
}

// Mark the labels as changed and, when auto-save is on, queue a save.
function markDirty() {
  dirty = true;
  scheduleAutoSave();
}

function scheduleAutoSave() {
  if (!autoSave || readonly || currentIndex < 0) return;
  clearTimeout(autoSaveTimer);
  autoSaveTimer = setTimeout(() => { autoSaveTimer = null; save({ silent: true }); }, AUTO_SAVE_DELAY);
}

// Save any pending auto-save now (used before navigating away).
async function flushAutoSave() {
  if (autoSaveTimer) {
    clearTimeout(autoSaveTimer);
    autoSaveTimer = null;
  }
  if (!dirty || readonly) return true;
  return save({ silent: true });
}

// Returns true on success, false when the write failed or a hook cancelled it.
// `silent` suppresses the success toast (used by auto-save); failures always show.
async function save(opts = {}) {
  if (currentIndex < 0) return false;
  // a failing before_save hook cancels the write
  dbg('save requested', { index: currentIndex, boxes: boxes.length });
  if (!(await runHook('on_before_save'))) {
    dbgWarn('save aborted by on_before_save hook');
    toast('Save aborted by on_before_save', { type: 'error' });
    return false;
  }
  let ok = false;
  try {
    const res = await fetch('/api/labels' + keyQuery(images[currentIndex]), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ boxes }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      dirty = false;
      ok = true;
      dbg('save ok', { index: currentIndex, count: data.count });
      if (!opts.silent) toast(`Saved ${data.count} box(es)`, { type: 'success' });
      updateHistoryButtons();
      runHook('on_after_save');
    } else {
      dbgWarn('save failed', { status: res.status, error: data.error });
      toast('Save failed: ' + (data.error || res.status), { type: 'error' });
    }
  } catch (err) {
    dbgWarn('save error', err);
    toast('Save failed: ' + err.message, { type: 'error' });
  }
  updateHistoryButtons();
  return ok;
}

async function loadDataset(rawPath) {
  const yamlPath = (rawPath || '').trim();
  if (!yamlPath) {
    toast('Enter the path to a data.yaml', { type: 'warning' });
    return;
  }
  try {
    const res = await fetch('/api/data', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data_yaml: yamlPath }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      dbg('dataset loaded', { path: yamlPath });
      await loadConfig();
      toast('Dataset loaded', { type: 'success' });
      closeSettingsModal();
      closeLoadDataModal();
    } else {
      dbgWarn('dataset load failed', { status: res.status, error: data.error });
      toast(data.error || 'Invalid data.yaml', { type: 'error' });
    }
  } catch (err) {
    dbgWarn('dataset load error', err);
    toast('Error: ' + err.message, { type: 'error' });
  }
}

function setDataYaml() {
  return loadDataset(el('dataYaml').value);
}

function loadDataFromModal() {
  return loadDataset(el('loadDataYaml').value);
}

async function setSplit(split) {
  try {
    const res = await fetch('/api/split', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ split: split || null }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      dbg('split changed', { split: split || null });
      // skip the view restore: the split just set is authoritative, otherwise a
      // stale remembered split would immediately switch it back (e.g. choosing
      // "All splits" after a specific one). Resume the per-split last image.
      await loadConfig(0, { skipFilterRestore: true });
    } else {
      dbgWarn('split switch failed', { status: res.status, error: data.error });
      toast(data.error || 'Split switch failed', { type: 'error' });
    }
  } catch (err) {
    dbgWarn('split switch error', err);
    toast('Error: ' + err.message, { type: 'error' });
  }
}

// Set the per-dataset tags folder (empty restores the images -> tags default).
async function setTagsDir() {
  const anchor = captureImageAnchor(false);
  try {
    const res = await fetch('/api/tags-dir', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tags_dir: el('tagsDirInput').value.trim() }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      dbg('tags dir changed', { tags_dir: data.tags_dir });
      toast('Tags folder updated', { type: 'success' });
      await loadConfig(0, { noResume: true, anchor });
    } else {
      dbgWarn('tags dir update failed', { status: res.status, error: data.error });
      toast(data.error || 'Tags folder update failed', { type: 'error' });
    }
  } catch (err) {
    dbgWarn('tags dir update error', err);
    toast('Error: ' + err.message, { type: 'error' });
  }
}

async function applyFilterChain(names) {
  const anchor = captureImageAnchor(false);
  try {
    const res = await fetch('/api/filter', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filters: names || [] }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      dbg('filters changed', { filters: names || [],
        images: (data.images || []).length, filter_error: data.filter_error });
      await loadConfig(0, { noResume: true, skipFilterRestore: true, anchor });
    } else {
      dbgWarn('filter failed', { status: res.status, error: data.error });
      toast(data.error || 'Filter failed', { type: 'error' });
      populateFilterPanel(); // revert the panel to the active chain
    }
  } catch (err) {
    dbgWarn('filter error', err);
    toast('Error: ' + err.message, { type: 'error' });
    populateFilterPanel();
  }
}

// ------------------------------------------------------------------------- //
// user actions (actions.yaml)
// ------------------------------------------------------------------------- //
function setResultText(id, text, emptyClass) {
  const node = el(id);
  node.textContent = text || '';
  node.classList.toggle('modal-empty', !text);
}

function showActionResult(data) {
  const ok = !!data.ok;
  const title = `${data.action || 'Action'} — ${ok ? 'succeeded' : 'failed'}`;
  el('actionResultTitle').textContent = title;
  el('actionResultTitle').style.color = ok ? 'var(--green)' : 'var(--red)';
  setResultText('actionResultCmd', data.command ? `$ ${data.command}` : (data.error || ''));
  setResultText('actionResultExit', `exit code: ${data.exit_code}`.trim(), true);
  setResultText('actionResultOut', data.stdout);
  setResultText('actionResultErr', data.stderr);
  el('actionResult').classList.remove('hidden');
}

function closeActionResult() {
  el('actionResult').classList.add('hidden');
}

// Event hooks report success as a transient toast; failures still use the modal.
function setHookStatus(msg) {
  toast(msg, { type: 'success', timeout: 3000 });
}

// Run one user action (or event hook) on the current image. `confirm: false`
// skips the confirmation prompt — hooks run automatically. The backend owns the
// steps + after_success chain and pauses whenever an app action is needed: it
// returns `client_action` + a `uid`, which we run and report back. Returns true
// when the whole run succeeded (or there was nothing to run), false on failure.
async function runAction(name, opts = {}) {
  const ask = opts.confirm !== false;
  const isHook = !!opts.hook;
  if (!name || currentIndex < 0 || !images[currentIndex]) {
    dbg('runAction skipped', { name, currentIndex });
    return false;
  }
  const target = `${images[currentIndex].split}/${images[currentIndex].name}`;
  if (ask && !confirm(`Run action "${name}" on ${target}?`)) return false;
  setActionButtonsDisabled(true);
  dbg(`run ${isHook ? 'hook' : 'action'} "${name}"`, { target, index: currentIndex });
  try {
    let data = await postActionRun({ action: name, target });
    // The server-side chain pauses at each client action (app_*): run it here,
    // then resume the server with the same uid.
    while (data.ok && data.client_action) {
      dbg('run after_success client action', data.client_action, { uid: data.uid });
      let result;
      try {
        await runAppAction(data.client_action);
        result = { ok: true };
      } catch (err) {
        result = { ok: false, error: err.message };
      }
      data = await postActionRun({ uid: data.uid, result });
    }
    dbg(`"${name}" response`, data);
    if (!data.ok) {
      // failures always use the modal
      showActionResult(data);
      console.error(`[user action] "${name}" failed:`, {
        exit_code: data.exit_code,
        command: data.command,
      });
      return false;
    }
    if (isHook) setHookStatus(`${name} succeeded`);
    else showActionResult(data);
    return true;
  } catch (err) {
    dbgWarn(`"${name}" request error`, err);
    showActionResult({ ok: false, action: name, error: 'Error: ' + err.message });
    return false;
  } finally {
    setActionButtonsDisabled(readonly);
  }
}

async function postActionRun(body) {
  const res = await fetch('/api/actions/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json();
}

// Fire an event hook if it is defined and an image is loaded. No-op otherwise.
// The in-flight guard keeps a hook from re-entering itself (e.g. a hook whose
// after_success refreshes the image list, which would fire it again).
async function runHook(name) {
  if (!hooksByName.has(name) || currentIndex < 0) return true;
  if (hookInFlight.has(name)) { dbg(`hook ${name} skipped (already running)`); return true; }
  hookInFlight.add(name);
  dbg(`hook ${name} fired`);
  try {
    return await runAction(name, { confirm: false, hook: true });
  } finally {
    hookInFlight.delete(name);
  }
}

// ------------------------------------------------------------------------- //
// class picker (shown after drawing a new box)
// ------------------------------------------------------------------------- //
const classPicker = el('classPicker');

function openClassPicker(x, y) {
  classPicker.innerHTML = '';
  const title = document.createElement('div');
  title.className = 'picker-title';
  title.textContent = 'Choose class';
  classPicker.appendChild(title);

  classes.forEach((name, i) => {
    const btn = document.createElement('button');
    btn.textContent = `${i}: ${name}`;
    btn.addEventListener('click', () => {
      if (selected >= 0) {
        const wasJustDrawn = justDrawn;
        boxes[selected].class = i;
        justDrawn = false;
        markDirty();
        syncClassSelect(selected);
        draw();
        // choosing the class of a just-drawn box completes the creation, it is
        // not a separate edit
        if (!wasJustDrawn) runHook('on_box_edited');
      }
      closeClassPicker();
    });
    classPicker.appendChild(btn);
  });

  classPicker.classList.remove('hidden');
  const w = classPicker.offsetWidth;
  const h = classPicker.offsetHeight;
  const pad = 8;
  let px = x + 12;
  let py = y + 12;
  if (px + w > window.innerWidth) px = x - w - 12;
  if (py + h > window.innerHeight) py = y - h - 12;
  classPicker.style.left = Math.max(pad, px) + 'px';
  classPicker.style.top = Math.max(pad, py) + 'px';
}

function openPickerForSelectedBox() {
  if (selected < 0) return;
  const r = toPx(boxes[selected]);
  const rect = canvas.getBoundingClientRect();
  const sx = rect.left + (r.x + r.w / 2) * (rect.width / canvas.width);
  const sy = rect.top + (r.y + r.h / 2) * (rect.height / canvas.height);
  openClassPicker(sx, sy);
}

function closeClassPicker() {
  classPicker.classList.add('hidden');
}

// ------------------------------------------------------------------------- //
// left sidebar: resizable, collapsible body (the header row stays visible)
// ------------------------------------------------------------------------- //
let sidePanelOpen = true;

function fmtNum(v) {
  return Math.round(v * 10000) / 10000;
}

const SIDEBAR_MIN = 220;
const SIDEBAR_MAX = 720;
const SIDEBAR_W_KEY = 'ybe_side_panel_w';

function applySidePanelWidth(w) {
  const clamped = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, Math.round(w)));
  el('sidebar').style.setProperty('--sidebar-w', clamped + 'px');
  return clamped;
}

function initSidePanelResizer() {
  const handle = el('sidebarResizer');
  if (!handle) return;
  let dragging = false;
  let pending = null;
  const onMove = (e) => {
    if (!dragging) return;
    e.preventDefault();
    const rect = el('sidebar').getBoundingClientRect();
    pending = panelSide === 'left'
      ? applySidePanelWidth(e.clientX - rect.left)
      : applySidePanelWidth(rect.right - e.clientX);
  };
  const onUp = () => {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove('active');
    document.body.style.cursor = '';
    if (pending !== null) settingsSet(SIDEBAR_W_KEY, pending);
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
  };
  handle.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    dragging = true;
    handle.classList.add('active');
    try { handle.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
    document.body.style.cursor = 'col-resize';
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  });
}

function initSidePanel() {
  sidePanelOpen = settingsGet('sidePanelOpen') !== '0';
  toggleSidePanel(sidePanelOpen, false);
  const saved = parseInt(settingsGet(SIDEBAR_W_KEY) || '', 10);
  if (saved) applySidePanelWidth(saved);
  el('sidePanelToggle').addEventListener('click', () => toggleSidePanel());
  initSidePanelResizer();
}

function toggleSidePanel(show, persist = true) {
  const open = show !== undefined ? !!show : !sidePanelOpen;
  sidePanelOpen = open;
  el('sidebar').classList.toggle('collapsed', !open);
  el('sidePanelToggle').classList.toggle('active', open);
  if (persist) settingsSet('sidePanelOpen', open ? '1' : '0');
}

// ------------------------------------------------------------------------- //
// appearance: control panel side + dockable Tags / Boxes widgets
//
// Widgets (Tags, Boxes) live in one of: their default spot, a floating window,
// the left panel, the right panel or the bottom panel. A side location that
// matches the control panel merges into it (stacked); otherwise it uses the
// widget-only panel on the opposite side, which appears only while it has a
// visible child.
// ------------------------------------------------------------------------- //
const PANEL_SIDE_KEY = 'ybe_panel_side';
const DOCK_SIDE_W_KEY = 'ybe_dock_side_w';
const DOCK_BOTTOM_H_KEY = 'ybe_dock_bottom_h';
const LEGACY_TAGGING_KEY = 'taggingEnabled';
const LEGACY_DETACH_TAGS_KEY = 'ybe_detach_tags';
const LEGACY_DETACH_BOXES_KEY = 'ybe_detach_boxes';
const FLOAT_MARGIN = 8;
const DOCK_SIDE_MIN = 200;
const DOCK_SIDE_MAX = 720;
const DOCK_BOTTOM_MIN = 100;
const DOCK_LOCATIONS = ['default', 'float', 'left', 'right', 'bottom'];

let panelSide = 'right';

// The dockable widgets. `default` puts the content back where it lives in the
// markup; the other locations are the floating window or an edge panel.
const WIDGETS = {
  tags: {
    frame: 'tagFloat', body: 'tagFloatBody',
    content: () => el('tagBar'),
    parent: () => document.querySelector('#dockBottom .imagebar'),
    key: 'ybe_tags_dock', select: 'tagsDockSel',
    visibleKey: 'ybe_tags_visible', visibleSw: 'tagsVisibleSw',
  },
  boxes: {
    frame: 'boxFloat', body: 'boxFloatBody',
    content: () => document.querySelector('.boxes-section'),
    parent: () => document.querySelector('#sidebar .sidebar-body'),
    key: 'ybe_boxes_dock', select: 'boxesDockSel',
    visibleKey: 'ybe_boxes_visible', visibleSw: 'boxesVisibleSw',
  },
  actions: {
    frame: 'actionsFloat', body: 'actionsFloatBody',
    content: () => document.querySelector('.actionbox'),
    parent: () => document.querySelector('#sidebar .sidebar-body'),
    anchor: () => el('actionsSep'),
    key: 'ybe_actions_dock', select: 'actionsDockSel',
    visibleKey: 'ybe_actions_visible', visibleSw: 'actionsVisibleSw',
  },
  nav: {
    frame: 'navFloat', body: 'navFloatBody',
    content: () => document.querySelector('.imagebar-nav'),
    parent: () => document.querySelector('#dockBottom .imagebar'),
    key: 'ybe_nav_dock', select: 'navDockSel',
    visibleKey: 'ybe_nav_visible', visibleSw: 'navVisibleSw',
  },
  save: {
    frame: 'saveFloat', body: 'saveFloatBody',
    content: () => document.querySelector('.imagebar-right'),
    parent: () => document.querySelector('#dockBottom .imagebar'),
    key: 'ybe_save_dock', select: 'saveDockSel',
    visibleKey: 'ybe_save_visible', visibleSw: 'saveVisibleSw',
  },
};

const dockState = {};
const visibleState = {};
Object.keys(WIDGETS).forEach((name) => {
  dockState[name] = 'default';
  visibleState[name] = true;
});

function applyPanelSide() {
  document.body.classList.toggle('panel-left', panelSide === 'left');
}

function floatKey(id) { return 'ybe_float_' + id; }

function clampFloatPos(win, x, y) {
  const w = win.offsetWidth || 260;
  const h = win.offsetHeight || 120;
  const maxX = Math.max(FLOAT_MARGIN, window.innerWidth - w - FLOAT_MARGIN);
  const maxY = Math.max(FLOAT_MARGIN, window.innerHeight - h - FLOAT_MARGIN);
  return {
    x: Math.min(maxX, Math.max(FLOAT_MARGIN, x)),
    y: Math.min(maxY, Math.max(FLOAT_MARGIN, y)),
  };
}

function setFloatPos(win, x, y) {
  const p = clampFloatPos(win, x, y);
  win.style.left = p.x + 'px';
  win.style.top = p.y + 'px';
  return p;
}

function saveFloatPos(win) {
  settingsSet(floatKey(win.id), JSON.stringify({
    x: win.offsetLeft, y: win.offsetTop,
  }));
}

function defaultFloatPos(win) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  if (win.id === 'boxFloat') return { x: Math.max(20, vw - 340), y: 90 };
  // stagger the bottom-left windows so several do not open on top of each other
  const order = ['tagFloat', 'navFloat', 'saveFloat', 'actionsFloat'];
  const i = Math.max(0, order.indexOf(win.id));
  return { x: 24 + i * 28, y: Math.max(20, vh - 260 - i * 28) };
}

function restoreFloatPos(win) {
  let pos = null;
  try { pos = JSON.parse(settingsGet(floatKey(win.id)) || 'null'); } catch (e) { /* ignore */ }
  if (pos && typeof pos.x === 'number' && typeof pos.y === 'number') {
    setFloatPos(win, pos.x, pos.y);
  } else {
    const d = defaultFloatPos(win);
    setFloatPos(win, d.x, d.y);
  }
}

// ---- widget <-> DOM helpers ---------------------------------------------- //
function widgetNames() { return Object.keys(WIDGETS); }
function widgetNameForFrame(win) {
  if (!win) return 'tags';
  return widgetNames().find((n) => WIDGETS[n].frame === win.id) || 'tags';
}
function dockKey(name) { return WIDGETS[name].key; }
function dockSelectId(name) { return WIDGETS[name].select; }
function getDock(name) { return dockState[name] || 'default'; }
function setDockState(name, loc) { dockState[name] = loc; }
function widgetFrame(name) { return el(WIDGETS[name].frame); }
function widgetFrameBody(name) { return el(WIDGETS[name].body); }
function widgetContent(name) { return WIDGETS[name].content(); }
function widgetDefaultParent(name) { return WIDGETS[name].parent(); }
function widgetDockTarget(name, loc) {
  if (loc === 'bottom') return el('dockBottomBody');
  if (loc === panelSide) return document.querySelector('#sidebar .sidebar-body');
  return el('dockSideBody');
}

// A panel exists only while it holds a visible child.
function updateDockPanels() {
  const hasChild = (node) => !!node
    && Array.from(node.children).some((c) => !c.classList.contains('hidden'));
  const panel = el('dockSide');
  const body = el('dockSideBody');
  if (panel && body) panel.classList.toggle('hidden', !hasChild(body));

  const bottomBody = el('dockBottomBody');
  if (bottomBody) bottomBody.classList.toggle('empty', !hasChild(bottomBody));

  // the bottom panel itself disappears once nothing is left in it
  const bottom = el('dockBottom');
  const imagebar = document.querySelector('#dockBottom .imagebar');
  if (bottom) bottom.classList.toggle('hidden', !hasChild(bottomBody) && !hasChild(imagebar));
}

function placeWidget(name, loc) {
  const frame = widgetFrame(name);
  const body = widgetFrameBody(name);
  const content = widgetContent(name);
  if (!frame || !body || !content) return;

  if (loc === 'float') {
    if (content.parentElement !== body) body.appendChild(content);
    if (frame.parentElement !== document.body) document.body.appendChild(frame);
    frame.style.left = '';
    frame.style.top = '';
    frame.style.width = '';
    frame.style.height = '';
    frame.classList.remove('hidden');
    restoreFloatPos(frame);
  } else if (loc === 'default') {
    const parent = widgetDefaultParent(name);
    const anchor = WIDGETS[name].anchor ? WIDGETS[name].anchor() : null;
    if (parent && content.parentElement !== parent) {
      if (anchor && anchor.parentElement === parent) parent.insertBefore(content, anchor);
      else parent.appendChild(content);
    }
    frame.style.left = frame.style.top = '';
    frame.style.width = frame.style.height = '';
    frame.classList.add('hidden');
  } else {
    if (content.parentElement !== body) body.appendChild(content);
    const target = widgetDockTarget(name, loc);
    if (target && frame.parentElement !== target) target.appendChild(frame);
    frame.style.left = frame.style.top = '';
    frame.style.width = frame.style.height = '';
    frame.classList.remove('hidden');
  }
  updateDockPanels();
}

function getWidgetVisible(name) { return visibleState[name] !== false; }

function setWidgetVisible(name, on) {
  visibleState[name] = !!on;
  settingsSet(WIDGETS[name].visibleKey, on ? '1' : '0');
  const sw = el(WIDGETS[name].visibleSw);
  if (sw) sw.checked = !!on;
  applyWidget(name);
}

function applyWidget(name) {
  placeWidget(name, getDock(name));
  const on = getWidgetVisible(name);
  if (name === 'tags') {
    renderTagBar(); // tags only show with a dataset/image; it reads the flag
    return;
  }
  const frame = widgetFrame(name);
  const content = widgetContent(name);
  if (content) content.classList.toggle('hidden', !on);
  if (frame) frame.classList.toggle('hidden', !on || getDock(name) === 'default');
  updateDockPanels();
}

function applyAllWidgets() {
  widgetNames().forEach(applyWidget);
}

function setWidgetDock(name, loc) {
  if (!DOCK_LOCATIONS.includes(loc)) loc = 'default';
  // docking into the control panel while it is collapsed would hide the widget
  if ((loc === 'left' || loc === 'right') && loc === panelSide && !sidePanelOpen) {
    toggleSidePanel(true);
  }
  setDockState(name, loc);
  settingsSet(dockKey(name), loc);
  const sel = el(dockSelectId(name));
  if (sel) sel.value = loc;
  applyWidget(name);
}

// ---- panel resizers ------------------------------------------------------- //
function applyDockSideWidth(w) {
  const clamped = Math.min(DOCK_SIDE_MAX, Math.max(DOCK_SIDE_MIN, Math.round(w)));
  const panel = el('dockSide');
  if (panel) panel.style.setProperty('--dock-side-w', clamped + 'px');
  return clamped;
}

function applyDockBottomHeight(h) {
  const max = Math.max(DOCK_BOTTOM_MIN, window.innerHeight - 160);
  const clamped = Math.min(max, Math.max(DOCK_BOTTOM_MIN, Math.round(h)));
  const body = el('dockBottomBody');
  if (body) body.style.setProperty('--dock-bottom-h', clamped + 'px');
  return clamped;
}

function initDockResizers() {
  const side = el('dockSideResizer');
  if (side) {
    let dragging = false;
    let startX = 0;
    let startW = 0;
    const onMove = (e) => {
      if (!dragging) return;
      e.preventDefault();
      const delta = panelSide === 'left' ? startX - e.clientX : e.clientX - startX;
      applyDockSideWidth(startW + delta);
    };
    const onUp = () => {
      if (!dragging) return;
      dragging = false;
      side.classList.remove('active');
      document.body.style.cursor = '';
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      settingsSet(DOCK_SIDE_W_KEY, el('dockSide').offsetWidth);
    };
    side.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      dragging = true;
      startX = e.clientX;
      startW = el('dockSide').offsetWidth;
      side.classList.add('active');
      document.body.style.cursor = 'col-resize';
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp);
    });
  }

  const bottom = el('dockBottomResizer');
  if (bottom) {
    let dragging = false;
    let startY = 0;
    let startH = 0;
    const onMove = (e) => {
      if (!dragging) return;
      e.preventDefault();
      applyDockBottomHeight(startH + (startY - e.clientY));
    };
    const onUp = () => {
      if (!dragging) return;
      dragging = false;
      bottom.classList.remove('active');
      document.body.style.cursor = '';
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      settingsSet(DOCK_BOTTOM_H_KEY, el('dockBottomBody').offsetHeight);
    };
    bottom.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      dragging = true;
      startY = e.clientY;
      startH = el('dockBottomBody').offsetHeight || 200;
      bottom.classList.add('active');
      document.body.style.cursor = 'row-resize';
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp);
    });
  }
}

function initFloatWindow(win) {
  if (!win) return;
  const name = widgetNameForFrame(win);
  const head = win.querySelector('.float-head');
  let dragging = false;
  let grabX = 0;
  let grabY = 0;
  head.addEventListener('pointerdown', (e) => {
    if (e.target.closest('button')) return;
    if (getDock(name) !== 'float') return; // docked heads are not draggable
    dragging = true;
    grabX = e.clientX - win.offsetLeft;
    grabY = e.clientY - win.offsetTop;
    try { head.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
    win.classList.add('dragging');
    e.preventDefault();
  });
  head.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    setFloatPos(win, e.clientX - grabX, e.clientY - grabY);
  });
  const end = () => {
    if (!dragging) return;
    dragging = false;
    win.classList.remove('dragging');
    saveFloatPos(win);
  };
  head.addEventListener('pointerup', end);
  head.addEventListener('pointercancel', end);
  win.querySelectorAll('.float-dock').forEach((btn) => {
    btn.addEventListener('click', () => setWidgetDock(name, btn.dataset.dock));
  });
  const closeBtn = win.querySelector('.float-close');
  if (closeBtn) closeBtn.addEventListener('click', () => setWidgetDock(name, 'default'));
  window.addEventListener('resize', () => {
    if (getDock(name) === 'float') setFloatPos(win, win.offsetLeft, win.offsetTop);
  });
}

function setAppearanceControls() {
  el('panelSideSel').value = panelSide;
  widgetNames().forEach((name) => {
    const sel = el(dockSelectId(name));
    if (sel) sel.value = getDock(name);
    const sw = el(WIDGETS[name].visibleSw);
    if (sw) sw.checked = getWidgetVisible(name);
  });
}

function savedDock(key) {
  const raw = settingsGet(key);
  return DOCK_LOCATIONS.includes(raw) ? raw : 'default';
}

function savedVisible(key) {
  return settingsGet(key) !== '0';
}

function initAppearance() {
  panelSide = settingsGet(PANEL_SIDE_KEY) === 'left' ? 'left' : 'right';
  widgetNames().forEach((name) => {
    dockState[name] = savedDock(dockKey(name));
    visibleState[name] = savedVisible(WIDGETS[name].visibleKey);
  });
  // migrate the old "detach into a floating window" checkboxes
  const tagsKey = dockKey('tags');
  const boxesKey = dockKey('boxes');
  if (settingsGet(tagsKey) === null && localStorage.getItem(LEGACY_DETACH_TAGS_KEY) === '1') dockState.tags = 'float';
  if (settingsGet(boxesKey) === null && localStorage.getItem(LEGACY_DETACH_BOXES_KEY) === '1') dockState.boxes = 'float';
  // migrate the old View > Tags switch (now the Tags widget's Show toggle)
  if (settingsGet(WIDGETS.tags.visibleKey) === null
      && localStorage.getItem(LEGACY_TAGGING_KEY) !== null) {
    visibleState.tags = localStorage.getItem(LEGACY_TAGGING_KEY) !== '0';
  }
  try {
    localStorage.removeItem(LEGACY_DETACH_TAGS_KEY);
    localStorage.removeItem(LEGACY_DETACH_BOXES_KEY);
    localStorage.removeItem(LEGACY_TAGGING_KEY);
  } catch (e) { /* ignore */ }

  applyPanelSide();
  widgetNames().forEach((name) => initFloatWindow(widgetFrame(name)));
  initDockResizers();

  const sideW = parseInt(settingsGet(DOCK_SIDE_W_KEY) || '', 10);
  if (sideW) applyDockSideWidth(sideW);
  const bottomH = parseInt(settingsGet(DOCK_BOTTOM_H_KEY) || '', 10);
  if (bottomH) applyDockBottomHeight(bottomH);

  applyAllWidgets();
  setAppearanceControls();

  el('panelSideSel').addEventListener('change', () => {
    panelSide = el('panelSideSel').value === 'left' ? 'left' : 'right';
    settingsSet(PANEL_SIDE_KEY, panelSide);
    applyPanelSide();
    const saved = parseInt(settingsGet(SIDEBAR_W_KEY) || '', 10);
    if (saved) applySidePanelWidth(saved);
    // a widget's left/right location resolves against the new control side
    applyAllWidgets();
  });
  widgetNames().forEach((name) => {
    const sel = el(dockSelectId(name));
    if (sel) sel.addEventListener('change', () => setWidgetDock(name, sel.value));
    const sw = el(WIDGETS[name].visibleSw);
    if (sw) sw.addEventListener('change', () => setWidgetVisible(name, sw.checked));
  });
}

function selectFromPanel(i) {
  closeClassPicker();
  selected = i;
  justDrawn = false;
  syncClassSelect(i);
  draw();
}

function setFieldValue(f, val) {
  if (!f) return;
  if (document.activeElement !== f) f.value = val;
}

function makeRowControl(tag, cls, opts) {
  const c = document.createElement(tag);
  c.className = cls;
  if (tag === 'select') {
    classes.forEach((name, k) => {
      const opt = document.createElement('option');
      opt.value = k;
      opt.textContent = `${k}: ${name}`;
      c.appendChild(opt);
    });
  } else {
    c.type = 'number';
    c.step = '0.001';
    c.min = '0';
    c.max = '1';
    c.value = opts && opts.value !== undefined ? opts.value : '';
  }
  return c;
}

function renderSidePanel() {
  const list = el('boxList');
  if (!list) return;
  el('sidePanelCount').textContent = boxes.length;
  list.innerHTML = '';
  boxes.forEach((b, i) => {
    const id = `pb${i}`;
    const row = document.createElement('div');
    row.className = 'box-row';
    row.dataset.index = i;

    const idx = document.createElement('span');
    idx.className = 'box-row-idx';
    idx.textContent = i;

    const cls = makeRowControl('select', 'box-row-ctl box-row-class');
    cls.dataset.name = 'class';
    cls.value = String(b.class);

    const mkPoint = (name) => {
      const inp = makeRowControl('input', `box-row-ctl box-row-point box-row-${name}`, { value: String(fmtNum(b[name])) });
      inp.dataset.name = name;
      return inp;
    };
    const ptCx = mkPoint('cx');
    const ptCy = mkPoint('cy');
    const ptW = mkPoint('w');
    const ptH = mkPoint('h');

    const fix = document.createElement('button');
    fix.type = 'button';
    fix.className = 'box-row-ctl box-row-fix';
    fix.textContent = 'F';
    fix.title = 'Fix / unfix this box (F) — fixed boxes ignore dragging';

    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'box-row-ctl box-row-del danger';
    del.textContent = '\u00d7';
    del.title = 'Delete box';

    const top = document.createElement('div');
    top.className = 'box-row-top';
    top.append(idx, cls, fix, del);

    const bottom = document.createElement('div');
    bottom.className = 'box-row-bottom';
    bottom.append(ptCx, ptCy, ptW, ptH);

    row.append(top, bottom);

    row.addEventListener('click', (e) => {
      if (e.target.closest('select, input, button')) return;
      selectFromPanel(i);
    });
    cls.addEventListener('change', () => {
      if (readonly) return;
      pushUndo();
      boxes[i].class = parseInt(cls.value, 10);
      justDrawn = false;
      markDirty();
      draw();
      updateHistoryButtons();
      renderSidePanel();
      runHook('on_box_edited');
    });
    [ptCx, ptCy, ptW, ptH].forEach((inp) => {
      inp.addEventListener('input', () => {
        if (readonly || i !== selected) return;
        const val = parseFloat(inp.value);
        if (isNaN(val)) return;
        if (!inp.dataset.dirty) {
          pushUndo();
          inp.dataset.dirty = '1';
        }
        boxes[i][inp.dataset.name] = clamp01(val);
        justDrawn = false;
        dirty = true;
        draw();
        updateHistoryButtons();
      });
      inp.addEventListener('change', () => {
        const wasEdited = !!inp.dataset.dirty;
        delete inp.dataset.dirty;
        if (wasEdited) {
          scheduleAutoSave();
          runHook('on_box_edited');
        }
      });
      inp.addEventListener('focus', () => {
        editingPoint = { i: i, name: inp.dataset.name };
        draw();
      });
      inp.addEventListener('blur', () => {
        if (editingPoint && editingPoint.i === i) {
          editingPoint = null;
          draw();
        }
      });
    });
    fix.addEventListener('click', (e) => {
      e.stopPropagation();
      if (readonly) return;
      boxes[i].fixed = !boxes[i].fixed;
      draw();
      updateSidePanelState();
    });
    del.addEventListener('click', (e) => {
      e.stopPropagation();
      if (readonly) return;
      pushUndo();
      boxes.splice(i, 1);
      if (selected === i) {
        selected = -1;
        justDrawn = false;
      } else if (selected > i) {
        selected -= 1;
      }
      syncClassSelect(selected);
      markDirty();
      draw();
      updateHistoryButtons();
      renderSidePanel();
      runHook('on_box_deleted');
    });

    list.appendChild(row);
  });
  updateSidePanelState();
}

function updateSidePanelState() {
  const list = el('boxList');
  if (!list) return;
  el('sidePanelCount').textContent = boxes.length;
  list.querySelectorAll('.box-row').forEach((row, i) => {
    const b = boxes[i];
    if (!b) return;
    const on = i === selected && !readonly;
    row.classList.toggle('selected', i === selected);
    row.classList.toggle('fixed', !!b.fixed);
    row.querySelector('.box-row-idx').textContent = i;
    const fixBtn = row.querySelector('.box-row-fix');
    if (fixBtn) {
      fixBtn.classList.toggle('active', !!b.fixed);
      fixBtn.title = b.fixed ? 'Unfix this box (F)' : 'Fix this box (F)';
    }
    row.querySelectorAll('.box-row-ctl').forEach((ctl) => { ctl.disabled = !on; });
    setFieldValue(row.querySelector('.box-row-class'), String(b.class));
    setFieldValue(row.querySelector('.box-row-cx'), String(fmtNum(b.cx)));
    setFieldValue(row.querySelector('.box-row-cy'), String(fmtNum(b.cy)));
    setFieldValue(row.querySelector('.box-row-w'), String(fmtNum(b.w)));
    setFieldValue(row.querySelector('.box-row-h'), String(fmtNum(b.h)));
  });
}

function syncSidePanel() {
  const list = el('boxList');
  if (!list) return;
  if (list.children.length !== boxes.length) {
    renderSidePanel();
    return;
  }
  updateSidePanelState();
}

// ------------------------------------------------------------------------- //
// events
// ------------------------------------------------------------------------- //
canvas.addEventListener('mousedown', (e) => {
  closeClassPicker();
  if (!imgW || !imgH || readonly) return;
  const p = canvasPos(e);
  mouse = p;

  // modifier held (app_force_draw): always start a new box, whatever is under
  // the cursor — lets you draw inside / on top of an existing box.
  if (forceDrawActive(e)) {
    mode = 'drawing';
    selected = -1;
    justDrawn = false;
    moved = false;
    start = p;
    syncClassSelect(-1);
    dirty = true;
    draw();
    return;
  }

  const hit = hitTest(p);

  if (hit.type === 'delete') {
    pushUndo();
    boxes.splice(hit.index, 1);
    selected = -1;
    justDrawn = false;
    syncClassSelect(-1);
    markDirty();
    draw();
    updateHistoryButtons();
    runHook('on_box_deleted');
    return;
  }

  if (hit.type === 'class') {
    selected = hit.index;
    justDrawn = false;
    dirty = true;
    syncClassSelect(selected);
    draw();
    updateHistoryButtons();
    openClassPicker(e.clientX, e.clientY);
    return;
  }

  if (hit.type === 'handle') {
    mode = 'resizing';
    handle = hit.handle;
    selected = hit.index;
    justDrawn = false;
    moved = false;
    dragStart = p;
    origBox = { ...boxes[selected] };
  } else if (hit.type === 'box' && !boxes[hit.index].fixed) {
    mode = 'moving';
    selected = hit.index;
    justDrawn = false;
    moved = false;
    dragStart = p;
    origBox = { ...boxes[selected] };
  } else {
    // empty space, or a fixed box: a plain click selects a fixed box (so it
    // can be unfixed), a drag draws a new box on top of it.
    mode = 'drawing';
    selected = hit.type === 'box' ? hit.index : -1;
    justDrawn = false;
    moved = false;
    start = p;
  }
  syncClassSelect(selected);
  dirty = true;
  draw();
});

// Listen on window (not just the canvas) so a drag that leaves the image still
// tracks the cursor and completes on release instead of losing the box.
window.addEventListener('mousemove', (e) => {
  const p = canvasPos(e);
  if (mode === 'drawing' && start) {
    mouse = clampToImage(p);
    draw();
  } else {
    mouse = p;
    if (mode === 'moving' && origBox) {
      moveBox(mouse);
    } else if (mode === 'resizing' && origBox) {
      resizeBox(mouse);
    } else {
      updateCursor(p);
    }
  }
});

window.addEventListener('mouseup', (e) => {
  const edited = (mode === 'moving' || mode === 'resizing') && moved;
  let created = false;
  if (mode === 'drawing' && start) {
    const r = normRect(start, clampToImage(mouse || start));
    if (r.w >= 3 && r.h >= 3) {
      const nb = toNorm(r);
      nb.class = defaultClass;
      boxes.push(nb);
      selected = boxes.length - 1;
      justDrawn = true;
      created = true;
      dbg('box created', { box: nb, total: boxes.length });
      openClassPicker(e.clientX, e.clientY);
    }
  }
  mode = 'idle';
  handle = null;
  start = null;
  dragStart = null;
  origBox = null;
  draw();
  updateCursor(canvasPos(e));
  updateHistoryButtons();
  if (created) {
    scheduleAutoSave();
    runHook('on_box_created');
  } else if (edited) {
    dbg('box edited', { index: selected, box: boxes[selected] });
    scheduleAutoSave();
    runHook('on_box_edited');
  }
});

el('prevBtn').addEventListener('click', () => go(-1));
el('nextBtn').addEventListener('click', () => go(1));
el('saveBtn').addEventListener('click', () => save());
el('undoBtn').addEventListener('click', undo);
el('redoBtn').addEventListener('click', redo);
el('setDataBtn').addEventListener('click', setDataYaml);
el('tagsDirBtn').addEventListener('click', setTagsDir);
el('tagsDirInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') setTagsDir();
});
el('actionsExpandBtn').addEventListener('click', () => {
  actionsExpanded = !actionsExpanded;
  applyActionOverflow();
});
el('settingsBtn').addEventListener('click', openSettingsModal);
el('settingsModalClose').addEventListener('click', closeSettingsModal);
el('settingsModal').addEventListener('click', (e) => {
  if (e.target === el('settingsModal')) closeSettingsModal();
});
document.querySelectorAll('.settings-tab').forEach((tab) => {
  tab.addEventListener('click', () => selectSettingsTab(tab.dataset.tab));
});
el('loadDataBtn').addEventListener('click', loadDataFromModal);
el('loadDataYaml').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') loadDataFromModal();
});
el('loadDataModalClose').addEventListener('click', closeLoadDataModal);
el('loadDataModal').addEventListener('click', (e) => {
  if (e.target === el('loadDataModal')) closeLoadDataModal();
});
el('updateCheckBtn').addEventListener('click', () => {
  el('updateStatus').textContent = 'Checking…';
  refreshUpdateInfo(true);
});
el('updateHowBtn').addEventListener('click', openUpdateModal);
el('updateModalClose').addEventListener('click', closeUpdateModal);
el('updateModal').addEventListener('click', (e) => {
  if (e.target === el('updateModal')) closeUpdateModal();
});
el('changelogModalClose').addEventListener('click', closeChangelog);
el('changelogModal').addEventListener('click', (e) => {
  if (e.target === el('changelogModal')) closeChangelog();
});
el('tipModalClose').addEventListener('click', closeTipModal);
el('tipModal').addEventListener('click', (e) => {
  if (e.target === el('tipModal')) closeTipModal();
});
el('notifBtn').addEventListener('click', (e) => {
  e.stopPropagation();
  toggleNotifPanel();
});
el('notifClear').addEventListener('click', () => {
  notifLog = [];
  notifUnread = 0;
  updateNotifBadge();
  renderNotifPanel();
});
document.addEventListener('click', (e) => {
  if (!e.target.closest('#notifPanel') && !e.target.closest('#notifBtn')) {
    toggleNotifPanel(false);
  }
});
el('recentSelect').addEventListener('change', () => {
  const val = el('recentSelect').value;
  if (!val) return;
  el('dataYaml').value = val;
  el('recentSelect').value = '';
  setDataYaml();
});
el('splitSelect').addEventListener('change', () => setSplit(el('splitSelect').value));
el('filterPanelClear').addEventListener('click', () => applyFilterChain([]));
el('filterPanelApply').addEventListener('click', () => applyFilterChain(selectedFilterChain()));
const counterInput = el('counter');
counterInput.addEventListener('focus', () => counterInput.select());
counterInput.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter') return;
  e.preventDefault();
  jumpToImage(counterInput.value);
  counterInput.blur();
});
counterInput.addEventListener('blur', () => updateNav());
el('actionResultClose').addEventListener('click', closeActionResult);

el('autoSaveSw').addEventListener('change', (e) => {
  autoSave = e.target.checked;
  settingsSet('autoSave', autoSave ? '1' : '0');
  if (autoSave) scheduleAutoSave(); // save what is already pending
  else clearTimeout(autoSaveTimer);
});

el('tipsSw').addEventListener('change', (e) => {
  settingsSet('ybe_tips_enabled', e.target.checked ? '1' : '0');
  if (!e.target.checked) closeTipModal();
});

el('addTagBtn').addEventListener('click', () => {
  if (el('tagInput').classList.contains('hidden')) openTagInput();
  else closeTagInput();
});
el('tagSubmitBtn').addEventListener('click', () => {
  addTagFromInput();
  closeTagInput();
});
el('tagExpandBtn').addEventListener('click', () => {
  const bar = el('tagBar');
  const expanded = bar.classList.toggle('expanded');
  el('tagExpandBtn').title = expanded ? 'Show fewer tags' : 'Show all tags';
  applyTagOverflow();
});
el('tagInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !readonly) {
    e.preventDefault();
    addTagFromInput();
    closeTagInput();
  } else if (e.key === 'Escape') {
    e.preventDefault();
    closeTagInput();
  }
});
window.addEventListener('resize', applyTagOverflow);

const classSelectEl = el('classSelect');
if (classSelectEl) {
  classSelectEl.addEventListener('change', () => {
    const v = parseInt(classSelectEl.value, 10);
    if (selected >= 0) {
      if (readonly) return;
      boxes[selected].class = v;
      justDrawn = false;
      markDirty();
      draw();
      updateHistoryButtons();
      runHook('on_box_edited');
    } else {
      defaultClass = v;
    }
  });
}

const APP_SHORTCUT_HANDLERS = {
  app_prev: (e) => { e.preventDefault(); go(-1); },
  app_next: (e) => { e.preventDefault(); go(1); },
  app_del: (e) => { if (readonly) return; e.preventDefault(); deleteSelected(); },
  app_drop: (e) => {
    e.preventDefault();
    closeClassPicker();
    if (justDrawn && selected >= 0) {
      // drop the box that was just drawn by mistake
      boxes.splice(selected, 1);
      selected = -1;
      justDrawn = false;
      markDirty();
      syncClassSelect(-1);
      draw();
      updateHistoryButtons();
      runHook('on_box_deleted');
    } else if (mode === 'drawing') {
      mode = 'idle';
      start = null;
      draw();
    } else if (selected >= 0) {
      selected = -1;
      syncClassSelect(-1);
      draw();
    }
  },
  app_save: (e) => { if (readonly) return; e.preventDefault(); save(); },
  app_undo: (e) => { if (readonly) return; e.preventDefault(); undo(); },
  app_redo: (e) => { if (readonly) return; e.preventDefault(); redo(); },
  app_ch_box: (e) => {
    if (readonly || selected < 0) return;
    e.preventDefault();
    justDrawn = false;
    openPickerForSelectedBox();
  },
  app_sel_box: (e) => {
    if (e.repeat || !boxes.length) return;
    e.preventDefault();
    if (selected < 0) {
      selected = Math.min(lastSelected >= 0 ? lastSelected : 0, boxes.length - 1);
    } else {
      selected = (selected + 1) % boxes.length;
    }
    justDrawn = false;
    syncClassSelect(selected);
    draw();
  },
  app_sel_points: (e) => { tabCycleRow(e); },
  app_escape: (e) => { escDeactivateRow(e); },
  app_show_hide: (e) => {
    e.preventDefault();
    boxesVisible = !boxesVisible;
    settingsSet(SHOW_BOXES_KEY, boxesVisible ? '1' : '0');
    draw();
  },
  app_fix_box: (e) => {
    if (readonly || selected < 0) return;
    e.preventDefault();
    toggleFixSelected();
  },
  // app_force_draw is a held modifier, not a keydown action: it is matched on
  // canvas mousedown (see forceDrawActive), so this handler is intentionally a
  // no-op. It exists so the binding can be validated and shown in the bar.
  app_force_draw: () => {},
  // Re-scan the image folders and keep the user on the same image *by path*
  // (falling back to the next surviving one when it was removed); used e.g.
  // after a user action deleted/added image files. Targeted — no full reload.
  app_refresh_images_list: async (e) => {
    e.preventDefault();
    const anchor = captureImageAnchor();
    dbg('rescan images list', { was: images.length, index: currentIndex,
      anchor: anchor && anchor.path });
    try {
      const res = await fetch('/api/images/rescan', { method: 'POST' });
      const data = await res.json();
      if (!data.ok) {
        console.error('[app_refresh_images_list] rescan failed', data);
        return;
      }
      applyImagesPayload(data, anchor, 'rescan');
    } catch (err) {
      console.error('[app_refresh_images_list] failed:', err);
    }
  },
  // Re-read the server's current list *without* touching the disk: use after a
  // `backend_*` action already re-scanned it (e.g. Archive's
  // `backend_rescan_images`). Keeps the same image by path; no extra disk scan.
  app_reload_images_list: async (e) => {
    e.preventDefault();
    const anchor = captureImageAnchor();
    dbg('reload images list', { was: images.length, index: currentIndex,
      anchor: anchor && anchor.path });
    try {
      const res = await fetch('/api/images');
      const data = await res.json();
      if (!data.ok) {
        console.error('[app_reload_images_list] reload failed', data);
        return;
      }
      applyImagesPayload(data, anchor, 'reload');
    } catch (err) {
      console.error('[app_reload_images_list] failed:', err);
    }
  },
  // Built-in tagging action, run by the shipped on_after_save hook (as
  // action_update_tags): persist the image's tags and add new names to tags.yaml.
  app_update_tags: () => updateTagsForImage(),
  // Re-fetch the current image from the server (cache-busted); e.g. after an
  // external editor wrote a new version of the file.
  app_refresh_image: (e) => {
    e.preventDefault();
    if (currentIndex < 0) { dbg('refresh image skipped (no image)'); return; }
    imageEl.src = '/api/image' + keyQuery(images[currentIndex]) + '&_=' + Date.now();
    dbg('refresh image', { index: currentIndex, src: imageEl.src });
  },
};

// Apply an /api/images (GET) or /api/images/rescan (POST) payload to the client
// list, keeping the current image by path through `anchor`. Shared by
// app_refresh_images_list (disk rescan) and app_reload_images_list (in-memory).
function applyImagesPayload(data, anchor, label) {
  images = data.images || [];
  activeSplit = data.active_split || null;
  if (data.active_filters !== undefined) activeFilters = data.active_filters || [];
  dbg(label + ' done', { now: images.length, active_split: activeSplit,
    active_filters: activeFilters, filter_error: data.filter_error });
  populateSplitSelect();
  populateFilterPanel();
  if (data.filter_error) showTransientFilterMessage(data.filter_error);
  if (!images.length) {
    currentIndex = -1;
    boxes = [];
    selected = -1;
    imageTags = [];
    imgW = 0;
    imgH = 0;
    canvas.width = 0;
    canvas.height = 0;
    updateNav();
    renderSidePanel();
    renderTagBar();
    return;
  }
  loadImage(resolveImageAnchor(anchor));
  runHook('on_images_list_loaded');
}

// Run an app action by name through the same path used for keyboard shortcuts,
// so after_success hooks behave exactly like bound keys. Rejects with an Error
// on unknown names or handler failures.
async function runAppAction(name, e) {
  const handler = APP_SHORTCUT_HANDLERS[name];
  if (!handler) {
    throw new Error(`unknown app action: ${name}`);
  }
  return handler(e || { preventDefault() {} });
}

// Tab on the selected box's row: cycle class select -> cx -> cy -> w -> h (forward).
function tabCycleRow(e) {
  if (e.target.matches && e.target.matches('.box-row-ctl')) {
    const row = e.target.closest('.box-row');
    if (row) {
      const order = ['.box-row-class', '.box-row-cx', '.box-row-cy', '.box-row-w', '.box-row-h'];
      const idx = order.findIndex((sel) => e.target.matches(sel));
      if (idx >= 0) {
        e.preventDefault();
        const next = order[(idx + 1) % order.length];
        row.querySelector(next).focus();
        return true;
      }
    }
    return false;
  }
  // a box is selected (by canvas click, row click or Shift) but focus is
  // elsewhere: Tab starts cycling its row from the class select
  if (selected >= 0 && !readonly) {
    const panel = el('boxList');
    if (panel && !el('sidebar').classList.contains('collapsed')) {
      const row = panel.querySelector(`.box-row[data-index="${selected}"]`);
      const first = row && row.querySelector('.box-row-class');
      if (first && !first.disabled) {
        e.preventDefault();
        first.focus();
        return true;
      }
    }
  }
  return false;
}

// Esc while a side-panel row control is focused deactivates that row.
function escDeactivateRow(e) {
  if (e.target.matches && e.target.matches('.box-row-ctl')) {
    e.target.blur(); // clears the editing-point highlight
    if (selected >= 0) {
      selected = -1;
      syncClassSelect(-1);
      draw();
    }
    return true;
  }
  return false;
}

function dispatchAppShortcut(e) {
  for (const name of APP_SHORTCUT_ORDER) {
    if (name === 'app_force_draw') continue; // modifier-only, matched on mousedown
    const info = appShortcuts[name];
    if (info && shortcutMatches(e, info.shortcut)) {
      runAppAction(name, e).catch((err) => console.error(`[shortcut] ${name}:`, err));
      return true;
    }
  }
  return false;
}

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if (!el('actionResult').classList.contains('hidden')) {
      closeActionResult();
      return;
    }
    if (!el('changelogModal').classList.contains('hidden')) {
      closeChangelog();
      return;
    }
    if (!el('tipModal').classList.contains('hidden')) {
      closeTipModal();
      return;
    }
    if (!el('loadDataModal').classList.contains('hidden')) {
      closeLoadDataModal();
      return;
    }
    if (!el('settingsModal').classList.contains('hidden')) {
      closeSettingsModal();
      return;
    }
    if (!el('updateModal').classList.contains('hidden')) {
      closeUpdateModal();
      return;
    }
    if (!el('notifPanel').classList.contains('hidden')) {
      toggleNotifPanel(false);
      return;
    }
  }
  // app_escape / app_sel_points must also work while typing in inputs
  const escInfo = appShortcuts['app_escape'];
  if (escInfo && shortcutMatches(e, escInfo.shortcut) && escDeactivateRow(e)) return;
  const ptsInfo = appShortcuts['app_sel_points'];
  if (ptsInfo && shortcutMatches(e, ptsInfo.shortcut) && tabCycleRow(e)) return;

  if (e.target.matches('input, select, textarea')) return;
  // Alt + digit toggles the matching available tag (Alt+1 = first in tags.yaml)
  if (e.altKey && !e.ctrlKey && !e.metaKey && !e.shiftKey && e.code.startsWith('Digit')) {
    const n = parseInt(e.code.slice(5), 10);
    if (n >= 1 && n <= availableTags.length) {
      e.preventDefault();
      toggleTagByNumber(n);
      return;
    }
  }
  if (dispatchAppShortcut(e)) return;
  runActionForShortcut(e);
});

function shortcutMatches(e, shortcut) {
  const parts = shortcut.split('+').map((s) => s.trim());
  const key = parts[parts.length - 1].toUpperCase();
  const want =
    ['Ctrl', 'Alt', 'Shift', 'Meta'].reduce((acc, m) => { acc[m] = parts.includes(m); return acc; }, {});
  if (e.ctrlKey !== !!want.Ctrl) return false;
  if (e.altKey !== !!want.Alt) return false;
  if (e.shiftKey !== !!want.Shift) return false;
  if (e.metaKey !== !!want.Meta) return false;
  if (/^[A-Z]$/.test(key)) return e.code === 'Key' + key;
  if (/^[0-9]$/.test(key)) return e.code === 'Digit' + key;
  if ((key === 'DELETE' || key === 'BACKSPACE') && (e.key === 'Delete' || e.key === 'Backspace')) return true;
  return e.key.toUpperCase() === key;
}

function runActionForShortcut(e) {
  if (readonly) return;
  for (const [name, info] of Object.entries(actionShortcuts)) {
    if (shortcutMatches(e, info.shortcut)) {
      e.preventDefault();
      runAction(name);
      return;
    }
  }
}

// Set up the appearance controls once, after /api/config has supplied the
// server's settings (so `settingsGet` can fall back to them). Idempotent: the
// fallback path below and later config reloads must not re-init.
let settingsInitialized = false;
function initSettings() {
  if (settingsInitialized) return;
  settingsInitialized = true;
  initSidePanel();
  initAppearance();
  el('autoSaveSw').checked = settingsGet('autoSave') === '1';
  autoSave = el('autoSaveSw').checked;
  boxesVisible = settingsGet(SHOW_BOXES_KEY) !== '0';
  el('tipsSw').checked = settingsGet('ybe_tips_enabled') !== '0';
}

// With --debug these surface any error that would otherwise only show in the
// browser console; without it they are no-ops.
window.addEventListener('error', (e) => dbgWarn('uncaught error', e.error || e.message));
window.addEventListener('unhandledrejection', (e) => dbgWarn('unhandled rejection', e.reason));

loadConfig().catch((err) => {
  console.error('[ybe] config load failed:', err);
  initSettings(); // still build the UI with browser-only settings
});
startPresence();
// The start-thread check may not have finished when the page loads; retry so a
// freshly found update still reaches the user without a reload.
refreshUpdateInfo();
UPDATE_POLL_MS.forEach((ms) => setTimeout(() => refreshUpdateInfo(), ms));
