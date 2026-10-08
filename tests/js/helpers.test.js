'use strict';

// Unit tests for the pure helper functions in app.js: DOM builders, geometry,
// settings lookup and keyboard-shortcut parsing.

const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { createApp, plain } = require('./helpers/app.js');

let app;
before(() => { app = createApp(); });
after(() => { app.cleanup(); });

test('mk builds a tagged element with optional class and text', () => {
  const a = app.api.mk('div');
  assert.equal(a.tagName, 'DIV');
  assert.equal(a.className, '');
  const b = app.api.mk('span', 'x y', 'hi');
  assert.equal(b.className, 'x y');
  assert.equal(b.textContent, 'hi');
  // numeric text is coerced like textContent would be
  assert.equal(app.api.mk('span', null, 7).textContent, '7');
});

test('option builds an <option>, text defaulting to the value', () => {
  const a = app.api.option('v', 'Label');
  assert.equal(a.tagName, 'OPTION');
  assert.equal(a.value, 'v');
  assert.equal(a.textContent, 'Label');
  const b = app.api.option('only');
  assert.equal(b.value, 'only');
  assert.equal(b.textContent, '');
});

test('setHidden / showEl / hideEl / isHidden toggle the hidden class', () => {
  app.document.body.innerHTML = '<div id="secret" class="hidden"></div>';
  assert.equal(app.api.isHidden('secret'), true);
  assert.equal(app.api.isHidden('missing'), true);
  app.api.showEl('secret');
  assert.equal(app.api.isHidden('secret'), false);
  app.api.hideEl('secret');
  assert.equal(app.api.isHidden('secret'), true);
  app.api.setHidden('secret', false);
  assert.equal(app.$('secret').classList.contains('hidden'), false);
  // accepts a node as well as an id
  app.api.setHidden(app.$('secret'), true);
  assert.equal(app.$('secret').classList.contains('hidden'), true);
});

test('onEl attaches a listener and returns the node; missing ids are ignored', () => {
  app.document.body.innerHTML = '<button id="b"></button>';
  let hits = 0;
  const node = app.api.onEl('b', 'click', () => { hits += 1; });
  assert.equal(node, app.$('b'));
  app.click('b');
  assert.equal(hits, 1);
  assert.equal(app.api.onEl('nope', 'click', () => {}), null);
});

test('qs and qsa find nodes within a root', () => {
  app.document.body.innerHTML = '<div id="root"><i class="x"></i><i class="x"></i></div>';
  assert.equal(app.api.qs('#root .x'), app.$('root').children[0]);
  assert.equal(app.api.qsa('.x', app.$('root')).length, 2);
  assert.equal(app.api.qsa('.x', app.$('root'))[1], app.$('root').children[1]);
});

test('clamp01 clamps to the 0..1 range', () => {
  assert.equal(app.api.clamp01(-1), 0);
  assert.equal(app.api.clamp01(0.5), 0.5);
  assert.equal(app.api.clamp01(2), 1);
});

test('toPx / toNorm convert between normalised and pixel boxes', () => {
  app.set({ imgW: 200, imgH: 100, defaultClass: 2 });
  const px = app.api.toPx({ cx: 0.5, cy: 0.5, w: 0.2, h: 0.4 });
  assert.deepEqual(plain(px), { x: 80, y: 30, w: 40, h: 40 });
  const norm = app.api.toNorm({ x: 0, y: 0, w: 100, h: 50 });
  assert.deepEqual(plain(norm), { class: 2, cx: 0.25, cy: 0.25, w: 0.5, h: 0.5 });
});

test('normRect returns the enclosing rectangle regardless of drag direction', () => {
  assert.deepEqual(plain(app.api.normRect({ x: 10, y: 20 }, { x: 30, y: 5 })), { x: 10, y: 5, w: 20, h: 15 });
});

