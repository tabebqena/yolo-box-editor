// app/static/js/appearance.js — control-panel side and dockable widgets
'use strict';

// ------------------------------------------------------------------------- //
// appearance: control panel side + dockable Tags / Boxes widgets
//
// Widgets (Tags, Boxes) live in one of: their default spot, a floating window,
// the left panel, the right panel or the bottom panel. A side location that
// matches the control panel merges into it (stacked); otherwise it uses the
// widget-only panel on the opposite side, which appears only while it has a
// visible child.
// ------------------------------------------------------------------------- //
// Settings keys for the control-panel side and dock panel sizes.
const PANEL_SIDE_KEY = 'ybe_panel_side';
const DOCK_SIDE_W_KEY = 'ybe_dock_side_w';
const DOCK_BOTTOM_H_KEY = 'ybe_dock_bottom_h';
// Legacy localStorage keys migrated to the widget settings on first run.
const LEGACY_TAGGING_KEY = 'taggingEnabled';
const LEGACY_DETACH_TAGS_KEY = 'ybe_detach_tags';
const LEGACY_DETACH_BOXES_KEY = 'ybe_detach_boxes';
// Floating-window margin and dock panel size bounds (px).
const FLOAT_MARGIN = 8;
const DOCK_SIDE_MIN = 200;
const DOCK_SIDE_MAX = 720;
const DOCK_BOTTOM_MIN = 100;
// Valid docking locations for a widget.
const DOCK_LOCATIONS = ['default', 'float', 'left', 'right', 'bottom'];

// Which side the control panel is docked to ('left' or 'right').
let panelSide = 'left';

/*
 * The dockable widgets. `default` puts the content back where it lives in the
 * markup; the other locations are the floating window or an edge panel.
 */
const WIDGETS = {
  boxes: {
    frame: 'boxFloat', body: 'boxFloatBody',
    content: () => qs('.boxes-section'),
    parent: () => qs('#sidebar .sidebar-body'),
    key: 'ybe_boxes_dock', select: 'boxesDockSel',
    visibleKey: 'ybe_boxes_visible', visibleSw: 'boxesVisibleSw',
  },
  actions: {
    frame: 'actionsFloat', body: 'actionsFloatBody',
    content: () => qs('.actionbox'),
    parent: () => qs('#sidebar .sidebar-body'),
    anchor: () => el('actionsSep'),
    key: 'ybe_actions_dock', select: 'actionsDockSel',
    visibleKey: 'ybe_actions_visible', visibleSw: 'actionsVisibleSw',
  },
  nav: {
    frame: 'navFloat', body: 'navFloatBody',
    content: () => qs('.imagebar-nav'),
    parent: () => qs('#dockBottom .imagebar'),
    key: 'ybe_nav_dock', select: 'navDockSel',
    visibleKey: 'ybe_nav_visible', visibleSw: 'navVisibleSw',
  },
  save: {
    frame: 'saveFloat', body: 'saveFloatBody',
    content: () => qs('.imagebar-right'),
    parent: () => qs('#dockBottom .imagebar'),
    key: 'ybe_save_dock', select: 'saveDockSel',
    visibleKey: 'ybe_save_visible', visibleSw: 'saveVisibleSw',
  },
};

// Per-widget current dock location (see DOCK_LOCATIONS), keyed by widget name.
const dockState = {};
// Per-widget visibility, keyed by widget name.
const visibleState = {};
Object.keys(WIDGETS).forEach((name) => {
  dockState[name] = 'default';
  visibleState[name] = true;
});

/**
 * Toggle the body class that reflects the control-panel side.
 */
function applyPanelSide() {
  document.body.classList.toggle('panel-left', panelSide === 'left');
}

/**
 * Settings key that stores a floating window's position.
 * @param {string} id - Floating window element id.
 * @returns {string} The settings key.
 */
function floatKey(id) { return 'ybe_float_' + id; }

/**
 * Clamp a floating window position to keep it on screen.
 * @param {HTMLElement} win - The floating window.
 * @param {number} x - Desired left position.
 * @param {number} y - Desired top position.
 * @returns {{x:number, y:number}} The clamped position.
 */
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

/**
 * Position a floating window, clamped to the viewport.
 * @param {HTMLElement} win - The floating window.
 * @param {number} x - Desired left position.
 * @param {number} y - Desired top position.
 * @returns {{x:number, y:number}} The applied position.
 */
