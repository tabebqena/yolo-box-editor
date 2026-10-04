// app/static/js/navigation.js — settings modal, dataset/split, filter chain, tips
'use strict';

// ------------------------------------------------------------------------- //
// navigation & data loading
// ------------------------------------------------------------------------- //
/**
 * Update the counter and prev/next buttons to match the current image.
 */
function updateNav() {
  const total = images.length;
  el('counter').value = total ? `${currentIndex + 1} / ${total}` : '0 / 0';
  el('prevBtn').disabled = total === 0 || currentIndex <= 0;
  el('nextBtn').disabled = total === 0 || currentIndex >= total - 1;
}

/**
 * Jump to image N (1-based) typed into the counter input.
 * @param {string} text
 * @returns {Promise<void>}
 */
async function jumpToImage(text) {
  if (!images.length) return;
  const m = String(text).match(/\d+/);
  const n = m ? parseInt(m[0], 10) : NaN;
  if (isNaN(n) || n < 1) {
    updateNav();
    return;
  }
  const idx = Math.min(Math.max(n - 1, 0), images.length - 1);
  if (idx !== currentIndex && !(await saveOrDiscard())) {
    updateNav();
    return;
  }
  loadImage(idx);
}

// set once the load-data modal has been auto-opened for this page load
let loadDataAutoOpened = false;
let tipChecked = false; // the daily tip is considered at most once per page load

/**
 * Show one random, not-yet-seen tip at most once per day. The tip list ships in
 * the backend (config.tips); the browser + backend remember the date and which
 * indices have been seen (so it carries across browsers), and reset the seen
 * list once every tip has appeared.
 * @param {string[]} tips
 */
function maybeShowTip(tips) {
  if (tipChecked) return;
  tipChecked = true;
  if (settingsGet('ybe_tips_enabled') === '0') return;
  if (!Array.isArray(tips) || !tips.length) return;

  const today = new Date().toISOString().slice(0, 10);
  const last = settingsGet(TIP_LAST_KEY);
  if (last === today) return;

  let seen = [];
  try { seen = JSON.parse(settingsGet(TIPS_SEEN_KEY) || '[]'); } catch (e) { seen = []; }
  if (!Array.isArray(seen)) seen = [];

  let pool = tips.map((_, i) => i).filter((i) => !seen.includes(i));
  if (!pool.length) { pool = tips.map((_, i) => i); seen = []; }
  const idx = pool[Math.floor(Math.random() * pool.length)];
  seen.push(idx);

  settingsSet(TIP_LAST_KEY, today);
  settingsSet(TIPS_SEEN_KEY, JSON.stringify(seen));

  queueAutoModal('tip', () => {
    el('tipText').textContent = tips[idx];
    openModal('tipModal');
  });
}

/**
 * Close the daily tip modal and release its auto-modal slot.
 */
function closeTipModal() {
  closeModal('tipModal');
  releaseAutoModal('tip');
}

/**
 * Activate a top-level Settings tab.
 * @param {string} name
 */
function selectSettingsTab(name) {
  qsa('.settings-tab').forEach((tab) => {
    tab.classList.toggle('active', tab.dataset.tab === name);
  });
  qsa('.settings-panel').forEach((panel) => {
    panel.classList.toggle('active', panel.dataset.panel === name);
  });
}

/**
 * Switch a segmented sub-tab within one settings panel. Kept separate from
 * `selectSettingsTab` so the main tabs are untouched; `scope` is the owning
 * `.settings-panel` so the same names in other panels never clash.
 * @param {string} name
 * @param {Element} [scope] - Owning panel; defaults to the document.
 */
function selectSubTab(name, scope) {
  const root = scope || document;
  qsa('.sub-tab', root).forEach((tab) => {
    tab.classList.toggle('active', tab.dataset.sub === name);
  });
  qsa('.sub-panel', root).forEach((sub) => {
    sub.classList.toggle('active', sub.dataset.sub === name);
  });
}

/**
 * Open the Settings modal, focusing the dataset tab when none is loaded.
 */
function openSettingsModal() {
  openModal('settingsModal');
  el('shortcutEditBtn').disabled = readonly;
  el('shortcutEditBtn').title = readonly
    ? 'Shortcuts cannot be changed in read-only mode'
    : 'Edit the key bindings';
  // With no dataset, the Dataset tab is the only useful one.
  if (!datasetLoaded) {
    selectSettingsTab('dataset');
    const input = el('dataYaml');
    input.focus();
    input.select();
  }
}

/**
 * Close the Settings modal.
 */
function closeSettingsModal() {
  closeModal('settingsModal');
}

/**
 * Open the load-dataset modal, focusing and selecting the path input.
 */
function openLoadDataModal() {
  queueAutoModal('loadData', () => {
    openModal('loadDataModal');
    const input = el('loadDataYaml');
    input.focus();
    input.select();
  });
}

/**
 * Close the load-dataset modal and release its auto-modal slot.
 */
function closeLoadDataModal() {
  closeModal('loadDataModal');
  releaseAutoModal('loadData');
}

/**
 * Fill the split select with "All splits" plus every known split.
 */
function populateSplitSelect() {
  const sel = el('splitSelect');
  sel.innerHTML = '';
  sel.appendChild(option('', 'All splits'));
  splits.forEach((s) => sel.appendChild(option(s.name, s.name)));
  sel.value = activeSplit || '';
}

// maximum number of filters that can be chained
const FILTER_CHAIN_MAX = 8;

/**
 * Look up a filter definition by name.
 * @param {string} name
 * @returns {object|null}
 */
function filterDef(name) {
  return filters.find((f) => f.name === name) || null;
}

