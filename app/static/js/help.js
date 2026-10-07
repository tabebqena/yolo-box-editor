// app/static/js/help.js — built-in help: 3-level tutorial + How-to recipes
'use strict';

// ------------------------------------------------------------------------- //
// help modal
//
// The help content ships as HTML fragments under app/static/help/ and is
// fetched the first time a tab is opened, then cached for the session. Tabs:
// Beginner, Intermediate, Expert (the tutorial) and How to? (task recipes).
// ------------------------------------------------------------------------- //

// Tab order and the fragment each one loads. `key` matches data-help-tab.
const HELP_TABS = [
  { key: 'beginner', label: 'Beginner', file: 'beginner.html' },
  { key: 'intermediate', label: 'Intermediate', file: 'intermediate.html' },
  { key: 'expert', label: 'Expert', file: 'expert.html' },
  { key: 'howto', label: 'How to?', file: 'howto.html' },
];

// The tab shown when help opens with no other choice.
const HELP_DEFAULT_TAB = 'beginner';

// Currently shown help tab key.
let currentHelpTab = HELP_DEFAULT_TAB;
// Loaded fragments, keyed by tab key.
const helpCache = {};
// Monotonic id for the in-flight load, so only the latest fetch may paint.
let helpLoadSeq = 0;

/**
 * Look up a tab definition by key, falling back to the default tab.
 * @param {string} key
 * @returns {Object}
 */
function helpTabDef(key) {
  return HELP_TABS.find((t) => t.key === key)
    || HELP_TABS.find((t) => t.key === HELP_DEFAULT_TAB)
    || HELP_TABS[0];
}

/**
 * Render one help fragment into the modal body.
 * @param {string} html - Fragment markup.
 * @param {string} key - Tab key it belongs to.
 * @returns {void}
 */
function renderHelpContent(html, key) {
  if (key !== currentHelpTab) return; // the user switched tabs meanwhile
  const body = el('helpBody');
  if (!body) return;
  body.innerHTML = html;
  body.scrollTop = 0;
}

/**
 * Load a help fragment (once) and show it.
 * @param {string} key - Tab key.
 * @returns {Promise<void>}
 */
async function loadHelpContent(key) {
  const body = el('helpBody');
  if (!body) return;
  if (Object.prototype.hasOwnProperty.call(helpCache, key)) {
    renderHelpContent(helpCache[key], key);
    return;
  }
  const def = helpTabDef(key);
  const token = String(++helpLoadSeq);
  body.dataset.loading = token;
  body.innerHTML = '<p class="help-loading">Loading…</p>';
  try {
    const res = await fetch('/static/help/' + def.file);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const html = await res.text();
    helpCache[key] = html;
    // Only paint if this is still the load the body is waiting for; a newer
    // tab (or a reopen) bumps the token and its own fetch will paint instead.
    if (body.dataset.loading === token) {
      renderHelpContent(html, key);
      delete body.dataset.loading;
    }
  } catch (err) {
    dbgWarn('help content failed', { key, error: String(err) });
    if (body.dataset.loading === token) {
      body.innerHTML = '<p class="help-error">Could not load the help content. '
        + 'The full guides also live in the repository docs/ folder.</p>';
      delete body.dataset.loading;
    }
  }
}

/**
 * Activate a help tab: update the tab strip and show its content.
 * @param {string} key - Tab key.
 * @returns {void}
 */
function selectHelpTab(key) {
  const def = helpTabDef(key);
  currentHelpTab = def.key;
  qsa('.help-tab').forEach((tab) => {
    const active = tab.dataset.helpTab === def.key;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  loadHelpContent(def.key);
}

/**
 * Open the help modal, showing `tab` (or the last/default tab).
 * @param {string} [tab] - Optional tab key to show.
 * @returns {void}
 */
function openHelp(tab) {
  currentHelpTab = tab ? helpTabDef(tab).key : (currentHelpTab || HELP_DEFAULT_TAB);
  openModal('helpModal');
  // Refresh the strip in case the modal was reopened on a different tab; then
  // load (cached) content.
  selectHelpTab(currentHelpTab);
}

/**
 * Close the help modal.
 * @returns {void}
 */
function closeHelp() {
  closeModal('helpModal');
}
