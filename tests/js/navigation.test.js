'use strict';

// Image navigation, per-image loading/anchoring and view persistence.

const { test, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const { createApp, plain } = require('./helpers/app.js');

let app;
beforeEach(() => { app = createApp(); app.window.confirm = () => true; });
afterEach(() => { app.cleanup(); });

const IMAGES = [
  { split: 'train', name: 'a.jpg' },
  { split: 'train', name: 'b.jpg' },
  { split: 'train', name: 'c.jpg' },
];

function setImages(images = IMAGES, currentIndex = -1) {
  app.set({ images, currentIndex, classes: ['cat', 'dog'], datasetLoaded: true });
}

function annotations({ boxes = [], tags = [] } = {}) {
  app.fetchMock.onPrefix('/api/annotations', () => ({ body: { ok: true, boxes, tags } }));
}

test('updateNav fills the counter and enables/disables the nav buttons', () => {
  app.set({ images: [], currentIndex: -1 });
  app.api.updateNav();
  assert.equal(app.$('counter').value, '0 / 0');
  assert.equal(app.$('prevBtn').disabled, true);
  assert.equal(app.$('nextBtn').disabled, true);

  setImages(IMAGES, 1);
  app.api.updateNav();
  assert.equal(app.$('counter').value, '2 / 3');
  assert.equal(app.$('prevBtn').disabled, false);
  assert.equal(app.$('nextBtn').disabled, false);

  app.set({ currentIndex: 2 });
  app.api.updateNav();
  assert.equal(app.$('nextBtn').disabled, true);
});

test('loadImage fetches annotations for the image', async () => {
  setImages(IMAGES, -1);
  annotations({ boxes: [{ class: 0, cx: 0.5, cy: 0.5, w: 0.2, h: 0.2 }] });
  app.api.loadImage(1);
  assert.equal(app.state().currentIndex, 1);
  await app.flush();
  assert.equal(app.state().boxes.length, 1);
  assert.equal(app.state().boxes[0].class, 0);
  assert.match(app.imageEl().src, /\/api\/image\?key=train%2Fb\.jpg/);
});

test('loadImage clamps out-of-range indices', async () => {
  setImages(IMAGES);
  annotations();
  app.api.loadImage(99);
  assert.equal(app.state().currentIndex, 2);
  app.api.loadImage(-4);
  assert.equal(app.state().currentIndex, 0);
  await app.flush();
});

test('a stale loadImage response does not overwrite a newer one', async () => {
  setImages(IMAGES);
  const resolvers = [];
  app.fetchMock.onPrefix('/api/annotations', () => new Promise((resolve) => resolvers.push(resolve)));
  app.api.loadImage(0);
  app.api.loadImage(1);
  assert.equal(app.state().currentIndex, 1);
  // resolve the first request afterwards: it must be ignored
  resolvers[0]({ body: { ok: true, boxes: [{ class: 0, cx: 0.1, cy: 0.1, w: 0.1, h: 0.1 }] } });
  resolvers[1]({ body: { ok: true, boxes: [] } });
  await app.flush();
  assert.equal(app.state().boxes.length, 0);
});

test('go advances and stops at the ends', async () => {
  setImages(IMAGES, 0);
  annotations();
  await app.api.go(1);
  await app.flush();
  assert.equal(app.state().currentIndex, 1);
  await app.api.go(-1);
  await app.flush();
  assert.equal(app.state().currentIndex, 0);
  await app.api.go(-1); // already at the start
  assert.equal(app.state().currentIndex, 0);
});

test('go asks to discard unsaved changes and can be blocked', async () => {
  setImages(IMAGES, 0);
  annotations();
  app.set({ dirty: true, autoSave: false });
  app.window.confirm = () => false;
  await app.api.go(1);
  assert.equal(app.state().currentIndex, 0);
  app.window.confirm = () => true;
  await app.api.go(1);
  await app.flush();
  assert.equal(app.state().currentIndex, 1);
});

test('jumpToImage parses a 1-based number and clamps it', async () => {
  setImages(IMAGES);
  annotations();
  await app.api.jumpToImage('3');
  await app.flush();
  assert.equal(app.state().currentIndex, 2);
  await app.api.jumpToImage('99');
  await app.flush();
  assert.equal(app.state().currentIndex, 2);
});

test('rememberLastImage / readLastImage keep the image per split', () => {
  setImages(IMAGES, 1);
  app.set({ currentDataYaml: 'data.yaml' });
  app.api.rememberLastImage();
  const mem = app.api.readLastImage();
  assert.equal(mem.dataYaml, 'data.yaml');
  assert.equal(mem.bySplit.train, 'b.jpg');
  assert.deepEqual(plain(mem.last), { split: 'train', name: 'b.jpg' });
});

test('resumeLastImage restores the remembered image in the split', async () => {
  setImages(IMAGES);
  app.set({ currentDataYaml: 'data.yaml' });
  app.window.localStorage.setItem('ybe_last_image', JSON.stringify({
    dataYaml: 'data.yaml', bySplit: { train: 'c.jpg' }, last: { split: 'train', name: 'c.jpg' },
  }));
  annotations();
  await app.api.resumeLastImage({ data_yaml: 'data.yaml', active_split: null });
  await app.flush();
  assert.equal(app.state().currentIndex, 2);
});

test('resumeLastImage falls back to the first image for a new dataset', async () => {
  setImages(IMAGES);
  app.set({ currentDataYaml: 'other.yaml' });
  annotations();
  await app.api.resumeLastImage({ data_yaml: 'other.yaml', active_split: null });
  assert.equal(app.state().currentIndex, 0);
  await app.flush();
});

test('persistView / readSavedView / clearSavedView round-trip a view', () => {
  app.api.persistView({ data_yaml: 'd.yaml', active_split: 'val', active_filters: [{ name: 'f' }] });
  assert.deepEqual(plain(app.api.readSavedView()), {
    dataYaml: 'd.yaml', split: 'val', filters: [{ name: 'f' }],
  });
  app.api.clearSavedView();
  assert.equal(app.api.readSavedView(), null);
});

test('maybeRestoreView re-applies a remembered split when the server has none', async () => {
  app.api.persistView({ data_yaml: 'd.yaml', active_split: 'val', active_filters: [] });
  app.fetchMock.on('/api/split', () => ({
    body: { ok: true, data_yaml: 'd.yaml', active_split: 'val', splits: [{ name: 'val' }], filters: [], active_filters: [] },
  }));
  const cfg = { data_yaml: 'd.yaml', active_split: null, splits: [{ name: 'val' }], filters: [], active_filters: [] };
  const out = await app.api.maybeRestoreView(cfg);
  assert.equal(out.active_split, 'val');
});

test('applyImagesPayload resets the editor when the list becomes empty', async () => {
  setImages(IMAGES, 1);
  app.api.applyImagesPayload({ images: [], active_split: null }, null, 'reload');
  assert.equal(app.state().currentIndex, -1);
  assert.equal(app.state().boxes.length, 0);
  assert.equal(app.$('counter').value, '0 / 0');
  await app.flush();
});

test('applyImagesPayload keeps the current image by path when it survives', async () => {
  setImages(IMAGES, 1); // train/b.jpg
  annotations();
  const anchor = app.api.captureImageAnchor(false);
  app.api.applyImagesPayload(
    { images: [IMAGES[0], IMAGES[2]], active_split: 'train', active_filters: [] },
    { path: 'train/b.jpg', following: ['train/c.jpg'], follow: true },
    'rescan'
  );
  await app.flush();
  assert.equal(app.state().currentIndex, 1); // train/c.jpg shifted to index 1
  assert.equal(app.api.imageKey(app.state().images[1]), 'train/c.jpg');
  assert.deepEqual(plain(anchor), { path: 'train/b.jpg', following: [], follow: false });
});

test('reloadImagesList keeps the current image across a fetch', async () => {
  setImages(IMAGES, 1);
  annotations();
  app.fetchMock.on('/api/images/rescan', () => ({
    body: { ok: true, images: [IMAGES[0], IMAGES[1]], active_split: 'train', active_filters: [] },
  }));
  await app.api.reloadImagesList('/api/images/rescan', { method: 'POST' }, 'app_refresh_images_list', 'rescan');
  await app.flush();
  assert.equal(app.api.imageKey(app.state().images[app.state().currentIndex]), 'train/b.jpg');
});
