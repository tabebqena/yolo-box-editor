// app/static/js/events.js — event wiring, image-list reload, shortcut handlers, initSettings
'use strict';

// Escape closes the topmost open overlay, in this priority order.
const ESCAPE_CLOSERS = [
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

// Listen on window (not just the canvas) so a drag that leaves the image still
// tracks the cursor and completes on release instead of losing the box.
function onWindowMouseMove(e) {
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
}

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

// Fetch a fresh image list and apply it, keeping the current image by path.
// `url` is the endpoint (GET) or the endpoint plus a fetch init; `tag` and
// `label` keep the console messages specific to the calling action.
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
    imageEl.removeAttribute('src');
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
    resetToEmptyImage();
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

// ------------------------------------------------------------------------- //
// keyboard dispatch
// ------------------------------------------------------------------------- //

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

// ------------------------------------------------------------------------- //
// wiring
// ------------------------------------------------------------------------- //

function wireCanvas() {
  canvas.addEventListener('mousedown', onCanvasMouseDown);
  // window (not just the canvas): a drag that leaves the image still tracks
  // the cursor and completes on release instead of losing the box.
  window.addEventListener('mousemove', onWindowMouseMove);
  window.addEventListener('mouseup', onWindowMouseUp);
}

function wireNavigation() {
  el('prevBtn').addEventListener('click', () => go(-1));
  el('nextBtn').addEventListener('click', () => go(1));
  el('splitSelect').addEventListener('change', () => setSplit(el('splitSelect').value));
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

function wireUpdates() {
  el('updateCheckBtn').addEventListener('click', () => {
    el('updateStatus').textContent = 'Checking…';
    refreshUpdateInfo(true);
  });
  el('updateHowBtn').addEventListener('click', openUpdateModal);
  el('updateModalClose').addEventListener('click', closeUpdateModal);
  bindModalBackdrop('updateModal', closeUpdateModal);
}

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

function wireYamlEditor() {
  el('yamlEditorClose').addEventListener('click', closeYamlEditor);
  el('yamlEditorCancel').addEventListener('click', closeYamlEditor);
  bindModalBackdrop('yamlEditorModal', closeYamlEditor);
  el('yamlEditorSave').addEventListener('click', saveYamlEditor);
}

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

function wireEvents() {
  wireCanvas();
  wireNavigation();
  wireEditingControls();
  wireTags();
  wireUpdates();
  wireSettings();
  wireDatasetModals();
  wireYamlEditor();
  wireNotifications();
  document.addEventListener('keydown', onGlobalKeyDown);
}

wireEvents();
