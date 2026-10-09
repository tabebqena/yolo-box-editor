'use strict';

// Custom widgets and extension packages.

const { test, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const { createApp } = require('./helpers/app.js');

let app;
beforeEach(() => { app = createApp(); });
afterEach(() => { app.cleanup(); });

const WIDGET = {
  name: 'Tools',
  title: 'Tools',
  status: 'current',
  controls: [
    { type: 'button', label: 'Go', action: null, steps: ['echo hi'], after_success: [] },
    { type: 'select', id: 'mode', label: 'Mode', options: ['a', 'b'], default: 'a' },
    { type: 'checkbox', id: 'dry', label: 'Dry', default: true },
    { type: 'input', id: 'suffix', label: 'Suffix', default: '', placeholder: '' },
  ],
};

test('renderCustomWidgets builds a frame, controls and a Layout block', () => {
  app.set({ widgetDefs: [WIDGET] });
  app.api.renderCustomWidgets();
  assert.ok(app.$('widgetFrame_Tools'));
  const content = app.$('widgetBody_Tools');
  assert.equal(content.querySelectorAll('.widget-button').length, 1);
  assert.equal(content.querySelectorAll('[data-control-id]').length, 3);
  // Layout tab controls + registry entry
  assert.ok(app.$('widgetDock_Tools'));
  assert.ok(app.$('widgetVis_Tools'));
  assert.ok(app.consts.WIDGETS.Tools);
  assert.equal(app.api.getDock('Tools'), 'float');
  assert.equal(app.api.getWidgetVisible('Tools'), true);
});

test('custom widget content collects control values', () => {
  const root = app.api.buildWidgetContent(WIDGET, () => {});
  const values = root.collect();
  assert.equal(values.mode, 'a');
  assert.equal(values.dry, '1');
  assert.equal(values.suffix, '');
});

test('renderCustomWidgets clears previous widgets on reload', () => {
  app.set({ widgetDefs: [WIDGET] });
  app.api.renderCustomWidgets();
  assert.ok(app.$('widgetFrame_Tools'));
  app.set({ widgetDefs: [] });
  app.api.renderCustomWidgets();
  assert.equal(app.$('widgetFrame_Tools'), null);
  assert.equal(app.consts.WIDGETS.Tools, undefined);
  assert.equal(app.$('customWidgetSettings').children.length, 0);
});

test('runWidgetControl posts values and resumes a client action', async () => {
  app.set({
    widgetDefs: [WIDGET],
    images: [{ split: 'train', name: 'a.jpg' }],
    currentIndex: 0,
  });
  let widgetBody = null;
  let resumeBody = null;
  app.fetchMock.on('/api/widgets/run', (url, method, entry) => {
    widgetBody = JSON.parse(entry.body);
    return { body: { ok: true, uid: 'u1', client_action: 'app_focus_canvas' } };
  });
  app.fetchMock.on('/api/actions/run', (url, method, entry) => {
    resumeBody = JSON.parse(entry.body);
    return { body: { ok: true } };
  });
  const root = app.api.buildWidgetContent(WIDGET, () => {});
  await app.api.runWidgetControl('Tools', 0, root);
  assert.equal(widgetBody.widget, 'Tools');
  assert.equal(widgetBody.control, 0);
  assert.equal(widgetBody.target, 'train/a.jpg');
  assert.equal(widgetBody.values.mode, 'a');
  assert.equal(resumeBody.uid, 'u1');
});

const PACKAGE = {
  id: 'mypack',
  name: 'My Pack',
  description: 'demo',
  version: '1.0.0',
  author: 'me',
  active: true,
  source: 'user',
  api_version: 3,
  status: 'current',
  parts: { action: ['pack_action.yaml'] },
  settings: {
    title: 'Pack settings',
    controls: [
      { type: 'checkbox', id: 'verbose', label: 'Verbose', default: false },
      { type: 'button', label: 'Refresh', steps: [], action: null, after_success: [] },
    ],
  },
};

test('renderExtensionsTab builds one subtab per package', () => {
  app.set({ extensionPackages: [PACKAGE] });
  app.api.renderExtensionsTab();
  const body = app.$('extensionTabBody');
  const tab = body.querySelector('.sub-tab');
  assert.ok(tab);
  assert.equal(tab.dataset.sub, 'mypack');
  assert.ok(body.querySelector('.package-name'));
  assert.ok(body.querySelector('.widget-button'));
});

test('the package Enabled toggle posts the override', async () => {
  app.set({ extensionPackages: [PACKAGE] });
  app.api.renderExtensionsTab();
  let body = null;
  app.fetchMock.on('/api/extensions/active', (url, method, entry) => {
    body = JSON.parse(entry.body);
    return { body: { ok: true, active: false } };
  });
  const cb = app.$('extensionTabBody').querySelector('.package-active input');
  assert.equal(cb.checked, true);
  cb.checked = false;
  cb.dispatchEvent(new app.window.Event('change', { bubbles: true }));
  await app.flush();
  assert.deepEqual(body, { package: 'mypack', active: false });
});

test('renderExtensionsTab shows a hint with no packages', () => {
  app.set({ extensionPackages: [] });
  app.api.renderExtensionsTab();
  assert.match(app.$('extensionTabBody').textContent, /No extension packages/);
});

test('runPackageControl posts to /api/extensions/run', async () => {
  app.set({
    extensionPackages: [PACKAGE],
    images: [{ split: 'train', name: 'a.jpg' }],
    currentIndex: 0,
  });
  let body = null;
  app.fetchMock.on('/api/extensions/run', (url, method, entry) => {
    body = JSON.parse(entry.body);
    return { body: { ok: true } };
  });
  const root = app.api.buildWidgetContent(PACKAGE.settings, () => {});
  await app.api.runPackageControl('mypack', 1, root);
  assert.equal(body.package, 'mypack');
  assert.equal(body.control, 1);
  assert.equal(body.target, 'train/a.jpg');
});

const ENV_PACKAGE = Object.assign({}, PACKAGE, {
  environment: {
    declared: true,
    status: 'missing',
    mode: 'venv',
    requirements: ['ultralytics>=8'],
    env_dir: '/home/extension_envs/mypack',
  },
});

test('a package with an environment shows its status and a Set up button', () => {
  app.set({ extensionPackages: [ENV_PACKAGE] });
  app.api.renderExtensionsTab();
  const sec = app.$('extensionTabBody').querySelector('.package-environment');
  assert.ok(sec);
  assert.match(sec.textContent, /not built yet/);
  assert.match(sec.textContent, /ultralytics>=8/);
  assert.match(sec.querySelector('button').textContent, /Set up environment/);
});

test('the Set up environment button posts to /api/extensions/env', async () => {
  app.set({ extensionPackages: [ENV_PACKAGE] });
  app.api.renderExtensionsTab();
  let body = null;
  app.fetchMock.on('/api/extensions/env', (url, method, entry) => {
    body = JSON.parse(entry.body);
    return { body: { ok: true } };
  });
  const btn = app.$('extensionTabBody').querySelector('.package-environment button');
  btn.dispatchEvent(new app.window.Event('click', { bubbles: true }));
  await app.flush();
  assert.deepEqual(body, { package: 'mypack' });
});

