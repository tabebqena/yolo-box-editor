'use strict';

// Per-image tagging and the tag bar.

const { test, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const { createApp, plain } = require('./helpers/app.js');

let app;
beforeEach(() => { app = createApp(); });
afterEach(() => { app.cleanup(); });

function ready(overrides = {}) {
  app.set({
    images: [{ split: 'train', name: 'a.jpg' }],
    currentIndex: 0,
    datasetLoaded: true,
    availableTags: ['fire', 'smoke'],
    imageTags: [],
    ...overrides,
  });
}

test('addTag appends a tag, marks dirty and pushes an undo step', () => {
  ready();
  app.api.addTag('fire');
  assert.deepEqual(plain(app.state().imageTags), ['fire']);
  assert.equal(app.state().dirty, true);
  assert.equal(app.state().undoStack.length, 1);
});

test('addTag ignores duplicates, read-only mode and no image', () => {
  ready({ imageTags: ['fire'] });
  app.api.addTag('fire');
  assert.equal(app.state().imageTags.length, 1);
  app.set({ readonly: true });
  app.api.addTag('smoke');
  assert.equal(app.state().imageTags.length, 1);
  app.set({ readonly: false, currentIndex: -1 });
  app.api.addTag('smoke');
  assert.equal(app.state().imageTags.length, 1);
});

test('removeTag drops the tag and marks dirty', () => {
  ready({ imageTags: ['fire', 'smoke'] });
  app.api.removeTag('fire');
  assert.deepEqual(plain(app.state().imageTags), ['smoke']);
  assert.equal(app.state().dirty, true);
});

test('toggleTagByNumber toggles the numbered available tag', () => {
  ready();
  app.api.toggleTagByNumber(1);
  assert.deepEqual(plain(app.state().imageTags), ['fire']);
  app.api.toggleTagByNumber(1);
  assert.deepEqual(plain(app.state().imageTags), []);
  app.api.toggleTagByNumber(9); // out of range: no-op
  assert.deepEqual(plain(app.state().imageTags), []);
});

test('toggleTagByNumber makes the tag widget visible first', () => {
  ready();
  app.api.setWidgetVisible('tags', false);
  app.api.toggleTagByNumber(2);
  assert.equal(app.api.getWidgetVisible('tags'), true);
  assert.deepEqual(plain(app.state().imageTags), ['smoke']);
});

test('openTagInput / closeTagInput show and hide the add controls', () => {
  ready();
  app.api.openTagInput();
  assert.equal(app.$('tagInput').classList.contains('hidden'), false);
  assert.equal(app.$('tagSubmitBtn').classList.contains('hidden'), false);
  assert.equal(app.document.activeElement, app.$('tagInput'));
  app.api.closeTagInput();
  assert.equal(app.$('tagInput').classList.contains('hidden'), true);
  assert.equal(app.$('tagSubmitBtn').classList.contains('hidden'), true);
});

test('addTagFromInput trims, clears and adds a new tag', () => {
  ready();
  app.$('tagInput').value = '  fire  ';
  app.api.addTagFromInput();
  assert.deepEqual(plain(app.state().imageTags), ['fire']);
  assert.equal(app.$('tagInput').value, '');
});

test('addTagFromInput ignores empty input and duplicates', () => {
  ready({ imageTags: ['fire'] });
  app.$('tagInput').value = '   ';
  app.api.addTagFromInput();
  assert.equal(app.state().imageTags.length, 1);
  app.$('tagInput').value = 'fire';
  app.api.addTagFromInput();
  assert.equal(app.state().imageTags.length, 1);
});

test('renderTagBar lists available tags plus orphan image tags', () => {
  ready({ imageTags: ['fire', 'mystery'] });
  app.api.renderTagBar();
  const badges = app.api.qsa('.tag-badge', app.$('tagBadges'));
  const names = badges.map((b) => b.textContent.replace(/^\d+/, ''));
  assert.deepEqual(plain(names), ['fire', 'smoke', 'mystery']);
  // fire is on the image, smoke is not
  assert.equal(badges[0].classList.contains('active'), true);
  assert.equal(badges[1].classList.contains('active'), false);
  // the unknown tag warns that it will be written to tags.yaml on save
  assert.match(app.$('tagWarn').textContent, /not in tags.yaml/);
});

test('renderTagBar hides itself without a dataset or image', () => {
  ready({ datasetLoaded: false });
  app.api.renderTagBar();
  assert.equal(app.$('tagBar').classList.contains('hidden'), true);
  ready({ datasetLoaded: true, currentIndex: -1 });
  app.api.renderTagBar();
  assert.equal(app.$('tagBar').classList.contains('hidden'), true);
});

test('tagBadge shows the Alt shortcut number and title', () => {
  ready();
  const b = app.api.tagBadge('fire', true, 1);
  assert.match(b.className, /active/);
  assert.equal(b.querySelector('.tag-badge-num').textContent, '1');
  assert.match(b.title, /Remove tag "fire"/);
  assert.match(b.title, /Alt\+1/);
  const inactive = app.api.tagBadge('smoke', false, 2);
  assert.match(inactive.title, /Add tag "smoke"/);
});

test('clicking a tag badge toggles the tag', () => {
  ready();
  app.api.renderTagBar();
  app.click(app.api.qsa('.tag-badge', app.$('tagBadges'))[0]);
  assert.deepEqual(plain(app.state().imageTags), ['fire']);
});
