'use strict';

// Browser/server settings and the dockable widget layout.

const { test, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const { createApp } = require('./helpers/app.js');

let app;
beforeEach(() => { app = createApp(); });
afterEach(() => { app.cleanup(); });

test('settingsGet prefers the browser copy over the server copy', () => {
  app.set({ serverSettings: { k: 'server', s: 'server-only' } });
  app.window.localStorage.setItem('k', 'local');
  assert.equal(app.api.settingsGet('k'), 'local');
  assert.equal(app.api.settingsGet('s'), 'server-only');
  assert.equal(app.api.settingsGet('missing'), null);
});

test('settingsSet writes localStorage and mirrors to serverSettings', () => {
  app.api.settingsSet('k', 'v');
  assert.equal(app.window.localStorage.getItem('k'), 'v');
  assert.equal(app.state().serverSettings.k, 'v');
  assert.equal(app.state().pendingSettings.k, 'v');
  app.api.settingsSet('k', null);
  assert.equal(app.window.localStorage.getItem('k'), null);
  assert.equal('k' in app.state().serverSettings, false);
});

test('flushSettings posts the pending changes and adopts the response', async () => {
  let posted = null;
  app.fetchMock.on('/api/settings', (url, method, entry) => {
    posted = JSON.parse(entry.body);
    return { body: { ok: true, settings: { k: 'fromServer' } } };
  });
  app.api.settingsSet('k', 'v');
  app.api.flushSettings();
  await app.flush();
  assert.deepEqual(posted, { settings: { k: 'v' } });
  assert.equal(app.state().serverSettings.k, 'fromServer');
});

test('applySidePanelWidth clamps and sets the CSS variable', () => {
  assert.equal(app.api.applySidePanelWidth(300), 300);
  assert.equal(app.$('sidebar').style.getPropertyValue('--sidebar-w'), '300px');
  assert.equal(app.api.applySidePanelWidth(50), 220);
  assert.equal(app.api.applySidePanelWidth(9999), 720);
});

test('toggleSidePanel collapses the sidebar and persists the choice', () => {
  app.api.toggleSidePanel(false);
  assert.equal(app.$('sidebar').classList.contains('collapsed'), true);
  assert.equal(app.api.settingsGet('sidePanelOpen'), '0');
  app.api.toggleSidePanel(true);
  assert.equal(app.$('sidebar').classList.contains('collapsed'), false);
  assert.equal(app.api.settingsGet('sidePanelOpen'), '1');
});

test('setWidgetDock / getDock validate and persist a location', () => {
  app.api.setWidgetDock('boxes', 'left');
  assert.equal(app.api.getDock('boxes'), 'left');
  assert.equal(app.$('boxesDockSel').value, 'left');
  assert.equal(app.api.settingsGet('ybe_boxes_dock'), 'left');
  app.api.setWidgetDock('boxes', 'nonsense');
  assert.equal(app.api.getDock('boxes'), 'default');
});

test('setWidgetVisible / getWidgetVisible toggle and persist visibility', () => {
  assert.equal(app.api.getWidgetVisible('boxes'), true);
  app.api.setWidgetVisible('boxes', false);
  assert.equal(app.api.getWidgetVisible('boxes'), false);
  assert.equal(app.$('boxesVisibleSw').checked, false);
  assert.equal(app.api.settingsGet('ybe_boxes_visible'), '0');
});

test('applyWidget hides non-tag content when the widget is hidden', () => {
  app.api.setWidgetVisible('boxes', true);
  app.api.applyWidget('boxes');
  assert.equal(app.document.querySelector('.boxes-section').classList.contains('hidden'), false);
  app.api.setWidgetVisible('boxes', false);
  assert.equal(app.document.querySelector('.boxes-section').classList.contains('hidden'), true);
});

test('applyDockSideWidth / applyDockBottomHeight clamp to their ranges', () => {
  assert.equal(app.api.applyDockSideWidth(150), 200);
  assert.equal(app.api.applyDockSideWidth(9999), 720);
  assert.equal(app.$('dockSide').style.getPropertyValue('--dock-side-w'), '720px');
  assert.equal(app.api.applyDockBottomHeight(10), 100);
});

test('applyPanelSide toggles the body class', () => {
  app.set({ panelSide: 'right' });
  app.api.applyPanelSide();
  assert.equal(app.document.body.classList.contains('panel-left'), false);
  app.set({ panelSide: 'left' });
  app.api.applyPanelSide();
  assert.equal(app.document.body.classList.contains('panel-left'), true);
});

test('setAppearanceControls reflects the current state in the form', () => {
  app.set({ panelSide: 'right' });
  app.api.setDockState('boxes', 'float');
  app.api.setWidgetVisible('boxes', false);
  app.api.setAppearanceControls();
  assert.equal(app.$('panelSideSel').value, 'right');
  assert.equal(app.$('boxesDockSel').value, 'float');
  assert.equal(app.$('boxesVisibleSw').checked, false);
});

test('initSettings seeds auto-save and box visibility from settings', () => {
  app.api.settingsSet('autoSave', '1');
  app.api.settingsSet('ybe_show_boxes', '0');
  app.api.initSettings();
  assert.equal(app.state().settingsInitialized, true);
  assert.equal(app.state().autoSave, true);
  assert.equal(app.state().boxesVisible, false);
});

test('saveFloatPos / restoreFloatPos round-trip a window position', () => {
  const win = app.$('boxFloat');
  app.api.saveFloatPos(win);
  const raw = app.api.settingsGet('ybe_float_boxFloat');
  assert.deepEqual(JSON.parse(raw), { x: win.offsetLeft, y: win.offsetTop });
  app.api.restoreFloatPos(win);
  // jsdom has no layout, so the saved 0,0 clamps to the 8px margin
  assert.equal(win.style.left, '8px');
  // with nothing saved, the default position for boxFloat is used
  app.api.settingsSet('ybe_float_boxFloat', null);
  app.api.restoreFloatPos(win);
  assert.notEqual(win.style.left, '8px');
});