test('clampToImage keeps a point inside the image', () => {
  app.set({ imgW: 200, imgH: 100 });
  assert.deepEqual(plain(app.api.clampToImage({ x: -5, y: 200 })), { x: 0, y: 100 });
  assert.deepEqual(plain(app.api.clampToImage({ x: 50, y: 60 })), { x: 50, y: 60 });
});

test('handlePoints returns the eight resize handles in order', () => {
  const pts = app.api.handlePoints({ x: 10, y: 20, w: 100, h: 50 });
  assert.deepEqual(plain(pts.map((p) => p.name)), ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']);
  assert.deepEqual(plain(pts[0]), { x: 10, y: 20, name: 'nw' });
  assert.deepEqual(plain(pts[4]), { x: 110, y: 70, name: 'se' });
});

test('fmtNum rounds to four decimals', () => {
  assert.equal(app.api.fmtNum(0.123456), 0.1235);
  assert.equal(app.api.fmtNum(1), 1);
});

test('shortcutKeyFromEvent maps codes and named keys', () => {
  assert.equal(app.api.shortcutKeyFromEvent({ code: 'KeyA', key: 'a' }), 'A');
  assert.equal(app.api.shortcutKeyFromEvent({ code: 'Digit5', key: '5' }), '5');
  assert.equal(app.api.shortcutKeyFromEvent({ code: 'Space', key: ' ' }), 'Space');
  assert.equal(app.api.shortcutKeyFromEvent({ code: 'Escape', key: 'Escape' }), 'Escape');
  assert.equal(app.api.shortcutKeyFromEvent({ code: 'F1', key: 'F1' }), null);
});

test('shortcutMatches respects modifiers, letters, digits and named keys', () => {
  const m = app.api.shortcutMatches;
  assert.equal(m({ ctrlKey: true, altKey: false, shiftKey: false, metaKey: false, code: 'KeyS', key: 's' }, 'Ctrl+S'), true);
  assert.equal(m({ ctrlKey: false, altKey: false, shiftKey: false, metaKey: false, code: 'KeyS', key: 's' }, 'Ctrl+S'), false);
  assert.equal(m({ ctrlKey: false, altKey: false, shiftKey: false, metaKey: false, code: 'KeyS', key: 's' }, 'S'), true);
  assert.equal(m({ ctrlKey: false, altKey: false, shiftKey: false, metaKey: false, code: 'Digit3', key: '3' }, '3'), true);
  assert.equal(m({ ctrlKey: false, altKey: false, shiftKey: false, metaKey: false, code: 'Delete', key: 'Delete' }, 'Delete'), true);
  assert.equal(m({ ctrlKey: false, altKey: false, shiftKey: false, metaKey: false, code: 'Space', key: ' ' }, 'Space'), true);
  assert.equal(m({ ctrlKey: true, altKey: true, shiftKey: true, metaKey: false, code: 'KeyA', key: 'a' }, 'Ctrl+Alt+Shift+A'), true);
});

test('forceDrawActive reads the app_force_draw binding and falls back to Ctrl', () => {
  app.set({ appShortcuts: {} });
  assert.equal(app.api.forceDrawActive({ ctrlKey: true }), true);
  assert.equal(app.api.forceDrawActive({ ctrlKey: false }), false);
  app.set({ appShortcuts: { app_force_draw: { shortcut: 'Alt' } } });
  assert.equal(app.api.forceDrawActive({ altKey: true }), true);
  assert.equal(app.api.forceDrawActive({ ctrlKey: true }), false);
});

test('imageKey and keyQuery identify an image independent of its index', () => {
  assert.equal(app.api.imageKey({ split: 'train', name: 'a.jpg' }), 'train/a.jpg');
  assert.equal(app.api.imageKey(null), null);
  assert.equal(app.api.keyQuery({ split: 'train', name: 'a.jpg' }), '?key=train%2Fa.jpg');
});

test('captureImageAnchor records the current path and the ones after it', () => {
  app.set({
    images: [
      { split: 'train', name: 'a' },
      { split: 'train', name: 'b' },
      { split: 'train', name: 'c' },
    ],
    currentIndex: 1,
  });
  assert.deepEqual(plain(app.api.captureImageAnchor(true)), {
    path: 'train/b', following: ['train/c'], follow: true,
  });
  assert.deepEqual(plain(app.api.captureImageAnchor(false)), {
    path: 'train/b', following: [], follow: false,
  });
  app.set({ currentIndex: -1 });
  assert.equal(app.api.captureImageAnchor(), null);
});

test('resolveImageAnchor prefers the same path, then the next surviving image', () => {
  app.set({
    images: [
      { split: 'train', name: 'a' },
      { split: 'train', name: 'c' },
    ],
    currentIndex: 1,
  });
  assert.equal(app.api.resolveImageAnchor({ path: 'train/c', following: [] }), 1);
  // the anchored image is gone; follow its successor, then fall back
  assert.equal(app.api.resolveImageAnchor({ path: 'train/b', following: ['train/c'], follow: true }), 1);
  assert.equal(app.api.resolveImageAnchor({ path: 'train/z', following: [], follow: false }), 0);
  assert.equal(app.api.resolveImageAnchor({ path: 'train/z', following: [], follow: true }), 1);
  app.set({ images: [] });
  assert.equal(app.api.resolveImageAnchor({ path: 'x' }), -1);
});

test('defaultFloatPos places each window without overlapping the others', () => {
  const box = app.document.createElement('div');
  box.id = 'boxFloat';
  assert.deepEqual(plain(app.api.defaultFloatPos(box)), { x: 684, y: 90 });
  const tag = app.document.createElement('div');
  tag.id = 'tagFloat';
  assert.deepEqual(plain(app.api.defaultFloatPos(tag)), { x: 24, y: 508 });
});

test('clampFloatPos keeps a floating window on screen', () => {
  const win = app.document.createElement('div');
  const p = app.api.clampFloatPos(win, 1000, -5);
  assert.equal(p.x, 756);
  assert.equal(p.y, 8);
});

test('savedDock / savedVisible read browser settings with sane defaults', () => {
  app.window.localStorage.clear();
  assert.equal(app.api.savedDock('k'), 'default');
  assert.equal(app.api.savedVisible('k'), true);
  app.window.localStorage.setItem('k', 'left');
  assert.equal(app.api.savedDock('k'), 'left');
  app.window.localStorage.setItem('k', 'nowhere');
  assert.equal(app.api.savedDock('k'), 'default');
  app.window.localStorage.setItem('k', '0');
  assert.equal(app.api.savedVisible('k'), false);
});

test('filterDef looks a filter up by name', () => {
  app.set({ filters: [{ name: 'keep', description: 'd' }] });
  assert.equal(app.api.filterDef('keep').description, 'd');
  assert.equal(app.api.filterDef('missing'), null);
});

test('versionBadge reflects the extension api_version status', () => {
  const newer = app.api.versionBadge({ status: 'newer' });
  assert.match(newer.className, /ext-badge-newer/);
  assert.match(newer.textContent, /newer/);
  app.set({ extensionApiVersion: 3 });
  const current = app.api.versionBadge({ status: 'current', api_version: 3 });
  assert.match(current.textContent, /v3/);
  const outdated = app.api.versionBadge({ status: 'outdated', api_version: 2 });
  assert.match(outdated.textContent, /outdated v2/);
  const unknown = app.api.versionBadge({});
  assert.match(unknown.textContent, /outdated/);
});

test('EXT_TYPE_LABELS names every step type', () => {
  const labels = app.consts.EXT_TYPE_LABELS;
  assert.equal(labels.cmd, 'Shell command');
  assert.equal(labels.app, 'App action');
  assert.equal(labels.backend, 'Server action');
  assert.equal(labels.action, 'Other action');
});
