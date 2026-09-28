'use strict';

const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');

const el = (id) => document.getElementById(id);

const HANDLE_SIZE = 8;
const DEL_BTN = 16;
const MAX_CASCADE_DEPTH = 8; // action -> after_success -> action ... recursion cap
const AUTO_SAVE_DELAY = 400; // ms to coalesce rapid edits into one auto-save

let images = [];
let splits = [];
let filters = [];
let classes = [];
let currentIndex = -1;
let activeSplit = null;
let activeFilter = null;
let boxes = [];        // normalized: {class, cx, cy, w, h}
let selected = -1;
let lastSelected = 0; // most recent selected index; Shift resumes here after Esc
let defaultClass = 0;
let justDrawn = false; // whether the selected box was just created (Esc can drop it)
let editingPoint = null; // {i, name} -> coordinate input focused in the side panel (cx/cy/w/h)
let appShortcuts = {}; // app action  -> {shortcut, label} from shortcuts.txt
let actionShortcuts = {}; // user action -> {shortcut, label} from shortcuts.txt
let shortcutErrors = []; // validation errors from shortcuts.txt
let undoStack = [];   // snapshots of `boxes` before each edit (fresh per image)
let redoStack = [];
let moved = false;    // whether the current drag actually changed anything yet
let imgW = 0;
let imgH = 0;
let dirty = false;
let readonly = false;
let datasetLoaded = false;
let taggingEnabled = false; // "Tags" switch; shows the tag bar
let availableTags = [];     // dataset-wide list from tags.yaml (toggle order for Alt+n)
let imageTags = [];         // current image's tags
let boxesVisible = true;    // `app_show_hide`: draw the box overlay or not
let currentDataYaml = '';   // data.yaml of the loaded dataset (for resume)
let hooksByName = new Set(); // event hooks defined in actions/ (on_app_hook_*)
let userActions = new Set(); // non-hook action names (for after_success cascades)
let hookInFlight = new Set(); // hooks currently running (re-entrancy guard)
let autoSave = false;        // save labels automatically after each edit
let autoSaveTimer = null;    // debounce timer for auto-save
const LAST_IMAGE_KEY = 'ybe_last_image'; // localStorage key: last image reached
const FILTER_KEY = 'ybe_filter';         // localStorage key: last active filter + split

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
  draw();
};
imageEl.onerror = () => {
  // the image file is gone (e.g. removed by an action): blank the canvas so
  // no stale frame keeps showing a deleted image.
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

  updateBoxCount();

  // a coordinate input highlight only survives while that input keeps focus
  const f = document.activeElement;
  if (editingPoint && (!f || f.dataset.name !== editingPoint.name)) editingPoint = null;

  if (boxesVisible) {
    boxes.forEach((b, idx) => {
      const r = toPx(b);
      const active = idx === selected;
      ctx.strokeStyle = active ? '#ffd166' : '#2ecc71';
      ctx.lineWidth = active ? 3 : 2;
      ctx.strokeRect(r.x, r.y, r.w, r.h);

      const label = `${b.class}: ${classes[b.class] || 'class ' + b.class}`;
      ctx.font = '14px system-ui, sans-serif';
      const tw = ctx.measureText(label).width;
      const ly = Math.max(0, r.y - 18);
      ctx.fillStyle = active ? 'rgba(255,209,102,0.92)' : 'rgba(46,204,113,0.85)';
      ctx.fillRect(r.x, ly, tw + 8, 18);
      ctx.fillStyle = '#111';
      ctx.fillText(label, r.x + 4, ly + 13);

      if (!readonly) {
        drawDeleteButton(r);
        drawClassButton(r);
      }
      if (active && !readonly) drawHandles(r);
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
  if (selected >= 0) {
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

function syncClassSelect(idx) {
  if (idx >= 0) lastSelected = idx;
  const sel = el('classSelect');
  if (!sel) return;
  sel.value = idx >= 0 ? boxes[idx].class : defaultClass;
}

function moveBox(p) {
  const dx = (p.x - dragStart.x) / imgW;
  const dy = (p.y - dragStart.y) / imgH;
  boxes[selected] = {
    ...origBox,
    cx: clamp01(origBox.cx + dx),
    cy: clamp01(origBox.cy + dy),
  };
  moved = true;
  draw();
}

function resizeBox(p) {
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
  el('filename').textContent = total
    ? `${images[currentIndex].split}/${images[currentIndex].name}`
    : '';
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

function applyDatasetVisibility() {
  el('settings').classList.toggle('hidden', datasetLoaded);
  el('changeDataBtn').classList.toggle('hidden', !datasetLoaded);
  el('sidePanelToggle').classList.toggle('hidden', !datasetLoaded);
  // filters need a dataset to receive, so only show them once one is loaded
  el('filterBox').classList.toggle('hidden', !datasetLoaded);
}

function updateBoxCount() {
  el('boxCount').textContent = boxes.length
    ? `${boxes.length} box${boxes.length === 1 ? '' : 'es'}`
    : '0 boxes';
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

function populateFilterSelect() {
  const sel = el('filterSelect');
  sel.innerHTML = '';
  const none = document.createElement('option');
  none.value = '';
  none.textContent = 'No filter';
  sel.appendChild(none);
  filters.forEach((name) => {
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name;
    sel.appendChild(opt);
  });
  sel.value = activeFilter || '';
  sel.disabled = filters.length === 0;
}

function populateRecent(paths) {
  const sel = el('recentSelect');
  sel.innerHTML = '';
  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = 'Recent…';
  sel.appendChild(placeholder);
  (paths || []).forEach((p) => {
    const opt = document.createElement('option');
    opt.value = p;
    opt.textContent = p;
    sel.appendChild(opt);
  });
  sel.value = '';
}

function populateActions(names) {
  const box = el('actionBtns');
  box.innerHTML = '';
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
}

function setActionButtonsDisabled(disabled) {
  el('actionBtns').querySelectorAll('button').forEach((b) => { b.disabled = disabled; });
}

// ------------------------------------------------------------------------- //
// shortcuts bar (bottom)
// ------------------------------------------------------------------------- //
function shortcutKbd(text) {
  const k = document.createElement('kbd');
  k.textContent = text;
  return k;
}

function buildKeyShortcut(keys, text) {
  const span = document.createElement('span');
  span.className = 'kbd-item';
  keys.forEach((k) => span.appendChild(shortcutKbd(k)));
  span.appendChild(document.createTextNode(' ' + text));
  return span;
}

function buildMouseShortcut() {
  const span = document.createElement('span');
  span.className = 'kbd-item';
  const drag = document.createElement('span');
  drag.className = 'mouse-hint';
  drag.textContent = 'drag';
  const del = document.createElement('span');
  del.className = 'mouse-hint';
  del.textContent = '\u2715';
  span.append(drag, document.createTextNode(' draw \u00b7 '), del, document.createTextNode(' delete box'));
  return span;
}

function buildActionShortcut(name, info) {
  const span = document.createElement('span');
  span.className = 'kbd-item';
  span.append(document.createTextNode(name), shortcutKbd(info.shortcut));
  if (info.label) span.append(document.createTextNode(': ' + info.label));
  return span;
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

const APP_SHORTCUT_ORDER = ['app_prev', 'app_next', 'app_del', 'app_drop', 'app_undo', 'app_redo', 'app_save', 'app_ch_box', 'app_sel_box', 'app_sel_points', 'app_escape', 'app_show_hide', 'app_refresh_images_list', 'app_refresh_image'];

function renderShortcutErrors() {
  const box = el('shortcutErrors');
  box.innerHTML = '';
  const dismissed = JSON.parse(sessionStorage.getItem('dismissedShortcutErrors') || '[]');
  const visible = shortcutErrors.filter((msg) => !dismissed.includes(msg));
  if (!visible.length) {
    box.classList.add('hidden');
    return;
  }
  box.classList.remove('hidden');
  const banner = document.createElement('div');
  banner.className = 'shortcut-errors-banner';
  const text = document.createElement('span');
  text.textContent = 'shortcuts.txt: ' + visible.join(' | ');
  const close = document.createElement('button');
  close.className = 'shortcut-errors-dismiss';
  close.textContent = '\u00d7';
  close.title = 'Hide this message for this session';
  close.addEventListener('click', () => {
    const updated = dismissed.concat(visible);
    sessionStorage.setItem('dismissedShortcutErrors', JSON.stringify(updated));
    box.classList.add('hidden');
  });
  banner.append(text, close);
  box.appendChild(banner);
}

function renderShortcuts() {
  const wrap = el('shortcutItems');
  const menu = el('shortcutsMenu');
  wrap.innerHTML = '';
  menu.innerHTML = '';

  APP_SHORTCUT_ORDER.forEach((name) => {
    const info = appShortcuts[name];
    if (!info) return;
    wrap.appendChild(buildKeyShortcut([info.shortcut], info.label));
    menu.appendChild(menuRow(info.label, info.shortcut));
  });
  wrap.appendChild(buildMouseShortcut());
  Object.entries(actionShortcuts).forEach(([name, info]) => {
    wrap.appendChild(buildActionShortcut(name, info));
    menu.appendChild(menuRow(`${name}: ${info.label}`.trim(), info.shortcut));
  });
  applyShortcutOverflow();
}

function applyShortcutOverflow() {
  const wrap = el('shortcutItems');
  const moreBtn = el('shortcutsMoreBtn');
  const menu = el('shortcutsMenu');
  const items = Array.from(wrap.children);

  items.forEach((i) => i.classList.remove('hidden'));
  moreBtn.classList.add('hidden');
  menu.classList.add('hidden');

  if (wrap.scrollWidth <= wrap.clientWidth) return;

  moreBtn.classList.remove('hidden');
  for (let i = items.length - 1; i >= 0 && wrap.scrollWidth > wrap.clientWidth; i--) {
    items[i].classList.add('hidden');
  }
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
  const cfg = opts.skipFilterRestore ? cfg0 : await maybeRestoreFilter(cfg0);
  images = cfg.images || [];
  splits = cfg.splits || [];
  filters = cfg.filters || [];
  activeSplit = cfg.active_split || null;
  activeFilter = cfg.active_filter || null;
  classes = cfg.classes || ['class_0'];
  availableTags = cfg.tags || [];
  datasetLoaded = !!cfg.data_yaml;
  el('dataYaml').value = cfg.data_yaml || '';
  currentDataYaml = cfg.data_yaml || '';
  el('datasetPath').textContent = cfg.dataset_path ? `dataset: ${cfg.dataset_path}` : '';
  readonly = !!cfg.readonly;
  applyDatasetVisibility();
  el('readonlySw').dataset.server = cfg.readonly ? '1' : '';
  applyReadonly();
  populateClasses();
  populateSplitSelect();
  populateFilterSelect();
  populateRecent(cfg.recent_data_yamls || []);
  actionShortcuts = cfg.action_shortcuts || {};
  appShortcuts = cfg.shortcuts || {};
  shortcutErrors = cfg.shortcut_errors || [];
  hooksByName = new Set(cfg.hooks || []);
  userActions = new Set(cfg.actions || []);
  renderShortcutErrors();
  populateActions(cfg.actions || []);
  renderShortcuts();
  persistFilterView(cfg);
  if (cfg.filter_error) showTransientFilterMessage(cfg.filter_error);
  if (images.length) {
    if (opts.explicit) {
      loadImage(startIdx);
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
  runHook('on_app_hook_images_list_loaded');
}

// The active filter (and the split it was selected with) live in the server's
// STATE, which a restart clears. Persist them here so the view is restored.
function persistFilterView(cfg) {
  try {
    if (cfg.data_yaml && cfg.active_filter) {
      localStorage.setItem(FILTER_KEY, JSON.stringify({
        dataYaml: cfg.data_yaml,
        split: cfg.active_split || null,
        filter: cfg.active_filter,
      }));
    } else {
      localStorage.removeItem(FILTER_KEY);
    }
  } catch (e) { /* storage unavailable */ }
}

function readSavedFilter() {
  try {
    return JSON.parse(localStorage.getItem(FILTER_KEY) || 'null');
  } catch (e) { return null; }
}

function clearSavedFilter() {
  try { localStorage.removeItem(FILTER_KEY); } catch (e) { /* ignore */ }
}

// On load, re-apply a remembered filter when the server has none (e.g. after a
// restart). Direct fetches only — never re-enters loadConfig.
async function maybeRestoreFilter(cfg) {
  if (cfg.active_filter || !cfg.data_yaml || !(cfg.filters || []).length) return cfg;
  const saved = readSavedFilter();
  if (!saved || saved.dataYaml !== cfg.data_yaml || !cfg.filters.includes(saved.filter)) {
    clearSavedFilter();
    return cfg;
  }
  const wantedSplit = saved.split || null;
  if (wantedSplit !== (cfg.active_split || null)) {
    const valid = wantedSplit === null || (cfg.splits || []).some((s) => s.name === wantedSplit);
    if (valid) {
      const res = await fetch('/api/split', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ split: wantedSplit }),
      });
      const data = await res.json();
      if (data.ok) cfg = data;
    }
  }
  const res = await fetch('/api/filter', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filter: saved.filter }),
  });
  const data = await res.json();
  if (data.ok) return data;
  clearSavedFilter();
  return cfg;
}

function showTransientFilterMessage(msg) {
  const status = el('folderStatus');
  status.textContent = msg;
  clearTimeout(showTransientFilterMessage._t);
  showTransientFilterMessage._t = setTimeout(() => { status.textContent = ''; }, 4000);
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

  Promise.all([
    fetch('/api/labels/' + currentIndex).then((r) => r.json()),
    fetch('/api/tags/' + currentIndex).then((r) => r.json()),
  ]).then(([labelData, tagData]) => {
    if (requested !== currentIndex) return; // a newer loadImage superseded us
    boxes = Array.isArray(labelData) ? labelData : [];
    imageTags = (tagData && tagData.tags) || [];
    imageEl.src = '/api/image/' + currentIndex;
    rememberLastImage();
    renderTagBar();
    runHook('on_app_hook_image_loaded');
  });
}

// remember the current image so the app can resume here on reload
function rememberLastImage() {
  if (currentIndex < 0 || !images[currentIndex]) return;
  try {
    localStorage.setItem(LAST_IMAGE_KEY, JSON.stringify({
      dataYaml: currentDataYaml,
      split: images[currentIndex].split,
      name: images[currentIndex].name,
    }));
  } catch (e) { /* storage unavailable; just don't resume */ }
}

function readLastImage() {
  try {
    const raw = localStorage.getItem(LAST_IMAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (e) { return null; }
}

async function resumeLastImage(cfg) {
  const mem = readLastImage();
  if (!mem || mem.dataYaml !== cfg.data_yaml || !images.length) {
    loadImage(0);
    return;
  }
  // the remembered image lives in a split that isn't currently active: switch
  // the filter first; the reload will then resume onto the image itself.
  // (with a filter active the split is just its input, so don't force it)
  if (!cfg.active_filter && mem.split && mem.split !== cfg.active_split) {
    if (cfg.splits.some((s) => s.name === mem.split)) {
      await setSplit(mem.split, true);
      return;
    }
  }
  const idx = images.findIndex((im) => im.split === mem.split && im.name === mem.name);
  loadImage(idx >= 0 ? idx : 0);
}

async function go(delta) {
  if (currentIndex < 0) return;
  const next = currentIndex + delta;
  if (next < 0 || next >= images.length) return;
  if (dirty) {
    if (autoSave) {
      if (!(await flushAutoSave())) return; // stay put if the save failed
    } else if (!confirm('You have unsaved changes. Discard them?')) {
      return;
    }
  }
  // navigation hooks run on the image being left; they capture its index before
  // loadImage advances currentIndex
  runHook(delta < 0 ? 'on_app_hook_prev' : 'on_app_hook_next');
  loadImage(next);
}

// ------------------------------------------------------------------------- //
// tagging (per-image tag bar)
// ------------------------------------------------------------------------- //
function setTagStatus(msg) {
  const status = el('tagStatus');
  status.textContent = msg;
  clearTimeout(setTagStatus._t);
  setTagStatus._t = setTimeout(() => { status.textContent = ''; }, 2000);
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
    else addTag(name, false);
  });
  return b;
}

function renderTagBar() {
  const bar = el('tagBar');
  const show = taggingEnabled && datasetLoaded && currentIndex >= 0;
  bar.classList.toggle('hidden', !show);
  if (!show) return;

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
  el('addTagBtn').disabled = readonly;
  el('tagHint').classList.toggle('hidden', availableTags.length === 0);

  const dl = el('tagSuggestions');
  dl.innerHTML = '';
  availableTags.forEach((t) => {
    const opt = document.createElement('option');
    opt.value = t;
    dl.appendChild(opt);
  });
}

async function saveImageTags() {
  if (currentIndex < 0) return;
  try {
    const res = await fetch('/api/tags/' + currentIndex, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tags: imageTags }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      setTagStatus(`Saved ${data.count} tag(s)`);
    } else {
      setTagStatus('Tag save failed: ' + (data.error || res.status));
    }
  } catch (err) {
    setTagStatus('Tag save failed: ' + err.message);
  }
  renderTagBar();
}

async function addTag(name, addToDataset) {
  if (readonly || currentIndex < 0) return;
  if (imageTags.includes(name)) return;
  if (addToDataset) {
    const next = [...availableTags, name];
    const res = await fetch('/api/tags.yaml', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tags: next }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      setTagStatus('Failed to add to tags.yaml: ' + (data.error || res.status));
      return;
    }
    const data = await res.json();
    availableTags = (data && data.tags) || next;
  }
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
  addTag(name, !availableTags.includes(name));
}

function toggleTagByNumber(n) {
  if (readonly || currentIndex < 0) return;
  const i = n - 1;
  if (i < 0 || i >= availableTags.length) return;
  if (!taggingEnabled) {
    taggingEnabled = true;
    localStorage.setItem('taggingEnabled', '1');
    el('taggingSw').checked = true;
  }
  const name = availableTags[i];
  if (imageTags.includes(name)) removeTag(name);
  else addTag(name, false);
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
  draw();
}

function deleteSelected() {
  if (selected >= 0) {
    pushUndo();
    boxes.splice(selected, 1);
    selected = -1;
    justDrawn = false;
    markDirty();
    draw();
    updateHistoryButtons();
    runHook('on_app_hook_box_deleted');
  }
}

// Mark the labels as changed and, when auto-save is on, queue a save.
function markDirty() {
  dirty = true;
  scheduleAutoSave();
}

function scheduleAutoSave() {
  if (!autoSave || readonly || currentIndex < 0) return;
  clearTimeout(autoSaveTimer);
  autoSaveTimer = setTimeout(() => { autoSaveTimer = null; save(); }, AUTO_SAVE_DELAY);
}

// Save any pending auto-save now (used before navigating away).
async function flushAutoSave() {
  if (autoSaveTimer) {
    clearTimeout(autoSaveTimer);
    autoSaveTimer = null;
  }
  if (!dirty || readonly) return true;
  return save();
}

// Returns true on success, false when the write failed or a hook cancelled it.
async function save() {
  if (currentIndex < 0) return false;
  const status = el('status');
  // a failing before_save hook cancels the write
  if (!(await runHook('on_app_hook_before_save'))) {
    status.textContent = 'Save aborted by on_app_hook_before_save';
    return false;
  }
  status.textContent = 'Saving…';
  let ok = false;
  try {
    const res = await fetch('/api/labels/' + currentIndex, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ boxes }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      dirty = false;
      ok = true;
      status.textContent = `Saved ${data.count} box(es)`;
      setTimeout(() => { status.textContent = ''; }, 2000);
      updateHistoryButtons();
      runHook('on_app_hook_after_save');
    } else {
      status.textContent = 'Save failed: ' + (data.error || res.status);
    }
  } catch (err) {
    status.textContent = 'Save failed: ' + err.message;
  }
  updateHistoryButtons();
  return ok;
}

async function setDataYaml() {
  const yamlPath = el('dataYaml').value.trim();
  const status = el('folderStatus');
  status.textContent = 'Loading…';
  try {
    const res = await fetch('/api/data', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data_yaml: yamlPath }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      status.textContent = 'Loaded';
      await loadConfig();
      setTimeout(() => { status.textContent = ''; }, 2000);
    } else {
      status.textContent = data.error || 'Invalid data.yaml';
    }
  } catch (err) {
    status.textContent = 'Error: ' + err.message;
  }
}