function setFloatPos(win, x, y) {
  const p = clampFloatPos(win, x, y);
  win.style.left = p.x + 'px';
  win.style.top = p.y + 'px';
  return p;
}

/**
 * Persist a floating window's current position.
 * @param {HTMLElement} win - The floating window.
 */
function saveFloatPos(win) {
  settingsSet(floatKey(win.id), JSON.stringify({
    x: win.offsetLeft, y: win.offsetTop,
  }));
}

/**
 * Compute the default opening position for a floating window.
 * @param {HTMLElement} win - The floating window.
 * @returns {{x:number, y:number}} The default position.
 */
function defaultFloatPos(win) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  if (win.id === 'boxFloat') return { x: Math.max(20, vw - 340), y: 90 };
  // stagger the bottom-left windows so several do not open on top of each other
  const order = ['tagFloat', 'navFloat', 'saveFloat', 'actionsFloat'];
  const i = Math.max(0, order.indexOf(win.id));
  return { x: 24 + i * 28, y: Math.max(20, vh - 260 - i * 28) };
}

/**
 * Restore a floating window position from settings or fall back to default.
 * @param {HTMLElement} win - The floating window.
 */
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
/**
 * List all dockable widget names.
 * @returns {string[]} The widget names.
 */
function widgetNames() { return Object.keys(WIDGETS); }
/**
 * Resolve the widget name that owns a floating frame element.
 * @param {HTMLElement} win - The floating frame.
 * @returns {string} The widget name.
 */
function widgetNameForFrame(win) {
  const names = widgetNames();
  if (!win) return names[0];
  return names.find((n) => WIDGETS[n].frame === win.id) || names[0];
}
/**
 * Settings key for a widget's dock location.
 * @param {string} name - Widget name.
 * @returns {string} The settings key.
 */
function dockKey(name) { return WIDGETS[name].key; }
/**
 * Element id of a widget's dock-location select.
 * @param {string} name - Widget name.
 * @returns {string} The select element id.
 */
function dockSelectId(name) { return WIDGETS[name].select; }
/**
 * Get a widget's current dock location.
 * @param {string} name - Widget name.
 * @returns {string} The dock location.
 */
function getDock(name) { return dockState[name] || WIDGETS[name].defaultDock || 'default'; }
/**
 * Set a widget's in-memory dock location (no persistence or reflow).
 * @param {string} name - Widget name.
 * @param {string} loc - Dock location.
 */
function setDockState(name, loc) { dockState[name] = loc; }
/**
 * Get a widget's floating frame element.
 * @param {string} name - Widget name.
 * @returns {HTMLElement|null} The frame element.
 */
function widgetFrame(name) { return el(WIDGETS[name].frame); }
/**
 * Get a widget's floating frame body element.
 * @param {string} name - Widget name.
 * @returns {HTMLElement|null} The body element.
 */
function widgetFrameBody(name) { return el(WIDGETS[name].body); }
/**
 * Get a widget's movable content element.
 * @param {string} name - Widget name.
 * @returns {HTMLElement|null} The content element.
 */
function widgetContent(name) { return WIDGETS[name].content(); }
/**
 * Get the element a widget returns to when its location is `default`.
 * @param {string} name - Widget name.
 * @returns {HTMLElement|null} The default parent element.
 */
function widgetDefaultParent(name) { return WIDGETS[name].parent(); }
/**
 * Get the container a widget docks into for a given location.
 * @param {string} name - Widget name.
 * @param {string} loc - Dock location.
 * @returns {HTMLElement|null} The dock target element.
 */
function widgetDockTarget(name, loc) {
  if (loc === 'bottom') return el('dockBottomBody');
  if (loc === panelSide) return qs('#sidebar .sidebar-body');
  return el('dockSideBody');
}

/**
 * Show or hide the dock panels based on whether they hold visible children.
 */
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
  const imagebar = qs('#dockBottom .imagebar');
  if (bottom) bottom.classList.toggle('hidden', !hasChild(bottomBody) && !hasChild(imagebar));
}

/**
 * Move a widget's content and frame into the given dock location.
 * @param {string} name - Widget name.
 * @param {string} loc - Dock location.
 */
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

/**
 * Whether a widget is currently visible.
 * @param {string} name - Widget name.
 * @returns {boolean} True when visible.
 */
function getWidgetVisible(name) { return visibleState[name] !== false; }

/**
 * Show or hide a widget and sync its toggle.
 * @param {string} name - Widget name.
 * @param {boolean} on - New visibility.
 */
