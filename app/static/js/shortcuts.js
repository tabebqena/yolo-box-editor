// app/static/js/shortcuts.js — action buttons, shortcut modal/editing, presence
'use strict';

/**
 * Fill the recent-datasets dropdown and hide it when the list is empty.
 * @param {string[]} paths - Recently opened data.yaml paths.
 * @returns {void}
 */
function populateRecent(paths) {
  const sel = el('recentSelect');
  sel.innerHTML = '';
  const list = paths || [];
  // Nothing to pick from: hide the dropdown entirely.
  setHidden(sel, list.length === 0);
  sel.appendChild(option('', 'Recent…'));
  list.forEach((p) => sel.appendChild(option(p, p)));
  sel.value = '';
}

// Max action buttons shown before the overflow (…) button appears.
const ACTIONS_VISIBLE = 3;
// Whether the overflowed action buttons are currently revealed.
let actionsExpanded = false;

/**
 * Show only the first ACTIONS_VISIBLE action buttons; reveal the rest when the
 * expand button (…) is toggled.
 * @returns {void}
 */
function applyActionOverflow() {
  const box = el('actionBtns');
  const expand = el('actionsExpandBtn');
  if (!box || !expand) return;
  const items = Array.from(box.querySelectorAll('button.action'));
  const overflow = items.length > ACTIONS_VISIBLE;
  expand.classList.toggle('hidden', !overflow);
  box.classList.toggle('expanded', actionsExpanded);
  items.forEach((b, i) => {
    b.classList.toggle('hidden', overflow && !actionsExpanded && i >= ACTIONS_VISIBLE);
  });
  expand.title = actionsExpanded ? 'Show fewer actions' : 'Show all actions';
}

/**
 * Rebuild the action buttons for the given action names.
 * @param {string[]} names - Action names to render.
 * @returns {void}
 */
function populateActions(names) {
  const box = el('actionBtns');
  box.innerHTML = '';
  actionsExpanded = false;
  (names || []).forEach((n) => {
    const btn = mk('button', 'action', n);
    const sc = actionShortcuts[n] && actionShortcuts[n].shortcut;
    btn.title = sc ? `Run action "${n}" on the current image (${sc})` : `Run action "${n}" on the current image`;
    if (sc) btn.appendChild(mk('span', 'btn-shortcut', sc));
    btn.addEventListener('click', () => runAction(n));
    box.appendChild(btn);
  });
  applyActionOverflow();
}

/**
 * Enable or disable every action button.
 * @param {boolean} disabled - Whether the buttons should be disabled.
 * @returns {void}
 */
function setActionButtonsDisabled(disabled) {
  el('actionBtns').querySelectorAll('button').forEach((b) => { b.disabled = disabled; });
}

// ------------------------------------------------------------------------- //
// shortcuts (modal)
// ------------------------------------------------------------------------- //
/**
 * Build a <kbd> element for a shortcut key label.
 * @param {string} text - Key label to display.
 * @returns {HTMLElement} The created element.
 */
function shortcutKbd(text) {
  return mk('kbd', null, text);
}

/**
 * Build a modal row pairing a label with its shortcut keys.
 * @param {string} label - Human-readable action label.
 * @param {string|string[]} keys - One or more key labels.
 * @returns {HTMLElement} The created row.
 */
function menuRow(label, keys) {
  const row = mk('div', 'menu-row');
  const keyBox = mk('span', 'menu-keys');
  (Array.isArray(keys) ? keys : [keys]).forEach((k) => keyBox.appendChild(shortcutKbd(k)));
  row.append(mk('span', 'menu-label', label), keyBox);
  return row;
}

// Preferred display order for the built-in app shortcuts.
const APP_SHORTCUT_ORDER = ['app_help', 'app_prev', 'app_next', 'app_del', 'app_drop', 'app_undo', 'app_redo', 'app_save', 'app_ch_box', 'app_sel_box', 'app_sel_points', 'app_escape', 'app_show_hide', 'app_box_details', 'app_isolate_box', 'app_focus_canvas', 'app_select_all', 'app_fix_box', 'app_widen_left', 'app_widen_right', 'app_widen_up', 'app_widen_down', 'app_narrow_left', 'app_narrow_right', 'app_narrow_up', 'app_narrow_down', 'app_force_draw', 'app_refresh_images_list', 'app_reload_images_list', 'app_refresh_image'];

// Last shortcut-error message shown, so config reloads don't re-toast it.
let shownShortcutErrors = '';

/**
 * Show a sticky toast listing the visible shortcut, hook and filter errors.
 * @returns {void}
 */
