// app/static/js/editing.js — undo/redo, save, dataset, user actions, class picker, side panel
'use strict';

// ------------------------------------------------------------------------- //
// actions
// ------------------------------------------------------------------------- //
function snapshot() {
  return { boxes: boxes.map((b) => ({ ...b })), tags: [...imageTags] };
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

// Apply a history snapshot to the current image. Shared by undo/redo; the
// caller has already moved the snapshot between the two stacks.
function applySnapshot(snap, label) {
  boxes = snap.boxes;
  imageTags = snap.tags;
  selected = -1;
  justDrawn = false;
  markDirty();
  syncClassSelect(-1);
  updateHistoryButtons();
  renderTagBar();
  dbg(label, { boxes: boxes.length, tags: imageTags.length,
    undo: undoStack.length, redo: redoStack.length });
  draw();
}

function undo() {
  if (readonly || !undoStack.length) return;
  redoStack.push(snapshot());
  applySnapshot(undoStack.pop(), 'undo');
}

function redo() {
  if (readonly || !redoStack.length) return;
  undoStack.push(snapshot());
  applySnapshot(redoStack.pop(), 'redo');
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
    const res = await fetch('/api/annotations' + keyQuery(images[currentIndex]), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ boxes, tags: imageTags }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      dirty = false;
      ok = true;
      if (Array.isArray(data.available_tags)) availableTags = data.available_tags;
      dbg('save ok', { index: currentIndex, count: data.count, tags: data.tags_count });
      if (!opts.silent) toast(`Saved ${data.count} box(es)`, { type: 'success' });
      renderTagBar();
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

// Busy state for the chain apply/clear: show a spinner on Apply and block both
// buttons until the request + config reload finish.
function setFilterApplying(on) {
  const apply = el('filterPanelApply');
  const clear = el('filterPanelClear');
  if (apply) {
    apply.classList.toggle('is-loading', on);
    apply.disabled = on;
  }
  if (clear) clear.disabled = on;
}

async function applyFilterChain(names) {
  const anchor = captureImageAnchor(false);
  setFilterApplying(true);
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
      closeSettingsModal();
    } else {
      dbgWarn('filter failed', { status: res.status, error: data.error });
      toast(data.error || 'Filter failed', { type: 'error' });
      populateFilterPanel(); // revert the panel to the active chain
    }
  } catch (err) {
    dbgWarn('filter error', err);
    toast('Error: ' + err.message, { type: 'error' });
    populateFilterPanel();
  } finally {
    setFilterApplying(false);
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
  openModal('actionResult');
}

function closeActionResult() {
  closeModal('actionResult');
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

function postActionRun(body) {
  return postJson('/api/actions/run', body);
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
  classPicker.appendChild(mk('div', 'picker-title', 'Choose class'));

  classes.forEach((name, i) => {
    const btn = mk('button', null, `${i}: ${name}`);
    btn.addEventListener('click', () => {
      if (selected >= 0) {
        const wasJustDrawn = justDrawn;
        if (!wasJustDrawn) pushUndo();
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

  openModal('classPicker');
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
  closeModal('classPicker');
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
