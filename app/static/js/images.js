// app/static/js/images.js — image loading/resume and tagging
'use strict';

/**
 * Blank the editor when there is no image to show (empty dataset / image list).
 * @returns {void}
 */
function resetToEmptyImage() {
  currentIndex = -1;
  boxes = [];
  clearBoxSelection();
  imgW = 0;
  imgH = 0;
  releaseFrame();
  canvas.width = 0;
  canvas.height = 0;
  updateNav();
  renderSidePanel();
}

/**
 * Fill the class dropdown, defaulting to `class_0` when there are no classes.
 * @returns {void}
 */
function populateClasses() {
  if (classes.length === 0) classes = ['class_0'];
  if (defaultClass >= classes.length) defaultClass = 0;
  const sel = el('classSelect');
  if (!sel) return;
  sel.innerHTML = '';
  classes.forEach((name, i) => sel.appendChild(option(i, `${i}: ${name}`)));
  sel.value = defaultClass;
}

/**
 * Load server config, restore the saved view and open the first image.
 * @param {number} [startIdx=0] - Image index to open.
 * @param {Object} [opts={}] - Options such as `explicit`, `anchor` or `noResume`.
 * @returns {Promise<void>}
 */
async function loadConfig(startIdx = 0, opts = {}) {
  const cfg0 = await apiGet('/api/config');
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
  datasetLoaded = !!cfg.data_yaml;
  el('dataYaml').value = cfg.data_yaml || '';
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
  shortcutDefaults = cfg.shortcut_defaults || {};
  userShortcutNames = new Set(cfg.user_shortcut_names || []);
  hookErrors = cfg.hook_errors || [];
  filterErrors = cfg.filter_errors || [];
  hooksByName = new Set(cfg.hooks || []);
  applyExtensionConfig(cfg);
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
    justDrawn = false;
    resetToEmptyImage();
  }
  renderUpdateStatus();
  notifyUpdateDaily();
  notifyChangelog(cfg0);
  maybeShowTip(cfg0.tips);
  emitUiEvent('dataset_loaded', { dataYaml: cfg.data_yaml || '' });
  runHook('on_images_list_loaded');
}

/**
 * Persist the active split and filters per dataset so a reload restores them.
 * @param {Object} cfg - The server config payload.
 * @returns {void}
 */
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

/**
 * Read the saved per-dataset view from localStorage.
 * @returns {Object|null} The saved view, or null when absent/unreadable.
 */
function readSavedView() {
  try {
    return JSON.parse(localStorage.getItem(VIEW_KEY) || 'null');
  } catch (e) { return null; }
}

/**
 * Remove the saved view from localStorage.
 * @returns {void}
 */
function clearSavedView() {
  try { localStorage.removeItem(VIEW_KEY); } catch (e) { /* ignore */ }
}

/**
 * POST a JSON body and return the parsed `data` field.
 * @param {string} url - Request URL.
 * @param {Object} body - JSON-serialisable request body.
 * @returns {Promise<Object>} The response data.
 */
async function postJson(url, body) {
  return (await apiPost(url, body)).data;
}

/**
 * Fetch the current image's annotations (labels) from the server.
 * @returns {Promise<Object|null>} `{boxes}`, or null when no image is open.
 */
async function fetchCurrentAnnotations() {
  if (currentIndex < 0 || !images[currentIndex]) return null;
  return apiGetOrNull('/api/annotations' + keyQuery(images[currentIndex]));
}

/**
 * Replace the current image's labels with a freshly read list.
 *
 * Used by the `app_refresh_image_*` actions after an external tool rewrote the
 * label file. The fresh list is what is on disk, so the image is not marked
 * dirty and the undo/redo history is reset to match.
 * @param {Array<Object>} boxList - The boxes read from the server.
 * @returns {void}
 */
function applyImageLabels(boxList) {
  boxes = Array.isArray(boxList) ? boxList.map((b) => ({ ...b })) : [];
  clearBoxSelection();
  justDrawn = false;
  dirty = false;
  undoStack = [];
  redoStack = [];
  updateHistoryButtons();
  renderSidePanel();
  draw();
}

/**
 * Re-apply the remembered split and/or filter when the server has none (e.g.
 * after a restart). Direct fetches only — never re-enters loadConfig.
 * @param {Object} cfg - The server config payload.
 * @returns {Promise<Object>} The (possibly updated) config payload.
 */
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
  // Entries are {name, arguments}; a bare name is the older saved shape.
  const valid = wanted.map((item) => {
    const name = typeof item === 'string' ? item : (item && item.name);
    const known = name && (cfg.filters || []).some((f) => f.name === name);
    if (!known) return null;
    return typeof item === 'string' ? { name, arguments: {} } : item;
  }).filter(Boolean);
  if (!cfg.active_filters.length && valid.length) {
    const data = await postJson('/api/filter', { filters: valid });
    if (data.ok) return data;
    clearSavedView();
  }
  return cfg;
}

/**
 * Show a filter error once, ignoring repeats on config reloads.
 * @param {string} msg - The message to display.
 * @returns {void}
 */