function setWidgetVisible(name, on) {
  visibleState[name] = !!on;
  settingsSet(WIDGETS[name].visibleKey, on ? '1' : '0');
  const sw = el(WIDGETS[name].visibleSw);
  if (sw) sw.checked = !!on;
  applyWidget(name);
}

/**
 * Re-place and show/hide a widget from its current state.
 * @param {string} name - Widget name.
 */
function applyWidget(name) {
  placeWidget(name, getDock(name));
  const on = getWidgetVisible(name);
  const frame = widgetFrame(name);
  const content = widgetContent(name);
  if (content) content.classList.toggle('hidden', !on);
  if (frame) frame.classList.toggle('hidden', !on || getDock(name) === 'default');
  updateDockPanels();
}

/**
 * Re-apply every widget from its current state.
 */
function applyAllWidgets() {
  widgetNames().forEach(applyWidget);
}

/**
 * Dock a widget at a new location, persisting and syncing the UI.
 * @param {string} name - Widget name.
 * @param {string} loc - New dock location.
 */
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

// ---- custom widgets (see js/widgets.js) ----------------------------------- //
/**
 * Build the floating frame for a custom widget and attach it to the page.
 * @param {string} name - Widget key.
 * @param {string} title - Header title.
 * @returns {{frame: HTMLElement, body: HTMLElement, hide: HTMLElement}}
 */
function createWidgetFrame(name, title) {
  const frame = mk('div', 'float-window hidden');
  frame.id = 'widgetFrame_' + name;
  const head = mk('div', 'float-head');
  head.appendChild(mk('span', 'float-title', title || name));
  const actions = mk('div', 'float-actions');
  [['float', 'Float freely', '\u29c9'],
    ['left', 'Dock to the left panel', '\u21e4'],
    ['right', 'Dock to the right panel', '\u21e5'],
    ['bottom', 'Dock to the bottom panel', '\u2913']].forEach(([dock, tip, glyph]) => {
    const b = mk('button', 'float-dock', glyph);
    b.type = 'button';
    b.dataset.dock = dock;
    b.title = tip;
    actions.appendChild(b);
  });
  const hide = mk('button', 'float-close', '\u00d7');
  hide.type = 'button';
  hide.title = 'Hide this widget';
  actions.appendChild(hide);
  head.appendChild(actions);
  frame.appendChild(head);
  const body = mk('div', 'float-body');
  body.id = 'widgetBody_' + name;
  frame.appendChild(body);
  document.body.appendChild(frame);
  return { frame, body, hide };
}

/**
 * Register a custom widget in the dock system. A custom widget has no built-in
 * default spot, so it starts floating and its close button hides it.
 * @param {string} name - Widget key.
 * @param {object} def - {frame, body, content, select, visibleSw}.
 * @returns {void}
 */
function registerWidget(name, def) {
  const key = 'ybe_widget_' + name + '_dock';
  const visibleKey = 'ybe_widget_' + name + '_visible';
  const defaultDock = DOCK_LOCATIONS.includes(def.defaultDock) && def.defaultDock !== 'default'
    ? def.defaultDock : 'float';
  WIDGETS[name] = {
    frame: def.frame.id,
    body: def.body.id,
    content: () => def.content,
    parent: () => null,
    key,
    select: def.select,
    visibleKey,
    visibleSw: def.visibleSw,
    defaultDock,
    noDefault: true,
  };
  const saved = settingsGet(key);
  dockState[name] = DOCK_LOCATIONS.includes(saved) && saved !== 'default' ? saved : defaultDock;
  visibleState[name] = settingsGet(visibleKey) !== '0';
  initFloatWindow(def.frame);
  applyWidget(name);
}

/**
 * Remove a previously registered custom widget and its frame.
 * @param {string} name - Widget key.
 * @returns {void}
 */
function unregisterWidget(name) {
  const w = WIDGETS[name];
  if (!w) return;
  const frame = el(w.frame);
  const content = w.content();
  if (content && content.parentElement) content.parentElement.removeChild(content);
  if (frame && frame.parentElement) frame.parentElement.removeChild(frame);
  delete WIDGETS[name];
  delete dockState[name];
  delete visibleState[name];
  updateDockPanels();
}

// ---- panel resizers ------------------------------------------------------- //
/**
 * Clamp and apply the dock-side panel width.
 * @param {number} w - Desired width in pixels.
 * @returns {number} The clamped width in pixels.
 */
