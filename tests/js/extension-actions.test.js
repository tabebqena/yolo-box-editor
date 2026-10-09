'use strict';

// Extension app actions and the app-action lifecycle bus.

const { test, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const { createApp, plain } = require('./helpers/app.js');

let app;
beforeEach(() => { app = createApp(); });
afterEach(() => { app.cleanup(); });

function capture() {
  const calls = [];
  app.consts.PANELS.fake = { target: { postMessage: (m) => calls.push(m) } };
  return calls;
}

test('invokeAppAction broadcasts before/after events around a core action', async () => {
  const calls = capture();
  let ran = false;
  await app.api.invokeAppAction('app_show_hide', { preventDefault() {} }, () => { ran = true; });
  assert.equal(ran, true);
  const events = calls.filter((m) => m.kind === 'evt').map((m) => m.event);
  assert.deepEqual(events, ['before_app_action', 'after_app_action']);
  const after = calls.find((m) => m.event === 'after_app_action');
  assert.equal(after.payload.action, 'app_show_hide');
  assert.equal(after.payload.extension, null);
  assert.equal(after.payload.depth, 0);
  assert.equal(after.payload.ok, true);
  delete app.consts.PANELS.fake;
});

test('an extension action reaches a mounted panel as an app_action event', async () => {
  const calls = capture();
  app.consts.PANELS['panel.tags'] = { target: { postMessage: (m) => calls.push(m) } };
  await app.api.callExtensionAction('tags', 'clear_tags', { depth: 0, chain: 'c1' });
  const act = calls.find((m) => m.event === 'app_action');
  assert.ok(act);
  assert.equal(act.payload.action, 'ext.tags.clear_tags');
  assert.equal(act.payload.extension, 'tags');
  assert.equal(act.payload.name, 'clear_tags');
  delete app.consts.PANELS.fake;
  delete app.consts.PANELS['panel.tags'];
});

test('an unmounted extension action falls back to its backend capability', async () => {
  app.set({
    images: [{ split: 'train', name: 'a.jpg' }],
    currentIndex: 0,
    extensionPackages: [{ id: 'tags', app_actions: [{ name: 'clear_tags', capability: 'tags.clear' }] }],
  });
  let posted = null;
  app.fetchMock.on('/api/extensions/call', (url, method, entry) => {
    posted = JSON.parse(entry.body);
    return { body: { ok: true, value: { tags: [] } } };
  });
  await app.api.invokeAppAction('ext.tags.clear_tags', { preventDefault() {} }, null);
  assert.deepEqual(posted, { package: 'tags', method: 'tags.clear', args: ['train/a.jpg'] });
});

test('the event chain is refused past MAX_EVENT_DEPTH', async () => {
  await assert.rejects(
    () => app.api.invokeAppAction('app_show_hide', { preventDefault() {} }, () => 1,
      { depth: 8, chain: 'c1' }),
    /chain exceeded/);
});

test('dispatchAppShortcut runs an extension action by its declared shortcut', async () => {
  app.set({
    extensionAppActions: [{ id: 'ext.tags.toggle_tag_1', name: 'toggle_tag_1', shortcut: 'Alt+1' }],
    images: [{ split: 'train', name: 'a.jpg' }],
    currentIndex: 0,
    extensionPackages: [{ id: 'tags', app_actions: [{ name: 'toggle_tag_1', capability: 'tags.get' }] }],
  });
  let posted = null;
  app.fetchMock.on('/api/extensions/call', (url, method, entry) => {
    posted = JSON.parse(entry.body);
    return { body: { ok: true, value: ['fire'] } };
  });
  const handled = app.api.dispatchAppShortcut({
    code: 'Digit1', key: '1', ctrlKey: false, altKey: true, shiftKey: false, metaKey: false,
    preventDefault() {},
  });
  assert.equal(handled, true);
  await app.flush();
  assert.equal(posted.method, 'tags.get');
});
