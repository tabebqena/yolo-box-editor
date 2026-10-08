// app/static/js/events.js — event wiring, image-list reload, shortcut handlers, initSettings
'use strict';

// Escape closes the topmost open overlay, in this priority order.
const ESCAPE_CLOSERS = [
  ['helpModal', closeHelp],
  ['yamlEditorModal', closeYamlEditor],
  ['actionResult', closeActionResult],
  ['changelogModal', closeChangelog],
  ['tipModal', closeTipModal],
  ['loadDataModal', closeLoadDataModal],
  ['settingsModal', closeSettingsModal],
  ['updateModal', closeUpdateModal],
  ['notifPanel', () => toggleNotifPanel(false)],
];

// ------------------------------------------------------------------------- //
// canvas interaction (draw / move / resize)
// ------------------------------------------------------------------------- //

/**
 * Handle a mousedown on the canvas: select a box, start moving/resizing it,
 * delete or change a box, or draw a new one.
 * @param {MouseEvent} e
 * @returns {void}
 */
function onCanvasMouseDown(e) {
  closeClassPicker();
  if (!imgW || !imgH || readonly) return;
  const p = canvasPos(e);
  mouse = p;
  dragUndoPushed = false; // a new drag starts its own undo snapshot
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
}

/**
 * Track the cursor on window (not just the canvas) so a drag that leaves the
 * image still completes on release instead of losing the box.
 * @param {MouseEvent} e
 * @returns {void}
 */