function applyDockSideWidth(w) {
  const clamped = Math.min(DOCK_SIDE_MAX, Math.max(DOCK_SIDE_MIN, Math.round(w)));
  const panel = el('dockSide');
  if (panel) panel.style.setProperty('--dock-side-w', clamped + 'px');
  return clamped;
}

/**
 * Clamp and apply the bottom dock panel height.
 * @param {number} h - Desired height in pixels.
 * @returns {number} The clamped height in pixels.
 */
function applyDockBottomHeight(h) {
  const max = Math.max(DOCK_BOTTOM_MIN, window.innerHeight - 160);
  const clamped = Math.min(max, Math.max(DOCK_BOTTOM_MIN, Math.round(h)));
  const body = el('dockBottomBody');
  if (body) body.style.setProperty('--dock-bottom-h', clamped + 'px');
  return clamped;
}

/**
 * Wire up pointer dragging for the side and bottom dock resizers.
 */
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

/**
 * Wire up dragging, docking and closing for a floating widget window.
 * @param {HTMLElement} win - The floating window element.
 */
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
  if (closeBtn) {
    // A custom widget has no built-in "default" spot, so its close button hides
    // it instead of docking it back to a home it does not have.
    closeBtn.addEventListener('click', () => {
      if (WIDGETS[name] && WIDGETS[name].noDefault) setWidgetVisible(name, false);
      else setWidgetDock(name, 'default');
    });
  }
  window.addEventListener('resize', () => {
    if (getDock(name) === 'float') setFloatPos(win, win.offsetLeft, win.offsetTop);
  });
}

/**
 * Sync the canvas overlay toolbar buttons to the current canvas state: the
 * pressed state of the view toggles, the draw-on-top mode, and which buttons are
 * disabled (read-only / no boxes / no image).
 * @returns {void}
 */
function syncCanvasToolbar() {
  const pressed = (id, on) => {
    const b = el(id);
    if (b) b.setAttribute('aria-pressed', on ? 'true' : 'false');
  };
  pressed('ctDetails', boxDetailsVisible);
  pressed('ctIsolate', isolateSelected);
  pressed('ctShowBoxes', boxesVisible);
  pressed('ctForceDraw', forceDrawMode);
  const toolbar = el('canvasToolbar');
  if (toolbar) toolbar.classList.toggle('hidden', currentIndex < 0);
  const setDisabled = (id, off) => { const b = el(id); if (b) b.disabled = off; };
  setDisabled('ctNewBox', readonly);
  setDisabled('ctSelectAll', readonly || !boxes.length);
  setDisabled('ctForceDraw', readonly);
}

/**
 * Wire the mouse-only canvas overlay toolbar. Each button drives the same code
 * path as its keyboard shortcut, so both input methods stay in sync.
 * @returns {void}
 */
function buildCanvasToolbar() {
  const on = (id, fn) => { const b = el(id); if (b) b.addEventListener('click', fn); };
  on('ctNewBox', () => newBox());
  on('ctSelectAll', () => selectAllBoxes());
  on('ctDetails', () => toggleBoxDetails());
  on('ctIsolate', () => toggleIsolateBox());
  on('ctShowBoxes', () => toggleShowBoxes());
  on('ctForceDraw', () => toggleForceDrawMode());
  syncCanvasToolbar();
}

/**
 * Sync the appearance controls (panel side, dock selects, visibility toggles).
 */
function setAppearanceControls() {
  el('panelSideSel').value = panelSide;
  widgetNames().forEach((name) => {
    const sel = el(dockSelectId(name));
    if (sel) sel.value = getDock(name);
    const sw = el(WIDGETS[name].visibleSw);
    if (sw) sw.checked = getWidgetVisible(name);
  });
}

/**
 * Read a persisted dock location, falling back to `default`.
 * @param {string} key - Settings key.
 * @returns {string} The saved dock location.
 */
function savedDock(key) {
  const raw = settingsGet(key);
  return DOCK_LOCATIONS.includes(raw) ? raw : 'default';
}

/**
 * Read a persisted visibility flag (missing means visible).
 * @param {string} key - Settings key.
 * @returns {boolean} True when visible.
 */
function savedVisible(key) {
  return settingsGet(key) !== '0';
}

/**
 * Load persisted appearance state, migrate legacy settings and wire controls.
 */
