// app/static/js/editing.js — undo/redo, save, dataset, user actions, class picker, side panel
'use strict';

// ------------------------------------------------------------------------- //
// actions
// ------------------------------------------------------------------------- //
/**
 * Capture the current boxes for the undo/redo history.
 * @returns {{boxes: Array<object>}} A copy of the current state.
 */
function snapshot() {
  return { boxes: boxes.map((b) => ({ ...b })) };
}

/**
 * Enable or disable the undo, redo and save buttons from the current state.
 */
function updateHistoryButtons() {
  const undo = el('undoBtn');
  const redo = el('redoBtn');
  const save = el('saveBtn');
  if (undo) undo.disabled = readonly || !undoStack.length;
  if (redo) redo.disabled = readonly || !redoStack.length;
  if (save) save.disabled = readonly || !dirty || currentIndex < 0;
}

/**
 * Snapshot the current image, push it onto the undo stack and clear redo.
 */
function pushUndo() {
  undoStack.push(snapshot());
  if (undoStack.length > 100) undoStack.shift();
  redoStack = [];
  updateHistoryButtons();
}

/**
 * Apply a history snapshot to the current image. Shared by undo/redo; the
 * caller has already moved the snapshot between the two stacks.
 * @param {{boxes: Array<object>}} snap - The snapshot to restore.
 * @param {string} label - Debug label for the source of the change.
 */
function applySnapshot(snap, label) {
  boxes = snap.boxes;
  clearBoxSelection();
  justDrawn = false;
  markDirty();
  syncClassSelect(-1);
  updateHistoryButtons();
  dbg(label, { boxes: boxes.length,
    undo: undoStack.length, redo: redoStack.length });
  draw();
}

/**
 * Restore the previous snapshot from the undo stack, if any.
 */
function undo() {
  if (readonly || !undoStack.length) return;
  redoStack.push(snapshot());
  applySnapshot(undoStack.pop(), 'undo');
}

/**
 * Reapply the next snapshot from the redo stack, if any.
 */
function redo() {
  if (readonly || !redoStack.length) return;
  undoStack.push(snapshot());
  applySnapshot(redoStack.pop(), 'redo');
}

/**
 * Delete every selected box and record the change.
 */
function deleteSelected() {
  const indices = selectionIndices();
  if (!indices.length) return;
  // A single box is quick to redo; a whole selection is worth confirming.
  if (indices.length > 1 && !confirm(`Delete ${indices.length} boxes?`)) return;
  pushUndo();
  // delete from the highest index down so the lower indices stay valid
  for (let k = indices.length - 1; k >= 0; k--) boxes.splice(indices[k], 1);
  dbg('boxes deleted', { indices, remaining: boxes.length });
  clearBoxSelection();
  justDrawn = false;
  markDirty();
  draw();
  updateHistoryButtons();
  runHook('on_box_deleted');
}

/**
 * Fix / unfix every selected box. A fixed box ignores dragging (moving and
 * resizing) but can still be clicked / selected and deleted. The flag is
 * transient UI state: it is never saved and is cleared when the image changes.
 */
function toggleFixSelected() {
  if (readonly || selected < 0) return;
  const fixed = !boxes[selected].fixed; // apply the primary's new state to all
  for (const i of selectionIndices()) boxes[i].fixed = fixed;
  draw();
  updateSidePanelState();
}

/**
 * Mark the labels as changed and, when auto-save is on, queue a save.
 */
function markDirty() {
  dirty = true;
  scheduleAutoSave();
  emitUiEvent('boxes_changed', {});
}

/**
 * Queue an auto-save after the debounce delay when auto-save is enabled.
 */
function scheduleAutoSave() {
  if (!autoSave || readonly || currentIndex < 0) return;
  clearTimeout(autoSaveTimer);
  autoSaveTimer = setTimeout(() => { autoSaveTimer = null; save({ silent: true }); }, AUTO_SAVE_DELAY);
}