function onWindowMouseMove(e) {
  const p = canvasPos(e);
  if (mode === 'drawing' && start) {
    mouse = clampToImage(p);
    drawFast(); // no box changed: cached layer + the in-progress rectangle
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
}

/**
 * Finish a drag: commit a newly drawn box or the moved/resized one, then reset
 * the interaction mode.
 * @param {MouseEvent} e
 * @returns {void}
 */
function onWindowMouseUp(e) {
  const edited = (mode === 'moving' || mode === 'resizing') && moved;
  let created = false;
  if (mode === 'drawing' && start) {
    const r = normRect(start, clampToImage(mouse || start));
    if (r.w >= 3 && r.h >= 3) {
      const nb = toNorm(r);
      nb.class = defaultClass;
      pushUndo();
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
}

// ------------------------------------------------------------------------- //
// image list reload + app shortcut actions
// ------------------------------------------------------------------------- //

/**
 * Fetch a fresh image list and apply it, keeping the current image by path.
 * `url` is the endpoint (GET) or an endpoint plus a fetch init.
 * @param {string} url
 * @param {RequestInit|undefined} init
 * @param {string} tag Console tag for errors.
 * @param {string} label Human-readable action name for messages.
 * @returns {Promise<void>}
 */
async function reloadImagesList(url, init, tag, label) {
  const anchor = captureImageAnchor();
  dbg(`${label} images list`, { was: images.length, index: currentIndex,
    anchor: anchor && anchor.path });
  try {
    const res = await fetch(url, init);
    const data = await res.json();
    if (!data.ok) {
      console.error(`[${tag}] ${label} failed`, data);
      return;
    }
    applyImagesPayload(data, anchor, label);
  } catch (err) {
    console.error(`[${tag}] failed:`, err);
  }
}

// Move the box selection by `delta` (+1 next, -1 prev), wrapping around. When
// no box is selected yet it resumes from the last active one. Shared by the
// key-bound app_sel_box and the hook-callable app_select_next_box/prev_box.
function selectRelativeBox(delta) {
  if (!boxes.length) return;
  if (selected < 0) {
    selected = Math.min(Math.max(lastSelected, 0), boxes.length - 1);
  } else {
    selected = (selected + delta + boxes.length) % boxes.length;
  }
  justDrawn = false;
  syncClassSelect(selected);
  draw();
}

// Map of app action name -> handler; keys must cover every app_* name in
// config.APP_ACTIONS. APP_SHORTCUT_ORDER additionally lists the ones bound to
// keys by default (the openers below and the trailing hook-only actions).
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
      // creation pushed an undo snapshot; dropping the new box returns to it
      if (undoStack.length) undoStack.pop();
      redoStack = [];
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
    selectRelativeBox(1);
  },
  app_select_next_box: (e) => { e.preventDefault(); selectRelativeBox(1); },
  app_select_prev_box: (e) => { e.preventDefault(); selectRelativeBox(-1); },
  app_clear_tags: () => {
    if (readonly || currentIndex < 0 || !imageTags.length) return;
    pushUndo();
    imageTags = [];
    markDirty();
    renderTagBar();
  },
  // Copy the previous image's boxes and tags onto the current one. The action
  // is opt-in (a hook/action step), so no-op quietly on the first image.
  app_copy_labels_from_prev: async () => {
    if (readonly || currentIndex <= 0) return;
    const prev = images[currentIndex - 1];
    const data = await apiGetOrNull('/api/annotations' + keyQuery(prev));
    if (!data) throw new Error('could not read previous annotations');
    pushUndo();
    boxes = Array.isArray(data.boxes) ? data.boxes.map((b) => ({ ...b })) : [];
    imageTags = Array.isArray(data.tags) ? [...data.tags] : [];
    selected = -1;
    justDrawn = false;
    markDirty();
    syncClassSelect(-1);
    renderTagBar();
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
  app_box_details: (e) => {
    e.preventDefault();
    boxDetailsVisible = !boxDetailsVisible;
    settingsSet(SHOW_BOX_DETAILS_KEY, boxDetailsVisible ? '1' : '0');
    draw();
  },
  // Hide every box but the selected one (needs a selection to take effect; with
  // none selected all boxes stay visible). Hidden boxes are not hit-tested.
  app_isolate_box: (e) => {
    e.preventDefault();
    isolateSelected = !isolateSelected;
    settingsSet(ISOLATE_BOX_KEY, isolateSelected ? '1' : '0');
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
  app_refresh_images_list: (e) => {
    e.preventDefault();
    return reloadImagesList('/api/images/rescan', { method: 'POST' },
      'app_refresh_images_list', 'rescan');
  },
  // Re-read the server's current list *without* touching the disk: use after a
  // `backend_*` action already re-scanned it (e.g. Archive's
  // `backend_rescan_images`). Keeps the same image by path; no extra disk scan.
  app_reload_images_list: (e) => {
    e.preventDefault();
    return reloadImagesList('/api/images', undefined,
      'app_reload_images_list', 'reload');
  },
  // Re-fetch the current image from the server (cache-busted); e.g. after an
  // external editor wrote a new version of the file.
  app_refresh_image: (e) => {
    e.preventDefault();
    if (currentIndex < 0) { dbg('refresh image skipped (no image)'); return; }
    displayImage('/api/image' + keyQuery(images[currentIndex]) + '&_=' + Date.now());
    dbg('refresh image', { index: currentIndex });
  },
  // Open the built-in help: the 3-level tutorial and the How-to recipes.
  app_help: (e) => {
    e.preventDefault();
    openHelp();
  },
};

/**
 * Apply an /api/images (GET) or /api/images/rescan (POST) payload to the client
 * list, keeping the current image by path through `anchor`.
 * @param {Object} data
 * @param {Object|null} anchor Image anchor captured before the request.
 * @param {string} label Human-readable action name for messages.
 * @returns {void}
 */
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
    resetToEmptyImage();
    return;
  }
  loadImage(resolveImageAnchor(anchor));
  runHook('on_images_list_loaded');
}

/**
 * Run an app action by name through the same path used for keyboard shortcuts,
 * so after_success hooks behave exactly like bound keys.
 * @param {string} name
 * @param {Event} [e] Original event, if any.
 * @returns {Promise<void>}
 */
async function runAppAction(name, e) {
  const handler = APP_SHORTCUT_HANDLERS[name];
  if (!handler) {
    throw new Error(`unknown app action: ${name}`);
  }
  return handler(e || { preventDefault() {} });
}

/**
 * Tab on the selected box's row: cycle class select -> cx -> cy -> w -> h.
 * @param {KeyboardEvent} e
 * @returns {boolean} True when the event was handled.
 */
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

/**
 * Esc while a side-panel row control is focused deactivates that row.
 * @param {KeyboardEvent} e
 * @returns {boolean} True when the event was handled.
 */
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

// ------------------------------------------------------------------------- //
// keyboard dispatch
// ------------------------------------------------------------------------- //

/**
 * Match a key event against the bound app shortcuts and run the first match.
 * @param {KeyboardEvent} e
 * @returns {boolean} True when an app shortcut was dispatched.
 */
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

/**
 * Test whether a key event matches a shortcut string such as "Ctrl+S".
 * @param {KeyboardEvent} e
 * @param {string} shortcut
 * @returns {boolean}
 */
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

/**
 * Match the key event against the user's action shortcuts and run the first.
 * @param {KeyboardEvent} e
 * @returns {void}
 */
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

/**
 * Global keydown entry point: close overlays, then handle app/action shortcuts
 * and tag number toggles (order matters).
 * @param {KeyboardEvent} e
 * @returns {void}
 */
function onGlobalKeyDown(e) {
  if (e.key === 'Escape') {
    for (const [id, close] of ESCAPE_CLOSERS) {
      if (!isHidden(id)) { close(); return; }
    }
  }
  // app_escape / app_sel_points must also work while typing in inputs
  const escInfo = appShortcuts['app_escape'];
  if (escInfo && shortcutMatches(e, escInfo.shortcut) && escDeactivateRow(e)) return;
  const ptsInfo = appShortcuts['app_sel_points'];
  if (ptsInfo && shortcutMatches(e, ptsInfo.shortcut) && tabCycleRow(e)) return;
  // Help opens from anywhere, even while an input or the YAML editor is focused.
  const helpInfo = appShortcuts['app_help'];
  if (helpInfo && shortcutMatches(e, helpInfo.shortcut)) {
    runAppAction('app_help', e).catch((err) => console.error('[shortcut] app_help:', err));
    return;
  }

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
}

// Guards initSettings so it only builds the appearance controls once.
let settingsInitialized = false;

/**
 * Set up the appearance controls once, after /api/config has supplied the
 * server's settings (so `settingsGet` can fall back to them). Idempotent: the
 * fallback path below and later config reloads must not re-init.
 * @returns {void}
 */
function initSettings() {
  if (settingsInitialized) return;
  settingsInitialized = true;
  initSidePanel();
  initAppearance();
  el('autoSaveSw').checked = settingsGet('autoSave') === '1';
  autoSave = el('autoSaveSw').checked;
  boxesVisible = settingsGet(SHOW_BOXES_KEY) !== '0';
  boxDetailsVisible = settingsGet(SHOW_BOX_DETAILS_KEY) !== '0';
  isolateSelected = settingsGet(ISOLATE_BOX_KEY) === '1';
  el('tipsSw').checked = settingsGet('ybe_tips_enabled') !== '0';
}

// ------------------------------------------------------------------------- //
// wiring
// ------------------------------------------------------------------------- //

/**
 * Wire the canvas mouse handlers.
 * @returns {void}
 */
function wireCanvas() {
  canvas.addEventListener('mousedown', onCanvasMouseDown);
  // window (not just the canvas): a drag that leaves the image still tracks
  // the cursor and completes on release instead of losing the box.
  window.addEventListener('mousemove', onWindowMouseMove);
  window.addEventListener('mouseup', onWindowMouseUp);
}

/**
 * Wire the prev/next, split, recent-dataset and image-jump controls.
 * @returns {void}
 */
function wireNavigation() {
  el('prevBtn').addEventListener('click', () => go(-1));
  el('nextBtn').addEventListener('click', () => go(1));
  el('splitSelect').addEventListener('change', () => setSplit(el('splitSelect').value));
  el('splitReloadBtn').addEventListener('click', reloadSplitImages);
  el('recentSelect').addEventListener('change', () => {
    const val = el('recentSelect').value;
    if (!val) return;
    el('dataYaml').value = val;
    el('recentSelect').value = '';
    setDataYaml();
  });
  el('setDataBtn').addEventListener('click', setDataYaml);
  el('tagsDirBtn').addEventListener('click', setTagsDir);
  el('tagsDirInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') setTagsDir();
  });

  const counterInput = el('counter');
  counterInput.addEventListener('focus', () => counterInput.select());
  counterInput.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    jumpToImage(counterInput.value);
    counterInput.blur();
  });
  counterInput.addEventListener('blur', () => updateNav());
}

