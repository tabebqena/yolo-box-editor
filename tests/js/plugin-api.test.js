'use strict';

// Sandboxed UI-panel bridge (host side): capability table, message protocol,
// srcdoc/CSP builder and mount/unmount.

const { test, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const { createApp, plain } = require('./helpers/app.js');

let app;
beforeEach(() => { app = createApp(); });
afterEach(() => { app.cleanup(); });

test('ybeHandleRequest returns state copies', async () => {
  app.set({ imageTags: ['a', 'b'] });
  const tags = await app.api.ybeHandleRequest('state.getTags', []);
  assert.deepEqual(plain(tags), ['a', 'b']);
  tags.push('c');
  assert.deepEqual(plain(app.state().imageTags), ['a', 'b']);
});

test('ybeHandleRequest rejects unknown methods', async () => {
  await assert.rejects(() => app.api.ybeHandleRequest('bogus.method', []),
    /unknown YBE method/);
});

test('mutating callbacks refuse in read-only mode', async () => {
  app.set({
    readonly: true,
    images: [{ split: 'train', name: 'a.jpg' }],
    currentIndex: 0,
    imageTags: [],
  });
  await assert.rejects(() => app.api.ybeHandleRequest('callbacks.addTag', ['x']),
    /read-only/);
});

test('callbacks.addTag adds a tag', async () => {
  app.set({
    readonly: false,
    images: [{ split: 'train', name: 'a.jpg' }],
    currentIndex: 0,
    imageTags: [],
  });
  await app.api.ybeHandleRequest('callbacks.addTag', ['fire']);
  assert.deepEqual(plain(app.state().imageTags), ['fire']);
});

test('callbacks.setBoxes validates and clamps', async () => {
  app.set({
    readonly: false,
    images: [{ split: 'train', name: 'a.jpg' }],
    currentIndex: 0,
    boxes: [],
  });
  await app.api.ybeHandleRequest('callbacks.setBoxes',
    [[{ class: 0, cx: 1.5, cy: -1, w: 0.2, h: 0.2 }]]);
  const b = app.state().boxes[0];
  assert.equal(b.cx, 1);
  assert.equal(b.cy, 0);
  await assert.rejects(() => app.api.ybeHandleRequest('callbacks.setBoxes',
    [[{ class: 0, cx: 'x', cy: 0, w: 0, h: 0 }]]), /invalid box/);
});

test('emitUiEvent forwards to mounted panels', () => {
  const calls = [];
  app.consts.PANELS.fake = { target: { postMessage: (m) => calls.push(m) } };
  app.api.emitUiEvent('saved', { count: 2 });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].__ybe, true);
  assert.equal(calls[0].kind, 'evt');
  assert.equal(calls[0].event, 'saved');
  assert.deepEqual(calls[0].payload, { count: 2 });
  delete app.consts.PANELS.fake;
});

test('handlePanelMessage answers a request with a response', async () => {
  const calls = [];
  app.consts.PANELS.fake = { target: { postMessage: (m) => calls.push(m) } };
  app.set({ currentIndex: 3 });
  app.api.handlePanelMessage('fake',
    { __ybe: true, kind: 'req', id: 7, method: 'state.getImageIndex', args: [] });
  await app.flush();
  const res = calls.find((m) => m.kind === 'res');
  assert.ok(res);
  assert.equal(res.id, 7);
  assert.equal(res.ok, true);
  assert.equal(res.value, 3);
  delete app.consts.PANELS.fake;
});

test('handlePanelMessage reports an unknown method', async () => {
  const calls = [];
  app.consts.PANELS.fake = { target: { postMessage: (m) => calls.push(m) } };
  app.api.handlePanelMessage('fake',
    { __ybe: true, kind: 'req', id: 1, method: 'nope', args: [] });
  await app.flush();
  const res = calls.find((m) => m.kind === 'res');
  assert.equal(res.ok, false);
  assert.match(res.error, /unknown YBE method/);
  delete app.consts.PANELS.fake;
});

test('buildPanelSrcdoc embeds a strict CSP and inlines the script', () => {
  const evil = 'var x = 1;<\/script>;';
  const html = app.api.buildPanelSrcdoc(evil);
  assert.match(html, /Content-Security-Policy/);
  assert.match(html, /connect-src 'none'/);
  assert.match(html, /img-src 'none'/);
  assert.match(html, /nonce-/);
  assert.match(html, /var x = 1/);
  assert.equal(html.indexOf('</script>;'), -1, 'closing tag must be escaped');
});

test('buildPanelSrcdoc numbers the plugin API version', () => {
  app.set({ pluginApiVersion: 1 });
  const html = app.api.buildPanelSrcdoc('');
  assert.match(html, /window\.__YBE_API_VERSION=1/);
});

test('mountExtensionPanel mounts a sandboxed iframe and unmounts', () => {
  app.api.mountExtensionPanel(
    { id: 'p1', name: 'P1', ui: { title: 'P1', script: 'p.js', status: 'current', location: 'right' } },
    'window.YBE;');
  assert.ok(app.consts.PANELS['panel.p1']);
  const body = app.$('widgetBody_panel.p1');
  const iframe = body && body.querySelector('iframe');
  assert.ok(iframe);
  assert.equal(iframe.getAttribute('sandbox'), 'allow-scripts');
  assert.ok(app.$('widgetDock_panel_p1'));
  app.api.unmountExtensionPanel('panel.p1');
  assert.equal(app.consts.PANELS['panel.p1'], undefined);
});