async function setSplit(split, resumeOk = false) {
  const status = el('folderStatus');
  status.textContent = 'Switching split…';
  try {
    const res = await fetch('/api/split', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ split: split || null }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      status.textContent = '';
      await loadConfig(0, { noResume: !resumeOk });
    } else {
      status.textContent = data.error || 'Split switch failed';
    }
  } catch (err) {
    status.textContent = 'Error: ' + err.message;
  }
}

async function setFilter(name) {
  const status = el('folderStatus');
  status.textContent = 'Applying filter…';
  try {
    const res = await fetch('/api/filter', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filter: name || null }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      status.textContent = '';
      await loadConfig(0, { noResume: true, skipFilterRestore: true });
    } else {
      status.textContent = data.error || 'Filter failed';
      populateFilterSelect(); // revert the select to the active filter
    }
  } catch (err) {
    status.textContent = 'Error: ' + err.message;
    populateFilterSelect();
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

// Event hooks report success in the bottom status bar (auto-hides); failures
// still use the result modal.
function setHookStatus(msg) {
  const bar = el('hookStatusBar');
  const text = el('hookStatus');
  if (!bar || !text) return;
  text.textContent = msg;
  bar.classList.remove('hidden');
  clearTimeout(setHookStatus._t);
  setHookStatus._t = setTimeout(() => { bar.classList.add('hidden'); }, 3000);
}

// Run one user action (or event hook) on the current image. `confirm: false`
// skips the confirmation prompt — hooks run automatically. Returns true when
// the action succeeded (or there was nothing to run), false on failure.
async function runAction(name, opts = {}) {
  const ask = opts.confirm !== false;
  const depth = opts.depth || 0;
  const isHook = !!opts.hook;
  if (!name || currentIndex < 0 || !images[currentIndex]) return false;
  const target = `${images[currentIndex].split}/${images[currentIndex].name}`;
  if (ask && !confirm(`Run action "${name}" on ${target}?`)) return false;
  setActionButtonsDisabled(true);
  try {
    const res = await fetch('/api/actions/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: name, idx: currentIndex }),
    });
    const data = await res.json();
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
    // YAML actions may return an after_success chain to integrate with the app
    // (app_refresh_* or another action). Run it one after another; on the first
    // error report it, show a message and stop the chain.
    return await runAfterSuccessChain(data.after_success || [], depth, isHook);
  } catch (err) {
    showActionResult({ ok: false, action: name, error: 'Error: ' + err.message });
    return false;
  } finally {
    setActionButtonsDisabled(readonly);
  }
}

