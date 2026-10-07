'use strict';

// The built-in help modal: open via button/F1, tab switching, Escape.

const { test, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const { createApp } = require('./helpers/app.js');

let app;
beforeEach(() => { app = createApp(); });
afterEach(() => { app.cleanup(); });

// Serve each help fragment with its own file name, so a test can tell which
// tab's content landed in the modal body.
function serveHelp() {
  app.fetchMock.onPrefix('/static/help/', (url) => {
    const file = url.split('/').pop();
    return { body: `<h2>${file}</h2>` };
  });
}

test('the help button opens the modal on the Beginner tab', async () => {
  serveHelp();
  app.click('helpBtn');
  await app.flush();
  assert.equal(app.api.isHidden('helpModal'), false);
  const active = app.$('helpModal').querySelector('.help-tab.active');
  assert.equal(active.dataset.helpTab, 'beginner');
  assert.match(app.$('helpBody').innerHTML, /beginner\.html/);
});

test('selectHelpTab switches the active tab and loads its content', async () => {
  serveHelp();
  app.api.openHelp();
  await app.flush();
  app.api.selectHelpTab('expert');
  await app.flush();
  const active = app.$('helpModal').querySelector('.help-tab.active');
  assert.equal(active.dataset.helpTab, 'expert');
  assert.match(app.$('helpBody').innerHTML, /expert\.html/);
});

test('openHelp can target a tab directly', async () => {
  serveHelp();
  app.api.openHelp('howto');
  await app.flush();
  assert.match(app.$('helpBody').innerHTML, /howto\.html/);
});

test('the F1 shortcut opens help', async () => {
  serveHelp();
  app.set({ appShortcuts: { app_help: { shortcut: 'F1', label: 'help' } } });
  app.keydown(app.document, { key: 'F1', code: 'F1' });
  await app.flush();
  assert.equal(app.api.isHidden('helpModal'), false);
});

test('Escape closes the help modal', async () => {
  serveHelp();
  app.api.openHelp();
  await app.flush();
  app.keydown(app.document, { key: 'Escape' });
  assert.equal(app.api.isHidden('helpModal'), true);
});

test('a fetch failure shows a friendly message instead of throwing', async () => {
  app.fetchMock.onPrefix('/static/help/', () => ({ status: 500, ok: false, body: {} }));
  app.api.openHelp();
  await app.flush();
  assert.match(app.$('helpBody').innerHTML, /Could not load the help content/);
});