function renderShortcutErrors() {
  const dismissed = JSON.parse(sessionStorage.getItem('dismissedShortcutErrors') || '[]');
  // messages are self-describing ("'shortcuts.txt': ..." / "'hooks/x.yaml': ...")
  const all = shortcutErrors.concat(hookErrors, filterErrors);
  const visible = all.filter((msg) => !dismissed.includes(msg));
  if (!visible.length) return;
  const msg = visible.join(' | ');
  if (msg === shownShortcutErrors) return; // config reloads must not re-toast it
  shownShortcutErrors = msg;
  toast(msg, {
    type: 'error',
    sticky: true,
    onClose: () => {
      const updated = dismissed.concat(visible);
      sessionStorage.setItem('dismissedShortcutErrors', JSON.stringify(updated));
    },
  });
}

// --------------------------------------------------------------------------- //
// Concurrent-client warning: ping /api/presence and show a dismissible message
// while more than one client is using the app. Informational only; it never
// blocks editing. The server is the source of truth so different browsers and
// machines are counted too.
// --------------------------------------------------------------------------- //
const PRESENCE_INTERVAL = 5000; // ms between presence pings
// Interval id for the presence ping loop.
let presenceTimer = null;
// Set once the user dismisses the presence warning for this overlap.
let presenceDismissed = false;
// Handle of the currently shown presence warning toast, if any.
let presenceToast = null;

/**
 * Show or hide the concurrent-client warning based on the client count.
 * @param {number} count - Number of connected clients.
 * @returns {void}
 */
function renderPresenceWarning(count) {
  if (count <= 1) {
    // overlap is over: hide the toast, and warn again on a later overlap
    presenceDismissed = false;
    if (presenceToast) { presenceToast.dismiss(); presenceToast = null; }
    return;
  }
  if (presenceDismissed || presenceToast) return;
  presenceToast = toast(
    'Another user is using this app. It is designed for one user at a time and is ' +
    'not meant to be served to multiple clients, so your changes may overwrite theirs.',
    {
      type: 'warning',
      sticky: true,
      onClose: () => { presenceDismissed = true; presenceToast = null; },
    });
}

/**
 * Send a presence ping, optionally signalling that this client is leaving.
 * @param {boolean} [bye=false] - True to mark the client as gone.
 * @returns {Promise<void>}
 */
async function pingPresence(bye = false) {
  try {
    const { data } = await apiPost('/api/presence', { cid: CLIENT_ID, bye }, { keepalive: bye });
    dbg('presence', { count: data.count, bye });
    if (!bye) renderPresenceWarning(data.count || 0);
  } catch (e) { /* presence is best-effort */ }
}

/**
 * Start the periodic presence ping and wire up visibility/page-hide pings.
 * @returns {void}
 */
function startPresence() {
  pingPresence();
  clearInterval(presenceTimer);
  presenceTimer = setInterval(pingPresence, PRESENCE_INTERVAL);
  // background tabs get their timers throttled; ping again as soon as we are visible
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') pingPresence();
  });
  window.addEventListener('pagehide', () => {
    const body = JSON.stringify({ cid: CLIENT_ID, bye: true });
    if (navigator.sendBeacon) {
      navigator.sendBeacon('/api/presence', new Blob([body], { type: 'application/json' }));
    }
  });
}

/**
 * Build a titled section container for the shortcuts modal.
 * @param {string} title - Section heading.
 * @returns {HTMLElement} The created section.
 */
function shortcutSection(title) {
  return mk('div', 'shortcut-section', title);
}

// Canonical modifier labels in display order.
const SHORTCUT_MODIFIERS = ['Ctrl', 'Alt', 'Shift', 'Meta'];
// Maps KeyboardEvent.key modifier names to their display labels.
const SHORTCUT_MODIFIER_KEYS = { Control: 'Ctrl', Alt: 'Alt', Shift: 'Shift', Meta: 'Meta' };

/**
 * Format a shortcut for display, using an em dash when unbound.
 * @param {string} text - Shortcut string.
 * @returns {string} The display text.
 */
function shortcutDisplay(text) {
  return text || '\u2014';
}

/**
 * Look up the effective shortcut for an app or action name.
 * @param {string} name - Shortcut name.
 * @returns {string} The bound shortcut, or an empty string.
 */
function currentShortcut(name) {
  const info = appShortcuts[name] || actionShortcuts[name];
  return info ? info.shortcut : '';
}