// Fire an event hook if it is defined and an image is loaded. No-op otherwise.
// The in-flight guard keeps a hook from re-entering itself (e.g. a hook whose
// after_success refreshes the image list, which would fire it again).
async function runHook(name) {
  if (!hooksByName.has(name) || currentIndex < 0) return true;
  if (hookInFlight.has(name)) return true;
  hookInFlight.add(name);
  try {
    return await runAction(name, { confirm: false, hook: true });
  } finally {
    hookInFlight.delete(name);
  }
}

// Run an after_success chain: app actions or other (non-hook) actions.
async function runAfterSuccessChain(chain, depth, isHook) {
  for (const name of chain) {
    try {
      await runAfterSuccess(name, depth, isHook);
    } catch (err) {
      const msg = `after_success "${name}" failed: ${err.message}`;
      console.error(msg, err);
      showActionHookError(msg);
      return false;
    }
  }
  return true;
}

async function runAfterSuccess(name, depth, isHook) {
  // hooks are event-driven only: they cannot be triggered from after_success
  if (hooksByName.has(name)) {
    throw new Error(`"${name}" is an event hook; hooks cannot run from after_success`);
  }
  if (APP_SHORTCUT_HANDLERS[name]) {
    return runAppAction(name);
  }
  if (userActions.has(name)) {
    if (depth >= MAX_CASCADE_DEPTH) {
      throw new Error(`action cascade exceeded ${MAX_CASCADE_DEPTH} levels`);
    }
    const ok = await runAction(name, { confirm: false, depth: depth + 1, hook: isHook });
    if (!ok) throw new Error(`action "${name}" failed`);
    return true;
  }
  throw new Error(`unknown app action: ${name}`);
}