/**
 * Build one filter-chain block (select, remove button and argument fields).
 * @param {number} i - Block index; the first block reads "No filter".
 * @returns {HTMLElement}
 */
function buildFilterBlock(i) {
  const block = mk('div', 'filter-chain-item');

  const sel = mk('select', 'filter-chain-select');
  sel.appendChild(option('', i === 0 ? 'No filter' : '(none)'));
  filters.forEach((f) => sel.appendChild(option(f.name, f.name)));
  const active = activeFilters[i];
  sel.value = active && filterDef(active.name) ? active.name : '';

  const head = mk('div', 'filter-chain-head');
  head.appendChild(sel);
  const remove = mk('button', 'filter-chain-remove', '\u00d7');
  remove.type = 'button';
  remove.title = 'Remove this filter from the chain';
  remove.addEventListener('click', () => removeFilterBlock(block));
  head.appendChild(remove);
  block.appendChild(head);

  const detail = mk('div', 'filter-chain-detail');
  block.appendChild(detail);

  const renderDetail = () => {
    detail.innerHTML = '';
    const def = filterDef(sel.value);
    if (!def) return;
    if (def.description) {
      const desc = mk('p', 'filter-chain-desc', def.description);
      desc.title = def.description;
      detail.appendChild(desc);
    }
    const saved = active && active.name === def.name ? (active.arguments || {}) : {};
    (def.arguments || []).forEach((arg) => {
      const row = mk('label', 'filter-arg');
      row.appendChild(mk('span', 'filter-arg-label', arg.name + (arg.required ? ' *' : '')));

      const value = Object.prototype.hasOwnProperty.call(saved, arg.name)
        ? saved[arg.name] : (arg.default != null ? arg.default : '');
      let input;
      if (Array.isArray(arg.options) && arg.options.length) {
        input = mk('select');
        if (!arg.required) input.appendChild(option('', ''));
        arg.options.forEach((opt) => input.appendChild(option(opt, opt)));
        input.value = value;
      } else {
        input = mk('input');
        input.type = 'text';
        input.value = value || '';
        if (arg.default != null) input.placeholder = arg.default;
      }
      input.className = 'filter-arg-input';
      input.dataset.arg = arg.name;
      row.appendChild(input);
      detail.appendChild(row);
    });
  };

  sel.addEventListener('change', renderDetail);
  renderDetail();
  return block;
}

/**
 * Keep the first block reading "No filter" and the rest "(none)" after adds and
 * removes, so the empty slot is obvious.
 */
function relabelFilterChain() {
  const body = el('filterPanelBody');
  if (!body) return;
  body.querySelectorAll('.filter-chain-item').forEach((block, i) => {
    const sel = block.querySelector('.filter-chain-select');
    if (sel && sel.options.length) {
      sel.options[0].textContent = i === 0 ? 'No filter' : '(none)';
    }
  });
}

/**
 * Add is allowed until FILTER_CHAIN_MAX; remove is blocked on the last block, so
 * there is always one slot to build in.
 */
function updateFilterChainControls() {
  const body = el('filterPanelBody');
  if (!body) return;
  const blocks = body.querySelectorAll('.filter-chain-item');
  const add = el('filterAddBtn');
  if (add) {
    const full = blocks.length >= FILTER_CHAIN_MAX;
    add.disabled = full;
    add.title = full
      ? `Up to ${FILTER_CHAIN_MAX} filters can be chained`
      : 'Add a filter to the chain';
  }
  blocks.forEach((b) => {
    const rm = b.querySelector('.filter-chain-remove');
    if (rm) rm.disabled = blocks.length <= 1;
  });
}

/**
 * Append a filter block to the chain, if there is room.
 */
function addFilterBlock() {
  const body = el('filterPanelBody');
  if (!body || !filters.length) return;
  const blocks = body.querySelectorAll('.filter-chain-item');
  if (blocks.length >= FILTER_CHAIN_MAX) return;
  body.appendChild(buildFilterBlock(blocks.length));
  relabelFilterChain();
  updateFilterChainControls();
}

/**
 * Remove a filter block, leaving at least one behind.
 * @param {HTMLElement} block
 */
function removeFilterBlock(block) {
  const body = el('filterPanelBody');
  if (!body || !block) return;
  if (body.querySelectorAll('.filter-chain-item').length <= 1) return;
  block.remove();
  relabelFilterChain();
  updateFilterChainControls();
}

/**
 * Render the filter chain editor from the active filter chain.
 */
function populateFilterPanel() {
  const body = el('filterPanelBody');
  if (!body) return;
  body.innerHTML = '';
  const add = el('filterAddBtn');
  if (!filters.length) {
    body.appendChild(mk('div', 'filter-empty', 'No filters found in filters/.'));
    if (add) add.disabled = true;
    return;
  }
  const count = Math.min(Math.max(activeFilters.length, 1), FILTER_CHAIN_MAX);
  for (let i = 0; i < count; i++) {
    body.appendChild(buildFilterBlock(i));
  }
  relabelFilterChain();
  updateFilterChainControls();
}

/**
 * Read the selected filters and their argument values from the UI.
 * @returns {Array<{name:string,arguments:Object}>}
 */
function selectedFilterChain() {
  const chain = [];
  const body = el('filterPanelBody');
  if (body) body.querySelectorAll('.filter-chain-item').forEach((block) => {
    const sel = block.querySelector('.filter-chain-select');
    if (!sel || !sel.value) return;
    const args = {};
    block.querySelectorAll('.filter-arg-input').forEach((input) => {
      args[input.dataset.arg] = input.value;
    });
    chain.push({ name: sel.value, arguments: args });
  });
  return chain;
}