/**
 * Build an editable row for one shortcut, with a capture button and reset.
 * @param {string} name - Shortcut name.
 * @param {string} label - Human-readable label.
 * @returns {HTMLElement} The created row.
 */
function shortcutEditRow(name, label) {
  const row = mk('div', 'menu-row shortcut-edit-row');
  row.appendChild(mk('span', 'menu-label', label));

  const btn = mk('button', 'shortcut-capture', shortcutDisplay(shortcutDraft[name]));
  btn.type = 'button';
  btn.title = 'Click, then press the new key combination';
  btn.addEventListener('click', () => startShortcutCapture(btn, name));
  row.appendChild(btn);

  if (userShortcutNames.has(name) || shortcutResets.has(name)) {
    const reset = mk('button', 'shortcut-reset', '\u21ba');
    reset.type = 'button';
    reset.title = 'Reset to the shipped default';
    reset.addEventListener('click', () => resetShortcut(name));
    row.appendChild(reset);
  }
  return row;
}

/**
 * Render the shortcuts modal contents in view or edit mode.
 * @returns {void}
 */
function renderShortcuts() {
  const wrap = el('shortcutItems');
  if (!wrap) return;
  wrap.innerHTML = '';
  wrap.classList.toggle('editing', shortcutEditMode);

  const appNames = APP_SHORTCUT_ORDER.filter((name) => appShortcuts[name]);
  const actionEntries = Object.entries(actionShortcuts);

  if (appNames.length) {
    wrap.appendChild(shortcutSection('App'));
    appNames.forEach((name) => {
      const info = appShortcuts[name];
      wrap.appendChild(shortcutEditMode
        ? shortcutEditRow(name, info.label)
        : menuRow(info.label, info.shortcut));
    });
  }
  if (actionEntries.length) {
    wrap.appendChild(shortcutSection('Actions'));
    actionEntries.forEach(([name, info]) => {
      const label = `${name}: ${info.label}`.trim();
      wrap.appendChild(shortcutEditMode
        ? shortcutEditRow(name, label)
        : menuRow(label, info.shortcut));
    });
  }
  wrap.appendChild(shortcutSection('Mouse'));
  const mouse = mk('div', 'menu-row');
  mouse.appendChild(mk('span', 'menu-label', 'Drag to draw · \u2715 to delete box'));
  wrap.appendChild(mouse);
}

// --- editing the bindings (Settings > Shortcuts > Edit) ------------------- //
let shortcutCapture = null; // {name, btn, held:Set, used:Set, keyPressed}

/**
 * Convert a keyboard event into a shortcut key token.
 * @param {KeyboardEvent} e - The key event.
 * @returns {string|null} The key token, or null when unsupported.
 */
function shortcutKeyFromEvent(e) {
  if (/^Key[A-Z]$/.test(e.code)) return e.code.slice(3);
  if (/^Digit[0-9]$/.test(e.code)) return e.code.slice(5);
  if (e.key === ' ') return 'Space';
  if (e.key.length === 1) return e.key;
  const named = {
    Escape: 'Escape', Delete: 'Delete', Backspace: 'Backspace',
    ArrowLeft: 'ArrowLeft', ArrowRight: 'ArrowRight', ArrowUp: 'ArrowUp',
    ArrowDown: 'ArrowDown', Tab: 'Tab', Enter: 'Enter', Home: 'Home',
    End: 'End', PageUp: 'PageUp', PageDown: 'PageDown', Insert: 'Insert',
  };
  return named[e.key] || null;
}

/**
 * Begin capturing a new key combination for a shortcut.
 * @param {HTMLButtonElement} btn - The capture button being edited.
 * @param {string} name - Shortcut name being rebound.
 * @returns {void}
 */
function startShortcutCapture(btn, name) {
  stopShortcutCapture();
  shortcutCapture = { name, btn, held: new Set(), used: new Set(), keyPressed: false };
  btn.classList.add('capturing');
  btn.textContent = 'Press a key…';
  document.addEventListener('keydown', onShortcutCaptureKeyDown, true);
  document.addEventListener('keyup', onShortcutCaptureKeyUp, true);
  btn.focus();
}

/**
 * Stop capturing and restore the capture button's label.
 * @returns {void}
 */
function stopShortcutCapture() {
  if (!shortcutCapture) return;
  document.removeEventListener('keydown', onShortcutCaptureKeyDown, true);
  document.removeEventListener('keyup', onShortcutCaptureKeyUp, true);
  shortcutCapture.btn.classList.remove('capturing');
  shortcutCapture.btn.textContent = shortcutDisplay(shortcutDraft[shortcutCapture.name]);
  shortcutCapture = null;
}