function showActionHookError(msg) {
  const box = el('actionResult');
  if (box.classList.contains('hidden')) {
    // the parent (hook) succeeded silently, so start a fresh error modal
    const title = el('actionResultTitle');
    title.textContent = 'after_success failed';
    title.style.color = 'var(--red)';
    setResultText('actionResultCmd', '');
    setResultText('actionResultExit', '');
    setResultText('actionResultOut', '');
    setResultText('actionResultErr', '');
  }
  box.classList.remove('hidden');
  const errNode = el('actionResultErr');
  errNode.textContent = errNode.textContent
    ? errNode.textContent + '\n' + msg
    : msg;
  if (errNode.classList && errNode.classList.contains('modal-empty')) {
    errNode.classList.remove('modal-empty');
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
        if (!wasJustDrawn) runHook('on_app_hook_box_edited');
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
// boxes side panel (right edge, hideable)
// ------------------------------------------------------------------------- //
let sidePanelOpen = true;

function fmtNum(v) {
  return Math.round(v * 10000) / 10000;
}

function initSidePanel() {
  sidePanelOpen = localStorage.getItem('sidePanelOpen') !== '0';
  toggleSidePanel(sidePanelOpen);
  el('sidePanelToggle').addEventListener('click', () => toggleSidePanel());
  el('sidePanelClose').addEventListener('click', () => toggleSidePanel(false));
}

function toggleSidePanel(show) {
  const open = show !== undefined ? !!show : !sidePanelOpen;
  sidePanelOpen = open;
  el('sidePanel').classList.toggle('hidden', !open);
  el('sidePanelToggle').classList.toggle('active', open);
  localStorage.setItem('sidePanelOpen', open ? '1' : '0');
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

    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'box-row-ctl box-row-del danger';
    del.textContent = '\u00d7';
    del.title = 'Delete box';

    const top = document.createElement('div');
    top.className = 'box-row-top';
    top.append(idx, cls, del);

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
      runHook('on_app_hook_box_edited');
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
          runHook('on_app_hook_box_edited');
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
      runHook('on_app_hook_box_deleted');
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
    row.querySelector('.box-row-idx').textContent = i;
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
    runHook('on_app_hook_box_deleted');
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
  } else if (hit.type === 'box') {
    mode = 'moving';
    selected = hit.index;
    justDrawn = false;
    moved = false;
    dragStart = p;
    origBox = { ...boxes[selected] };
  } else {
    mode = 'drawing';
    selected = -1;
    justDrawn = false;
    moved = false;
    start = p;
  }
  syncClassSelect(selected);
  dirty = true;
  draw();
});

