'use strict';

// The shortcut list, edit mode, key capture, saving and error reporting.

const { test, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const { createApp, plain } = require('./helpers/app.js');

let app;
beforeEach(() => { app = createApp(); });
afterEach(() => { app.cleanup(); });

const SHORTCUTS = {
  app_next: { shortcut: 'ArrowRight', label: 'Next' },
  app_show_hide: { shortcut: 'H', label: 'Show/hide boxes' },
};
const ACTION_SHORTCUTS = { Archive: { shortcut: 'Ctrl+A', label: 'Archive' } };

function ready(overrides = {}) {
  app.set({
    appShortcuts: SHORTCUTS,
    actionShortcuts: ACTION_SHORTCUTS,
    shortcutErrors: [],
    hookErrors: [],
    filterErrors: [],
    shortcutDefaults: { app_next: { shortcut: 'ArrowRight', label: 'Next' } },
    userShortcutNames: new Set(),
    ...overrides,
  });
}

function fakeEvent(init) {
  return Object.assign({
    preventDefault() {},
    stopImmediatePropagation() {},
  }, init);
}

test('renderShortcuts lists app, action and mouse rows', () => {
  ready();
  app.api.renderShortcuts();
  const wrap = app.$('shortcutItems');
  const sections = app.api.qsa('.shortcut-section', wrap).map((s) => s.textContent);
  assert.deepEqual(plain(sections), ['App', 'Actions', 'Mouse']);
  const kbd = wrap.querySelectorAll('kbd');
  assert.equal(kbd.length, 3); // two app bindings + one action binding
});

test('currentShortcut finds app and action bindings', () => {
  ready();
  assert.equal(app.api.currentShortcut('app_next'), 'ArrowRight');
  assert.equal(app.api.currentShortcut('Archive'), 'Ctrl+A');
  assert.equal(app.api.currentShortcut('missing'), '');
});

test('setShortcutEditMode shows capture buttons and seeds the draft', () => {
  ready();
  app.api.setShortcutEditMode(true);
  assert.equal(app.api.isHidden('shortcutEditBtn'), true);
  assert.equal(app.api.isHidden('shortcutEditHint'), false);
  assert.equal(app.api.isHidden('shortcutEditActions'), false);
  assert.equal(app.state().shortcutDraft.app_next, 'ArrowRight');
  assert.ok(app.$('shortcutItems').querySelector('.shortcut-capture'));
  app.api.setShortcutEditMode(false);
  assert.equal(app.state().shortcutEditMode, false);
});

test('capturing a key combination stores it in the draft', () => {
  ready();
  app.api.setShortcutEditMode(true);
  const btn = app.$('shortcutItems').querySelector('.shortcut-capture');
  app.api.startShortcutCapture(btn, 'app_next');
  app.api.onShortcutCaptureKeyDown(fakeEvent({ key: 'Control' }));
  app.api.onShortcutCaptureKeyDown(fakeEvent({ key: 's', code: 'KeyS' }));
  assert.equal(app.state().shortcutDraft.app_next, 'Ctrl+S');
  assert.equal(app.state().shortcutCapture, null);
});

test('releasing a modifier alone creates a modifier-only binding', () => {
  ready();
  app.api.setShortcutEditMode(true);
  const btn = app.$('shortcutItems').querySelector('.shortcut-capture');
  app.api.startShortcutCapture(btn, 'app_next');
  app.api.onShortcutCaptureKeyDown(fakeEvent({ key: 'Alt' }));
  app.api.onShortcutCaptureKeyUp(fakeEvent({ key: 'Alt' }));
  assert.equal(app.state().shortcutDraft.app_next, 'Alt');
});

test('Escape cancels a capture without changing the draft', () => {
  ready();
  app.api.setShortcutEditMode(true);
  const btn = app.$('shortcutItems').querySelector('.shortcut-capture');
  app.api.startShortcutCapture(btn, 'app_next');
  const before = app.state().shortcutDraft.app_next;
  app.api.onShortcutCaptureKeyDown(fakeEvent({ key: 'Escape' }));
  assert.equal(app.state().shortcutCapture, null);
  assert.equal(app.state().shortcutDraft.app_next, before);
});

test('resetShortcut restores the shipped default', () => {
  ready();
  app.api.setShortcutEditMode(true);
  app.set({ shortcutDraft: { app_next: 'X' } });
  app.api.resetShortcut('app_next');
  assert.equal(app.state().shortcutDraft.app_next, 'ArrowRight');
  assert.equal(app.state().shortcutResets.has('app_next'), true);
});

test('saveShortcuts posts only changed bindings', async () => {
  ready();
  let posted = null;
  app.fetchMock.on('/api/shortcuts', (url, method, entry) => {
    posted = JSON.parse(entry.body);
    return { body: { ok: true, shortcuts: SHORTCUTS, action_shortcuts: ACTION_SHORTCUTS, shortcut_errors: [], shortcut_defaults: {}, user_shortcut_names: ['app_next'] } };
  });
  app.set({ shortcutEditMode: true, shortcutDraft: { app_next: 'X', app_show_hide: 'H' } });
  await app.api.saveShortcuts();
  assert.deepEqual(plain(posted.set), { app_next: 'X' });
  assert.equal(app.state().shortcutEditMode, false);
});

test('renderShortcutErrors surfaces errors once and honours dismissal', () => {
  app.window.sessionStorage.removeItem('dismissedShortcutErrors');
  ready({ shortcutErrors: ["'shortcuts.txt': bad key"] });
  app.api.renderShortcutErrors();
  assert.equal(app.state().notifLog.length, 1);
  app.api.renderShortcutErrors(); // memoised: no duplicate
  assert.equal(app.state().notifLog.length, 1);

  // a dismissed message is not shown again
  app.api.toast('placeholder', { type: 'info' });
  const app2 = createApp();
  app2.window.sessionStorage.setItem('dismissedShortcutErrors', JSON.stringify(["'shortcuts.txt': bad key"]));
  app2.set({ shortcutErrors: ["'shortcuts.txt': bad key"], hookErrors: [], filterErrors: [] });
  app2.api.renderShortcutErrors();
  assert.equal(app2.state().notifLog.length, 0);
  app2.cleanup();
});

test('renderPresenceWarning warns on overlap and clears when alone', () => {
  app.api.renderPresenceWarning(2);
  assert.equal(app.$('toasts').children.length, 1);
  assert.match(app.$('toasts').textContent, /Another user/);
  app.api.renderPresenceWarning(1);
  assert.equal(app.$('toasts').children.length, 0);
});
