'use strict';

// User actions, event hooks and the action-result modal.

const { test, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const { createApp } = require('./helpers/app.js');

let app;
beforeEach(() => { app = createApp(); app.window.confirm = () => true; });
afterEach(() => { app.cleanup(); });

function ready(overrides = {}) {
  app.set({
    images: [{ split: 'train', name: 'a.jpg' }],
    currentIndex: 0,
    classes: ['cat'],
    datasetLoaded: true,
    ...overrides,
  });
}

test('showActionResult fills the modal for a success', () => {
  app.api.showActionResult({
    ok: true, action: 'Greet', command: 'echo hi', exit_code: 0, stdout: 'hi', stderr: '',
  });
  assert.equal(app.api.isHidden('actionResult'), false);
  assert.equal(app.$('actionResultTitle').textContent, 'Greet — succeeded');
  assert.equal(app.$('actionResultTitle').style.color, 'var(--green)');
  assert.equal(app.$('actionResultCmd').textContent, '$ echo hi');
  assert.equal(app.$('actionResultExit').textContent, 'exit code: 0');
  assert.equal(app.$('actionResultOut').textContent, 'hi');
  // empty stderr gets the dimmed empty style
  assert.equal(app.$('actionResultErr').classList.contains('modal-empty'), true);
});

test('showActionResult marks a failure', () => {
  app.api.showActionResult({ ok: false, action: 'Bad', error: 'boom', exit_code: 1 });
  assert.equal(app.$('actionResultTitle').textContent, 'Bad — failed');
  assert.equal(app.$('actionResultTitle').style.color, 'var(--red)');
  assert.equal(app.$('actionResultCmd').textContent, 'boom');
  app.api.closeActionResult();
  assert.equal(app.api.isHidden('actionResult'), true);
});

test('setActionButtonsDisabled disables every action button', () => {
  app.set({ actionShortcuts: {} });
  app.api.populateActions(['A', 'B']);
  app.api.setActionButtonsDisabled(true);
  app.api.qsa('#actionBtns button').forEach((b) => assert.equal(b.disabled, true));
  app.api.setActionButtonsDisabled(false);
  app.api.qsa('#actionBtns button').forEach((b) => assert.equal(b.disabled, false));
});

test('populateActions attaches shortcut badges', () => {
  app.set({ actionShortcuts: { B: { shortcut: 'Ctrl+B', label: 'B' } } });
  app.api.populateActions(['A', 'B']);
  const buttons = app.$('actionBtns').querySelectorAll('button');
  assert.equal(buttons.length, 2);
  assert.equal(buttons[0].querySelector('.btn-shortcut'), null);
  assert.equal(buttons[1].querySelector('.btn-shortcut').textContent, 'Ctrl+B');
  assert.match(buttons[1].title, /Ctrl\+B/);
});

test('applyActionOverflow hides the fourth action until expanded', () => {
  app.set({ actionShortcuts: {} });
  app.api.populateActions(['A', 'B', 'C', 'D']);
  const buttons = app.$('actionBtns').querySelectorAll('button');
  assert.equal(app.$('actionsExpandBtn').classList.contains('hidden'), false);
  assert.equal(buttons[3].classList.contains('hidden'), true);

  app.click('actionsExpandBtn');
  assert.equal(buttons[3].classList.contains('hidden'), false);
  assert.equal(app.$('actionsExpandBtn').title, 'Show fewer actions');
});

test('runAction runs a server action and shows the result', async () => {
  ready();
  app.fetchMock.on('/api/actions/run', () => ({
    body: { ok: true, action: 'Greet', command: 'echo hi', exit_code: 0, stdout: 'hi', stderr: '' },
  }));
  const ok = await app.api.runAction('Greet');
  assert.equal(ok, true);
  assert.equal(app.api.isHidden('actionResult'), false);
});

test('runAction drives an after_success client action and resumes the server', async () => {
  ready({ boxesVisible: true });
  let calls = 0;
  app.fetchMock.on('/api/actions/run', (url, method, entry) => {
    calls += 1;
    const body = JSON.parse(entry.body);
    if (body.uid) return { body: { ok: true, action: 'Archive', exit_code: 0 } };
    return { body: { ok: true, client_action: 'app_show_hide', uid: 'u1' } };
  });
  const ok = await app.api.runAction('Archive');
  assert.equal(ok, true);
  assert.equal(calls, 2);
  assert.equal(app.state().boxesVisible, false); // the client action ran
});

test('runAction returns false and shows the modal when the action fails', async () => {
  ready();
  app.fetchMock.on('/api/actions/run', () => ({
    body: { ok: false, action: 'Bad', error: 'nope', exit_code: 1 },
  }));
  const ok = await app.api.runAction('Bad');
  assert.equal(ok, false);
  assert.match(app.$('actionResultTitle').textContent, /failed/);
});

test('runAction does nothing without a current image', async () => {
  ready({ currentIndex: -1 });
  assert.equal(await app.api.runAction('Greet'), false);
});

test('runAction honours confirm:false (used by hooks)', async () => {
  ready();
  app.fetchMock.on('/api/actions/run', () => ({ body: { ok: true, action: 'H' } }));
  app.window.confirm = () => { throw new Error('confirm should not be called'); };
  const ok = await app.api.runAction('H', { confirm: false, hook: true });
  assert.equal(ok, true);
});

test('runHook only fires defined hooks and guards against re-entry', async () => {
  ready({ hooksByName: new Set(['on_box_created']) });
  let calls = 0;
  app.fetchMock.on('/api/actions/run', () => { calls += 1; return { body: { ok: true, action: 'on_box_created' } }; });
  assert.equal(await app.api.runHook('on_unknown'), true);
  assert.equal(calls, 0);
  await app.api.runHook('on_box_created');
  assert.equal(calls, 1);

  app.set({ hookInFlight: new Set(['on_box_created']) });
  await app.api.runHook('on_box_created');
  assert.equal(calls, 1); // skipped while already running
});

test('postActionRun posts the body to the actions endpoint', async () => {
  let posted = null;
  app.fetchMock.on('/api/actions/run', (url, method, entry) => {
    posted = JSON.parse(entry.body);
    return { body: { ok: true } };
  });
  const data = await app.api.postActionRun({ action: 'A', target: 'train/a.jpg' });
  assert.equal(data.ok, true);
  assert.equal(posted.action, 'A');
});