canvas.addEventListener('mousemove', (e) => {
  mouse = canvasPos(e);
  if (mode === 'drawing' && start) {
    draw();
  } else if (mode === 'moving' && origBox) {
    moveBox(mouse);
  } else if (mode === 'resizing' && origBox) {
    resizeBox(mouse);
  }
});

canvas.addEventListener('mouseup', (e) => {
  const edited = (mode === 'moving' || mode === 'resizing') && moved;
  let created = false;
  if (mode === 'drawing' && start) {
    const r = normRect(start, mouse || start);
    if (r.w >= 3 && r.h >= 3) {
      const nb = toNorm(r);
      nb.class = defaultClass;
      boxes.push(nb);
      selected = boxes.length - 1;
      justDrawn = true;
      created = true;
      openClassPicker(e.clientX, e.clientY);
    }
  }
  mode = 'idle';
  handle = null;
  start = null;
  dragStart = null;
  origBox = null;
  draw();
  updateHistoryButtons();
  if (created) {
    scheduleAutoSave();
    runHook('on_app_hook_box_created');
  } else if (edited) {
    scheduleAutoSave();
    runHook('on_app_hook_box_edited');
  }
});

canvas.addEventListener('mouseleave', () => {
  if (mode === 'drawing') {
    mode = 'idle';
    start = null;
    draw();
  }
});

