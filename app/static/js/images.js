// app/static/js/images.js — image loading/resume and tagging
'use strict';

// Blank the editor when there is no image to show (empty dataset / image list).
function resetToEmptyImage() {
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
}

function populateClasses() {
  if (classes.length === 0) classes = ['class_0'];
  if (defaultClass >= classes.length) defaultClass = 0;
  const sel = el('classSelect');
  if (!sel) return;
  sel.innerHTML = '';
  classes.forEach((name, i) => sel.appendChild(option(i, `${i}: ${name}`)));
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
  fetch('/api/annotations' + q)
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      if (requested !== currentIndex) return; // a newer loadImage superseded us
      boxes = Array.isArray(data && data.boxes) ? data.boxes : [];
      imageTags = (data && data.tags) || [];
      undoStack = []; // history is per image
      redoStack = [];
      imageEl.removeAttribute('src');
      imageEl.src = '/api/image' + q + '&_=' + Date.now();
      rememberLastImage();
      renderTagBar();
      updateHistoryButtons();
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
// to the image you were on there. Written through `settingsSet`, so the backend
// keeps a copy and a fresh browser resumes at the same image too.
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

function readLastImage() {
  try {
    const raw = settingsGet(LAST_IMAGE_KEY);
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

// Leave the current image safely: auto-save pending edits, or ask before
// discarding them. Returns false when navigation should be blocked.
async function saveOrDiscard() {
  if (!dirty) return true;
  if (autoSave) return flushAutoSave(); // stay put if the save failed
  return confirm('You have unsaved changes. Discard them?');
}

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

// ------------------------------------------------------------------------- //
// tagging (per-image tag bar)
// ------------------------------------------------------------------------- //
function setTagStatus(msg, type = 'info') {
  toast(msg, { type, timeout: type === 'error' ? undefined : 2500 });
}

function tagBadge(name, active, num) {
  const b = mk('button', 'tag-badge' + (active ? ' active' : ''));
  b.type = 'button';
  if (num) b.appendChild(mk('span', 'tag-badge-num', String(num)));
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
  // there is no tags.yaml at all, or the tag is new and is written to tags.yaml
  // on the next save.
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
  availableTags.forEach((t) => dl.appendChild(option(t)));

  // measure after the badges are laid out
  requestAnimationFrame(applyTagOverflow);
  updateDockPanels();
}

// Tag edits join the undo/redo history and are written with the image on Save:
// the backend stores the image's tag file and adds new names to tags.yaml.
function addTag(name) {
  if (readonly || currentIndex < 0) return;
  if (imageTags.includes(name)) return;
  pushUndo();
  imageTags = [...imageTags, name];
  markDirty();
  renderTagBar();
  setTagStatus(`Tag "${name}" added`);
}

function removeTag(name) {
  if (readonly || currentIndex < 0) return;
  pushUndo();
  imageTags = imageTags.filter((t) => t !== name);
  markDirty();
  renderTagBar();
  setTagStatus(`Tag "${name}" removed`);
}

function openTagInput() {
  if (readonly) return;
  showEl('tagInput');
  showEl('tagSubmitBtn');
  el('tagInput').focus();
}

function closeTagInput() {
  hideEl('tagInput');
  hideEl('tagSubmitBtn');
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