/**
 * Wire the save/undo/redo, auto-save and class-select controls.
 * @returns {void}
 */
function wireEditingControls() {
  el('saveBtn').addEventListener('click', () => save());
  el('undoBtn').addEventListener('click', undo);
  el('redoBtn').addEventListener('click', redo);
  el('autoSaveSw').addEventListener('change', (e) => {
    autoSave = e.target.checked;
    settingsSet('autoSave', autoSave ? '1' : '0');
    if (autoSave) scheduleAutoSave(); // save what is already pending
    else clearTimeout(autoSaveTimer);
  });
  el('actionResultClose').addEventListener('click', closeActionResult);

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
}

/**
 * Wire the tag bar: add/submit, expand and input keyboard handling.
 * @returns {void}
 */
function wireTags() {
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
}

/**
 * Wire the update-check button and update modal.
 * @returns {void}
 */
function wireUpdates() {
  el('updateCheckBtn').addEventListener('click', () => {
    el('updateStatus').textContent = 'Checking…';
    refreshUpdateInfo(true);
  });
  el('updateHowBtn').addEventListener('click', openUpdateModal);
  el('updateModalClose').addEventListener('click', closeUpdateModal);
  bindModalBackdrop('updateModal', closeUpdateModal);
}

/**
 * Wire the settings modal: tabs, shortcuts, actions and filters.
 * @returns {void}
 */