el('prevBtn').addEventListener('click', () => go(-1));
el('nextBtn').addEventListener('click', () => go(1));
el('saveBtn').addEventListener('click', save);
el('undoBtn').addEventListener('click', undo);
el('redoBtn').addEventListener('click', redo);
el('setDataBtn').addEventListener('click', setDataYaml);
el('changeDataBtn').addEventListener('click', () => {
  datasetLoaded = false;
  applyDatasetVisibility();
});
el('shortcutsMoreBtn').addEventListener('click', () => {
  el('shortcutsMenu').classList.toggle('hidden');
});
document.addEventListener('click', (e) => {
  if (!e.target.closest('#shortcutBar')) el('shortcutsMenu').classList.add('hidden');
});
window.addEventListener('resize', applyShortcutOverflow);
el('recentSelect').addEventListener('change', () => {
  const val = el('recentSelect').value;
  if (!val) return;
  el('dataYaml').value = val;
  el('recentSelect').value = '';
  setDataYaml();
});
el('splitSelect').addEventListener('change', () => setSplit(el('splitSelect').value));
el('filterSelect').addEventListener('change', () => setFilter(el('filterSelect').value));
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

el('taggingSw').addEventListener('change', (e) => {
  taggingEnabled = e.target.checked;
  localStorage.setItem('taggingEnabled', taggingEnabled ? '1' : '0');
  renderTagBar();
});