// Save any pending auto-save now (used before navigating away).
/**
 * Save any pending auto-save now (used before navigating away).
 * @returns {Promise<boolean>} True when there was nothing to save or it succeeded.
 */
async function flushAutoSave() {
  if (autoSaveTimer) {
    clearTimeout(autoSaveTimer);
    autoSaveTimer = null;
  }
  if (!dirty || readonly) return true;
  return save({ silent: true });
}

/**
 * Save the current image's boxes and tags to the server.
 * @param {{silent?:boolean}} [opts] - `silent` suppresses the success toast (used by auto-save).
 * @returns {Promise<boolean>} True when the write succeeded, false when it failed or a hook cancelled it.
 */
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
    const { res, data } = await apiPost(
      '/api/annotations' + keyQuery(images[currentIndex]),
      { boxes });
    if (res.ok && data.ok) {
      dirty = false;
      ok = true;
      dbg('save ok', { index: currentIndex, count: data.count });
      if (!opts.silent) toast(`Saved ${data.count} box(es)`, { type: 'success' });
      updateHistoryButtons();
      emitUiEvent('saved', { count: data.count });
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

/**
 * Load a dataset from a data.yaml path and refresh the UI.
 * @param {string} rawPath - Path to the data.yaml file.
 */
async function loadDataset(rawPath) {
  const yamlPath = (rawPath || '').trim();
  if (!yamlPath) {
    toast('Enter the path to a data.yaml', { type: 'warning' });
    return;
  }
  try {
    const { res, data } = await apiPost('/api/data', { data_yaml: yamlPath });
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

/**
 * Load the dataset typed into the main path field.
 * @returns {Promise<void>} Resolves when the load attempt finishes.
 */
function setDataYaml() {
  return loadDataset(el('dataYaml').value);
}

/**
 * Load the dataset typed into the load-data modal field.
 * @returns {Promise<void>} Resolves when the load attempt finishes.
 */
function loadDataFromModal() {
  return loadDataset(el('loadDataYaml').value);
}

/**
 * Busy state for the split controls: show a spinner and block the select and
 * the reload button while a split change (which may re-run the active filter
 * chain) or a manual image reload is in flight.
 * @param {boolean} on - Whether a split-list request is running.
 */
function setSplitBusy(on) {
  const spinner = el('splitSpinner');
  if (spinner) spinner.classList.toggle('hidden', !on);
  const sel = el('splitSelect');
  if (sel) sel.disabled = on;
  const reload = el('splitReloadBtn');
  if (reload) reload.disabled = on;
}

/**
 * Re-fetch the image list for the active split and filter chain. Re-scans the
 * image folders and re-runs the chain (POST /api/images/rescan), then keeps the
 * current image by path.
 * @returns {Promise<void>}
 */
async function reloadSplitImages() {
  setSplitBusy(true);
  try {
    await reloadImagesList('/api/images/rescan', { method: 'POST' },
      'split_reload', 'reload');
  } finally {
    setSplitBusy(false);
  }
}

/**
 * Switch to a dataset split (or all splits) on the server.
 * @param {string|null} split - Split name, or null for all splits.
 */
async function setSplit(split) {
  setSplitBusy(true);
  try {
    const { res, data } = await apiPost('/api/split', { split: split || null });
    if (res.ok && data.ok) {
      dbg('split changed', { split: split || null });
      // skip the view restore: the split just set is authoritative, otherwise a
      // stale remembered split would immediately switch it back (e.g. choosing
      // "All splits" after a specific one). Resume the per-split last image.
      await loadConfig(0, { skipFilterRestore: true });
    } else {
      dbgWarn('split switch failed', { status: res.status, error: data.error });
      toast(data.error || 'Split switch failed', { type: 'error' });
      populateSplitSelect(); // revert the select to the server's active split
    }
  } catch (err) {
    dbgWarn('split switch error', err);
    toast('Error: ' + err.message, { type: 'error' });
    populateSplitSelect();
  } finally {
    setSplitBusy(false);
  }
}

/**
 * Busy state for the chain apply/clear: show a spinner on Apply and block both
 * buttons until the request + config reload finish.
 * @param {boolean} on - Whether a filter chain is being applied.
 */
function setFilterApplying(on) {
  const apply = el('filterPanelApply');
  const clear = el('filterPanelClear');
  if (apply) {
    apply.classList.toggle('is-loading', on);
    apply.disabled = on;
  }
  if (clear) clear.disabled = on;
}

/**
 * Apply a filter chain by name and reload the dataset.
 * @param {string[]} names - Filter names to run, top to bottom.
 */
async function applyFilterChain(names) {
  const anchor = captureImageAnchor(false);
  setFilterApplying(true);
  try {
    const { res, data } = await apiPost('/api/filter', { filters: names || [] });
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
/**
 * Write text into a result field, toggling its empty style.
 * @param {string} id - Element id.
 * @param {string} text - Text to display.
 * @param {boolean} [emptyClass] - Optional flag forwarded for the empty style.
 */
function setResultText(id, text, emptyClass) {
  const node = el(id);
  node.textContent = text || '';
  node.classList.toggle('modal-empty', !text);
}

/**
 * Show the result of a user action in the result modal.
 * @param {object} data - The backend action response.
 */
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

/**
 * Close the action result modal.
 */
function closeActionResult() {
  closeModal('actionResult');
}

/**
 * Run one user action (or event hook) on the current image. `confirm: false`
 * skips the confirmation prompt — hooks run automatically. The backend owns the
 * steps + after_success chain and pauses whenever an app action is needed: it
 * returns `client_action` + a `uid`, which we run and report back.
 * @param {string} name - Action or hook name.
 * @param {{confirm?:boolean, hook?:boolean}} [opts] - `confirm` and `hook` flags.
 * @returns {Promise<boolean>} True when the whole run succeeded, false on failure.
 */
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
      toast(`"${name}" failed: ${data.error || data.stderr || 'see console'}`, { type: 'error' });
      console.error(`[user action] "${name}" failed:`, {
        exit_code: data.exit_code,
        command: data.command,
      });
      return false;
    }
    console.log(`[user action] "${name}" succeeded`, data);
    return true;
  } catch (err) {
    dbgWarn(`"${name}" request error`, err);
    toast(`"${name}" failed: ${err.message}`, { type: 'error' });
    return false;
  } finally {
    setActionButtonsDisabled(readonly);
  }
}

/**
 * POST to the action-run endpoint and return the parsed response.
 * @param {object} body - Request body (action+target, or uid+result).
 * @returns {Promise<object>} The parsed action response.
 */
function postActionRun(body) {
  return postJson('/api/actions/run', body);
}

/**
 * Fire an event hook if it is defined and an image is loaded. No-op otherwise.
 * The in-flight guard keeps a hook from re-entering itself (e.g. a hook whose
 * after_success refreshes the image list, which would fire it again).
 * @param {string} name - Hook event name (e.g. `on_before_save`).
 * @returns {Promise<boolean>} True when the hook succeeded or was skipped.
 */
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
// The class-picker popup element, shown after drawing a new box.
const classPicker = el('classPicker');

/**
 * Open the class picker popup near the given screen coordinates.
 * @param {number} x - Screen x position.
 * @param {number} y - Screen y position.
 */
function openClassPicker(x, y) {
  classPicker.innerHTML = '';
  classPicker.appendChild(mk('div', 'picker-title', 'Choose class'));

  classes.forEach((name, i) => {
    const btn = mk('button', null, `${i}: ${name}`);
    btn.addEventListener('click', () => {
      if (selected >= 0) {
        const wasJustDrawn = justDrawn;
        if (!wasJustDrawn) pushUndo();
        // apply to every selected box, not just the primary
        for (const k of selectionIndices()) boxes[k].class = i;
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

  // Keyboard: Arrow keys move between classes, Enter picks the focused one,
  // digits pick directly, Escape closes (see ESCAPE_CLOSERS).
  const buttons = qsa('button', classPicker);
  classPicker.onkeydown = (ev) => {
    if (!buttons.length) return;
    const cur = buttons.indexOf(document.activeElement);
    if (ev.key === 'ArrowDown') {
      ev.preventDefault();
      buttons[(cur < 0 ? 0 : cur + 1) % buttons.length].focus();
    } else if (ev.key === 'ArrowUp') {
      ev.preventDefault();
      buttons[(cur <= 0 ? buttons.length : cur) - 1].focus();
    } else if (ev.key === 'Home') {
      ev.preventDefault();
      buttons[0].focus();
    } else if (ev.key === 'End') {
      ev.preventDefault();
      buttons[buttons.length - 1].focus();
    } else if (/^[0-9]$/.test(ev.key)) {
      const k = parseInt(ev.key, 10);
      if (k < buttons.length) { ev.preventDefault(); buttons[k].click(); }
    }
  };

  openModal('classPicker');
  if (buttons[0]) buttons[0].focus();
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

/**
 * Open the class picker centred on the currently selected box.
 */
function openPickerForSelectedBox() {
  if (selected < 0) return;
  const r = toPx(boxes[selected]);
  const rect = canvas.getBoundingClientRect();
  const sx = rect.left + (r.x + r.w / 2) * (rect.width / canvas.width);
  const sy = rect.top + (r.y + r.h / 2) * (rect.height / canvas.height);
  openClassPicker(sx, sy);
}

/**
 * Close the class picker popup.
 */
function closeClassPicker() {
  closeModal('classPicker');
}

// ------------------------------------------------------------------------- //
// left sidebar: resizable, collapsible body (the header row stays visible)
// ------------------------------------------------------------------------- //
// Whether the left sidebar is currently expanded.
let sidePanelOpen = true;

/**
 * Round a normalized coordinate to four decimals for display.
 * @param {number} v - Value to round.
 * @returns {number} The rounded value.
 */
function fmtNum(v) {
  return Math.round(v * 10000) / 10000;
}

// Sidebar resize bounds (px) and the settings key that remembers the width.
const SIDEBAR_MIN = 220;
const SIDEBAR_MAX = 720;
const SIDEBAR_W_KEY = 'ybe_side_panel_w';

/**
 * Clamp and apply the sidebar width, returning the applied pixel value.
 * @param {number} w - Desired width in pixels.
 * @returns {number} The clamped width in pixels.
 */
function applySidePanelWidth(w) {
  const clamped = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, Math.round(w)));
  el('sidebar').style.setProperty('--sidebar-w', clamped + 'px');
  return clamped;
}

/**
 * Wire up pointer dragging on the sidebar resize handle.
 */
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

/**
 * Restore the sidebar open state, width and toggle, and init its resizer.
 */
function initSidePanel() {
  sidePanelOpen = settingsGet('sidePanelOpen') !== '0';
  toggleSidePanel(sidePanelOpen, false);
  const saved = parseInt(settingsGet(SIDEBAR_W_KEY) || '', 10);
  if (saved) applySidePanelWidth(saved);
  el('sidePanelToggle').addEventListener('click', () => toggleSidePanel());
  initSidePanelResizer();
}

/**
 * Show or hide the sidebar, optionally persisting the choice.
 * @param {boolean} [show] - Force a state; toggles when omitted.
 * @param {boolean} [persist=true] - Whether to save the state to settings.
 */
function toggleSidePanel(show, persist = true) {
  const open = show !== undefined ? !!show : !sidePanelOpen;
  sidePanelOpen = open;
  el('sidebar').classList.toggle('collapsed', !open);
  el('sidePanelToggle').classList.toggle('active', open);
  if (persist) settingsSet('sidePanelOpen', open ? '1' : '0');
}