function wireSettings() {
  el('settingsBtn').addEventListener('click', openSettingsModal);
  el('settingsModalClose').addEventListener('click', closeSettingsModal);
  bindModalBackdrop('settingsModal', closeSettingsModal);
  qsa('.settings-tab').forEach((tab) => {
    tab.addEventListener('click', () => selectSettingsTab(tab.dataset.tab));
  });
  qsa('.sub-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      selectSubTab(tab.dataset.sub, tab.closest('.settings-panel') || document);
    });
  });
  el('shortcutEditBtn').addEventListener('click', () => setShortcutEditMode(true));
  el('shortcutCancelBtn').addEventListener('click', () => setShortcutEditMode(false));
  el('shortcutSaveBtn').addEventListener('click', saveShortcuts);
  el('actionsExpandBtn').addEventListener('click', () => {
    actionsExpanded = !actionsExpanded;
    applyActionOverflow();
  });
  el('filterPanelClear').addEventListener('click', () => applyFilterChain([]));
  el('filterPanelApply').addEventListener('click', () => applyFilterChain(selectedFilterChain()));
  el('filterAddBtn').addEventListener('click', addFilterBlock);
  el('tipsSw').addEventListener('change', (e) => {
    settingsSet('ybe_tips_enabled', e.target.checked ? '1' : '0');
    if (!e.target.checked) closeTipModal();
  });
}

/**
 * Wire the load-data, changelog and tip modals.
 * @returns {void}
 */
function wireDatasetModals() {
  el('loadDataBtn').addEventListener('click', loadDataFromModal);
  el('loadDataYaml').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') loadDataFromModal();
  });
  el('loadDataModalClose').addEventListener('click', closeLoadDataModal);
  bindModalBackdrop('loadDataModal', closeLoadDataModal);
  el('changelogModalClose').addEventListener('click', closeChangelog);
  bindModalBackdrop('changelogModal', closeChangelog);
  el('tipModalClose').addEventListener('click', closeTipModal);
  bindModalBackdrop('tipModal', closeTipModal);
}

/**
 * Wire the raw YAML editor modal.
 * @returns {void}
 */
function wireYamlEditor() {
  el('yamlEditorClose').addEventListener('click', closeYamlEditor);
  el('yamlEditorCancel').addEventListener('click', closeYamlEditor);
  bindModalBackdrop('yamlEditorModal', closeYamlEditor);
  el('yamlEditorSave').addEventListener('click', saveYamlEditor);
}

/**
 * Wire the help modal: the top-panel button, tabs, close and backdrop.
 * @returns {void}
 */
function wireHelp() {
  onEl('helpBtn', 'click', () => openHelp());
  onEl('helpClose', 'click', closeHelp);
  bindModalBackdrop('helpModal', closeHelp);
  qsa('.help-tab').forEach((tab) => {
    tab.addEventListener('click', () => selectHelpTab(tab.dataset.helpTab));
  });
}

/**
 * Wire the notifications button, panel and outside-click dismissal.
 * @returns {void}
 */
function wireNotifications() {
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
}

/**
 * Wire every part of the UI, then start listening for keyboard shortcuts.
 * @returns {void}
 */
function wireEvents() {
  wireCanvas();
  wireNavigation();
  wireEditingControls();
  wireTags();
  wireUpdates();
  wireSettings();
  wireDatasetModals();
  wireYamlEditor();
  wireHelp();
  wireNotifications();
  document.addEventListener('keydown', onGlobalKeyDown);
}

wireEvents();