el('autoSaveSw').addEventListener('change', (e) => {
  autoSave = e.target.checked;
  localStorage.setItem('autoSave', autoSave ? '1' : '0');
  if (autoSave) scheduleAutoSave(); // save what is already pending
  else clearTimeout(autoSaveTimer);
});

el('addTagBtn').addEventListener('click', addTagFromInput);
el('tagInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !readonly) {
    e.preventDefault();
    addTagFromInput();
  }
});

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
      runHook('on_app_hook_box_edited');
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
      runHook('on_app_hook_box_deleted');
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
    draw();
  },
  // Re-scan the image folders and stay on the same index (clamped); used e.g.
  // after a user action deleted/added image files. Targeted — no full reload.
  app_refresh_images_list: async (e) => {
    e.preventDefault();
    try {
      const res = await fetch('/api/images/rescan', { method: 'POST' });
      const data = await res.json();
      if (!data.ok) {
        console.error('[app_refresh_images_list] rescan failed', data);
        return;
      }
      images = data.images || [];
      activeSplit = data.active_split || null;
      if (data.active_filter !== undefined) activeFilter = data.active_filter || null;
      populateSplitSelect();
      populateFilterSelect();
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
      const idx = Math.max(0, Math.min(currentIndex, images.length - 1));
      loadImage(idx);
      runHook('on_app_hook_images_list_loaded');
    } catch (err) {
      console.error('[app_refresh_images_list] failed:', err);
    }
  },
  // Re-fetch the current image from the server (cache-busted); e.g. after an
  // external editor wrote a new version of the file.
  app_refresh_image: (e) => {
    e.preventDefault();
    if (currentIndex < 0) return;
    imageEl.src = '/api/image/' + currentIndex + '?_=' + Date.now();
  },
};

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
    const panel = el('sidePanel');
    if (panel && !panel.classList.contains('hidden')) {
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
    if (!el('shortcutsMenu').classList.contains('hidden')) {
      el('shortcutsMenu').classList.add('hidden');
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

el('taggingSw').checked = localStorage.getItem('taggingEnabled') === '1';
el('autoSaveSw').checked = localStorage.getItem('autoSave') === '1';
autoSave = el('autoSaveSw').checked;

loadConfig();
initSidePanel();
