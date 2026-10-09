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
  app.set({ boxes: [{ class: 0, cx: 0.1, cy: 0.2, w: 0.3, h: 0.4 }] });
  const boxes = await app.api.ybeHandleRequest('state.getBoxes', []);
  assert.deepEqual(plain(boxes), [{ class: 0, cx: 0.1, cy: 0.2, w: 0.3, h: 0.4, fixed: false }]);
  boxes[0].cx = 0.9;
  assert.equal(app.state().boxes[0].cx, 0.1);
});

test('ybeHandleRequest rejects unknown methods', async () => {
  await assert.rejects(() => app.api.ybeHandleRequest('bogus.method', []),
    /unknown YBE method/);
});

test('the `call` capability forwards to the caller package backend', async () => {
  let posted = null;
  app.fetchMock.on('/api/extensions/call', (u, m, entry) => {
    posted = JSON.parse(entry.body);
    return { body: { ok: true, value: ['fire'] } };
  });
  const value = await app.api.ybeHandleRequest(
    'call', ['tags.available', []], null, { packageId: 'tags' });
  assert.deepEqual(plain(value), ['fire']);
  assert.deepEqual(posted, { package: 'tags', method: 'tags.available', args: [] });
});

test('state.getConfig returns the app config', async () => {
  app.fetchMock.on('/api/config', () => ({ body: { data_yaml: '/d/data.yaml', classes: ['a'] } }));
  const cfg = await app.api.ybeHandleRequest('state.getConfig', []);
  assert.deepEqual(plain(cfg), { data_yaml: '/d/data.yaml', classes: ['a'] });
});

test('api.request proxies same-origin /api paths and refuses auth routes', async () => {
  app.fetchMock.on('/api/images', () => ({ body: { images: [] } }));
  const got = await app.api.ybeHandleRequest('api.request', ['GET', '/api/images']);
  assert.deepEqual(plain(got), { images: [] });
  await assert.rejects(() => app.api.ybeHandleRequest('api.request', ['GET', '/api/login']),
    /auth routes/);
  await assert.rejects(() => app.api.ybeHandleRequest('api.request', ['GET', '/etc/passwd']),
    /only \/api\//);
  await assert.rejects(() => app.api.ybeHandleRequest('api.request', ['DELETE', '/api/images']),
    /GET and POST/);
});

test('a panel may only call YBE methods its package declares', async () => {
  app.set({
    pluginPermissionMap: { 'state.getImage': 'state.read' },
    extensionPackages: [{ id: 'p', permissions: { ybe: [] } }],
  });
  await assert.rejects(
    () => app.api.ybeHandleRequest('state.getImage', [], null, { packageId: 'p' }),
    /permission denied/);
  app.set({ extensionPackages: [{ id: 'p', permissions: { ybe: ['state.read'] } }] });
  const img = await app.api.ybeHandleRequest('state.getImage', [], null, { packageId: 'p' });
  assert.equal(img, null);
});

test('a package without a permissions file is allowed (legacy)', async () => {
  app.set({
    pluginPermissionMap: { 'state.getImage': 'state.read' },
    extensionPackages: [{ id: 'p', permissions: null }],
  });
  const img = await app.api.ybeHandleRequest('state.getImage', [], null, { packageId: 'p' });
  assert.equal(img, null);
});

test('mutating callbacks refuse in read-only mode', async () => {
  app.set({
    readonly: true,
    images: [{ split: 'train', name: 'a.jpg' }],
    currentIndex: 0,
    boxes: [],
  });
  await assert.rejects(() => app.api.ybeHandleRequest('callbacks.setBoxes', [[]]),
    /read-only/);
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

test('buildPanelSrcdoc forwards a color-scheme so panels match the app', () => {
  const html = app.api.buildPanelSrcdoc('');
  assert.match(html, /:root\{color-scheme:/);
  assert.match(html, /color-scheme:dark/);
});

test('panelSourceAccepted trusts the live iframe window across a reload', () => {
  const oldWin = {};
  const newWin = {};
  const panel = { iframe: { contentWindow: newWin }, target: oldWin };
  assert.equal(app.api.panelSourceAccepted(panel, newWin), true);
  assert.equal(app.api.panelSourceAccepted(panel, oldWin), false);
  assert.equal(app.api.panelSourceAccepted({ iframe: null }, oldWin), true);
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