function initAppearance() {
  panelSide = settingsGet(PANEL_SIDE_KEY) === 'right' ? 'right' : 'left';
  widgetNames().forEach((name) => {
    dockState[name] = savedDock(dockKey(name));
    visibleState[name] = savedVisible(WIDGETS[name].visibleKey);
  });
  // migrate the old "detach into a floating window" checkbox
  const boxesKey = dockKey('boxes');
  if (settingsGet(boxesKey) === null && localStorage.getItem(LEGACY_DETACH_BOXES_KEY) === '1') dockState.boxes = 'float';
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

  forceDrawMode = settingsGet(FORCE_DRAW_MODE_KEY) === '1';
  buildCanvasToolbar();

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

/**
 * Select a box from the side panel and refresh the canvas. Ctrl+click toggles
 * the box in the selection.
 * @param {number} i - Box index.
 * @param {MouseEvent} [e] - The click event (for the Ctrl/Meta modifier).
 */
function selectFromPanel(i, e) {
  closeClassPicker();
  if (e && (e.ctrlKey || e.metaKey)) toggleBoxSelection(i);
  else selectOnlyBox(i);
  justDrawn = false;
  syncClassSelect(selected);
  draw();
}

/**
 * Set an input's value unless the user is currently editing it.
 * @param {HTMLInputElement} f - The input element.
 * @param {string} val - The value to set.
 */
function setFieldValue(f, val) {
  if (!f) return;
  if (document.activeElement !== f) f.value = val;
}

/**
 * Build a class select or numeric point input for a side-panel box row.
 * @param {string} tag - `select` or `input`.
 * @param {string} cls - CSS class list.
 * @param {{value?:string}} [opts] - Optional initial value for inputs.
 * @returns {HTMLElement} The created control.
 */
function makeRowControl(tag, cls, opts) {
  const c = mk(tag, cls);
  if (tag === 'select') {
    classes.forEach((name, k) => c.appendChild(option(k, `${k}: ${name}`)));
  } else {
    c.type = 'number';
    c.step = '0.001';
    c.min = '0';
    c.max = '1';
    c.value = opts && opts.value !== undefined ? opts.value : '';
  }
  return c;
}

/**
 * Render the side-panel list of boxes.
 */
function renderSidePanel() {
  const list = el('boxList');
  if (!list) return;
  el('sidePanelCount').textContent = boxes.length;
  list.innerHTML = '';
  boxes.forEach((b, i) => {
    const row = mk('div', 'box-row');
    row.dataset.index = i;

    const idx = mk('span', 'box-row-idx', i);

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

    const fix = mk('button', 'box-row-ctl box-row-fix', 'F');
    fix.type = 'button';
    fix.title = 'Fix / unfix this box (F) — fixed boxes ignore dragging';

    const del = mk('button', 'box-row-ctl box-row-del danger', '\u00d7');
    del.type = 'button';
    del.title = 'Delete box';

    const top = mk('div', 'box-row-top');
    top.append(idx, cls, fix, del);

    const bottom = mk('div', 'box-row-bottom');
    bottom.append(ptCx, ptCy, ptW, ptH);

    row.append(top, bottom);

    row.addEventListener('click', (e) => {
      if (e.target.closest('select, input, button')) return;
      selectFromPanel(i, e);
    });
    cls.addEventListener('change', () => {
      if (readonly) return;
      pushUndo();
      // a change on a selected row applies to the whole selection
      const targets = isBoxSelected(i) ? selectionIndices() : [i];
      for (const k of targets) boxes[k].class = parseInt(cls.value, 10);
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
      afterBoxRemoved(i);
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

/**
 * Refresh selection, fixed state and field values for one side-panel row.
 * @param {HTMLElement} row - The `.box-row` element.
 * @param {number} i - Box index this row shows.
 */
function updateSidePanelRow(row, i) {
  const b = boxes[i];
  if (!b) return;
  const on = i === selected && !readonly;
  row.classList.toggle('selected', isBoxSelected(i));
  row.classList.toggle('fixed', !!b.fixed);
  const idx = row.querySelector('.box-row-idx');
  if (idx) idx.textContent = i;
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
}

/**
 * Refresh selection, fixed state and field values for the side-panel rows.
 */
function updateSidePanelState() {
  const list = el('boxList');
  if (!list) return;
  el('sidePanelCount').textContent = boxes.length;
  Array.from(list.children).forEach((row, i) => updateSidePanelRow(row, i));
}

/**
 * Re-render the side-panel list only when its length changed, else update it.
 * Called from the full `draw()`, i.e. after an interaction finishes.
 */
function syncSidePanel() {
  const list = el('boxList');
  if (!list) return;
  if (list.children.length !== boxes.length) {
    renderSidePanel();
    return;
  }
  updateSidePanelState();
}