/**
 * Commit a captured combination to the draft bindings.
 * @param {string} value - The captured shortcut string.
 * @returns {void}
 */
function applyShortcutCapture(value) {
  const name = shortcutCapture.name;
  shortcutDraft[name] = value;
  shortcutResets.delete(name);
  stopShortcutCapture();
  renderShortcuts();
}

/**
 * Handle keydown while capturing a shortcut.
 * @param {KeyboardEvent} e - The key event.
 * @returns {void}
 */
function onShortcutCaptureKeyDown(e) {
  if (!shortcutCapture) return;
  e.preventDefault();
  e.stopImmediatePropagation();
  if (e.key === 'Escape') {
    stopShortcutCapture();
    renderShortcuts();
    return;
  }
  const mod = SHORTCUT_MODIFIER_KEYS[e.key];
  if (mod) {
    shortcutCapture.held.add(mod);
    shortcutCapture.used.add(mod);
    return;
  }
  const key = shortcutKeyFromEvent(e);
  if (!key) return;
  shortcutCapture.keyPressed = true;
  const mods = SHORTCUT_MODIFIERS.filter((m) => shortcutCapture.used.has(m));
  applyShortcutCapture(mods.concat(key).join('+'));
}

/**
 * Handle keyup while capturing, allowing modifier-only bindings.
 * @param {KeyboardEvent} e - The key event.
 * @returns {void}
 */
function onShortcutCaptureKeyUp(e) {
  if (!shortcutCapture) return;
  e.preventDefault();
  e.stopImmediatePropagation();
  const mod = SHORTCUT_MODIFIER_KEYS[e.key];
  if (!mod) return;
  shortcutCapture.held.delete(mod);
  // all modifiers released without a real key -> modifier-only binding
  if (!shortcutCapture.keyPressed && shortcutCapture.held.size === 0 && shortcutCapture.used.size) {
    const mods = SHORTCUT_MODIFIERS.filter((m) => shortcutCapture.used.has(m));
    applyShortcutCapture(mods.join('+'));
  }
}

/**
 * Reset a shortcut to its shipped default in the draft bindings.
 * @param {string} name - Shortcut name.
 * @returns {void}
 */
function resetShortcut(name) {
  shortcutResets.add(name);
  const def = shortcutDefaults[name];
  shortcutDraft[name] = def ? def.shortcut : '';
  renderShortcuts();
}

/**
 * Enter or leave shortcut editing and initialise the draft bindings.
 * @param {boolean} on - True to enter edit mode.
 * @returns {void}
 */
function setShortcutEditMode(on) {
  stopShortcutCapture();
  shortcutEditMode = on;
  shortcutDraft = {};
  shortcutResets = new Set();
  if (on) {
    Object.entries(appShortcuts).forEach(([name, info]) => { shortcutDraft[name] = info.shortcut; });
    Object.entries(actionShortcuts).forEach(([name, info]) => { shortcutDraft[name] = info.shortcut; });
  }
  el('shortcutEditBtn').classList.toggle('hidden', on);
  el('shortcutEditHint').classList.toggle('hidden', !on);
  el('shortcutEditActions').classList.toggle('hidden', !on);
  renderShortcuts();
}

/**
 * Save the changed and reset shortcuts to the server.
 * @returns {Promise<void>}
 */
async function saveShortcuts() {
  const set = {};
  Object.entries(shortcutDraft).forEach(([name, value]) => {
    if (shortcutResets.has(name)) return;
    if (value && value !== currentShortcut(name)) set[name] = value;
  });
  const reset = [...shortcutResets].filter((name) => userShortcutNames.has(name));
  const btn = el('shortcutSaveBtn');
  btn.disabled = true;
  try {
    const { res, data: cfg } = await apiPost('/api/shortcuts', { set, reset });
    if (!res.ok || cfg.ok === false) {
      toast(cfg.error || 'Could not save shortcuts', { type: 'error' });
      return;
    }
    appShortcuts = cfg.shortcuts || {};
    actionShortcuts = cfg.action_shortcuts || {};
    shortcutErrors = cfg.shortcut_errors || [];
    shortcutDefaults = cfg.shortcut_defaults || {};
    userShortcutNames = new Set(cfg.user_shortcut_names || []);
    setShortcutEditMode(false);
    renderShortcutErrors();
    toast('Shortcuts saved');
  } catch (err) {
    console.error(err);
    toast('Could not save shortcuts', { type: 'error' });
  } finally {
    btn.disabled = false;
  }
}