function showTransientFilterMessage(msg) {
  if (showTransientFilterMessage._last === msg) return; // don't re-toast on reload
  showTransientFilterMessage._last = msg;
  toast(msg, { type: 'error' });
}

/**
 * Load the image at the given index and its annotations.
 * @param {number} i - Image index (clamped to the list).
 * @returns {void}
 */
function loadImage(i) {
  i = Math.max(0, Math.min(images.length - 1, i));
  currentIndex = i;
  const requested = i; // this image may be replaced before the fetches resolve
  clearBoxSelection();
  justDrawn = false;
  dirty = false;
  clearTimeout(autoSaveTimer); // a stale auto-save must not fire on the new image
  autoSaveTimer = null;
  // Extension-drawn overlays belong to the old image: drop them so nothing
  // stale lingers (the owning panel redraws on `image_loaded`).
  drawnBoxes.clear();
  updateNav();
  updateHistoryButtons();
  const entry = images[currentIndex];
  dbg('loadImage', { index: currentIndex, of: images.length,
    image: entry ? `${entry.split}/${entry.name}` : null });

  const q = keyQuery(entry);
  apiGetOrNull('/api/annotations' + q)
    .then((data) => {
      if (requested !== currentIndex) return; // a newer loadImage superseded us
      boxes = Array.isArray(data && data.boxes) ? data.boxes : [];
      undoStack = []; // history is per image
      redoStack = [];
      const imageUrl = '/api/image' + q + '&_=' + Date.now();
      displayImage(imageUrl);
      rememberLastImage();
      updateHistoryButtons();
      dbg('loadImage resolved', { index: currentIndex, boxes: boxes.length, src: imageUrl });
      emitUiEvent('image_loaded', { split: entry.split, name: entry.name });
      runHook('on_image_loaded');
    }).catch((err) => {
      // e.g. the key is no longer in the server list (a stale tab): blank it
      // rather than surfacing an unhandled rejection, and let the image onerror
      // clear the canvas.
      dbgWarn('loadImage failed', { image: imageKey(entry), error: String(err) });
    });
}

/**
 * Remember the current image so the app resumes here on reload. One entry per
 * split is kept, plus a global `last`, written through `settingsSet`.
 * @returns {void}
 */
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
  settingsSet(LAST_IMAGE_KEY, JSON.stringify(mem));
}

/**
 * Read the remembered last-image map from settings.
 * @returns {Object|null} The last-image memory, or null.
 */
function readLastImage() {
  try {
    const raw = settingsGet(LAST_IMAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (e) { return null; }
}

/**
 * Build a stable identity for an image, independent of its list position.
 * @param {Object} entry - Image entry with `split` and `name`.
 * @returns {string|null} The `split/name` key, or null.
 */
function imageKey(entry) {
  return entry ? `${entry.split}/${entry.name}` : null;
}

/**
 * Build the identity query string for an image's API requests.
 * @param {Object} entry - Image entry with `split` and `name`.
 * @returns {string} A `?key=...` query string.
 */
function keyQuery(entry) {
  return '?key=' + encodeURIComponent(imageKey(entry));
}

/**
 * Snapshot the current image (and optionally its followers) by path.
 * @param {boolean} [follow=true] - Also record the images that follow it.
 * @returns {Object|null} The anchor, or null when no image is selected.
 */
function captureImageAnchor(follow = true) {
  if (currentIndex < 0 || !images[currentIndex]) return null;
  return {
    path: imageKey(images[currentIndex]),
    following: follow ? images.slice(currentIndex + 1).map(imageKey) : [],
    follow,
  };
}

/**
 * Find the image to show after the list was rebuilt.
 * @param {Object|null} anchor - Anchor from `captureImageAnchor`.
 * @returns {number} The image index to load.
 */
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

/**
 * Resume the last-reached image for the active split or globally.
 * @param {Object} cfg - The server config payload.
 * @returns {Promise<void>}
 */
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

/**
 * Auto-save or confirm discarding pending edits before leaving the image.
 * @returns {Promise<boolean>} False when navigation should be blocked.
 */
async function saveOrDiscard() {
  if (!dirty) return true;
  if (autoSave) return flushAutoSave(); // stay put if the save failed
  return confirm('You have unsaved changes. Discard them?');
}

/**
 * Move to the image `delta` away, running navigation hooks and saving first.
 * @param {number} delta - Relative step (-1 or 1).
 * @returns {Promise<void>}
 */
async function go(delta) {
  if (currentIndex < 0) return;
  const next = currentIndex + delta;
  if (next < 0 || next >= images.length) { dbg('go blocked', { delta, next, of: images.length }); return; }
  dbg('go', { delta, from: currentIndex, to: next, dirty });
  // "before leave" hooks run at the very start of navigation, before the
  // unsaved-changes / auto-save handling; the on_prev/on_next hooks below still
  // run on the image being left, just before it is replaced.
  await runHook(delta < 0 ? 'on_before_prev' : 'on_before_next');
  if (!(await saveOrDiscard())) return;
  // navigation hooks run on the image being left; they capture its index before
  // loadImage advances currentIndex
  runHook(delta < 0 ? 'on_prev' : 'on_next');
  loadImage(next);
}
