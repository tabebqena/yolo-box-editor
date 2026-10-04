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

let panelSide = 'left';

// The dockable widgets. `default` puts the content back where it lives in the
// markup; the other locations are the floating window or an edge panel.
const WIDGETS = {
  tags: {
    frame: 'tagFloat', body: 'tagFloatBody',
    content: () => el('tagBar'),
    parent: () => qs('#dockBottom .imagebar'),
    key: 'ybe_tags_dock', select: 'tagsDockSel',
    visibleKey: 'ybe_tags_visible', visibleSw: 'tagsVisibleSw',
  },
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
  if (loc === panelSide) return qs('#sidebar .sidebar-body');
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
  const imagebar = qs('#dockBottom .imagebar');
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
  panelSide = settingsGet(PANEL_SIDE_KEY) === 'right' ? 'right' : 'left';
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
