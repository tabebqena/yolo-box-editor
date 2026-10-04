'use strict';

// Box editing: undo/redo, the side panel, delete/fix and saving.

const { test, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const { createApp, plain } = require('./helpers/app.js');

let app;
beforeEach(() => { app = createApp(); });
afterEach(() => { app.cleanup(); });

function box(extra = {}) {
  return { class: 0, cx: 0.5, cy: 0.5, w: 0.2, h: 0.2, ...extra };
}
function ready(overrides = {}) {
  app.set({
    images: [{ split: 'train', name: 'a.jpg' }],
    currentIndex: 0,
    classes: ['cat', 'dog'],
    datasetLoaded: true,
    boxes: [box()],
    imageTags: [],
    ...overrides,
  });
}

test('snapshot deep-copies boxes and tags', () => {
  ready({ imageTags: ['fire'] });
  const snap = app.api.snapshot();
  assert.deepEqual(plain(snap.boxes), [box()]);
  assert.deepEqual(plain(snap.tags), ['fire']);
  snap.boxes[0].cx = 0.9;
  assert.equal(app.state().boxes[0].cx, 0.5);
});

test('pushUndo clears redo and caps the stack at 100', () => {
  ready();
  for (let i = 0; i < 105; i++) app.api.pushUndo();
  assert.equal(app.state().undoStack.length, 100);
  assert.equal(app.state().redoStack.length, 0);
});

test('updateHistoryButtons reflects undo/redo/dirty state', () => {
  ready({ undoStack: [], redoStack: [], dirty: false });
  app.api.updateHistoryButtons();
  assert.equal(app.$('undoBtn').disabled, true);
  assert.equal(app.$('redoBtn').disabled, true);
  assert.equal(app.$('saveBtn').disabled, true);
  app.set({ dirty: true });
  app.api.updateHistoryButtons();
  assert.equal(app.$('saveBtn').disabled, false);
});

test('undo and redo move snapshots between the stacks', () => {
  ready({ boxes: [box()] });
  app.api.pushUndo();
  app.set({ boxes: [box(), box({ cx: 0.3 })] });
  app.api.undo();
  assert.equal(app.state().boxes.length, 1);
  assert.equal(app.state().redoStack.length, 1);
  app.api.redo();
  assert.equal(app.state().boxes.length, 2);
  assert.equal(app.state().undoStack.length, 1);
});

test('undo / redo are no-ops with empty stacks or in read-only mode', () => {
  ready({ boxes: [box()], undoStack: [], redoStack: [] });
  app.api.undo();
  app.api.redo();
  assert.equal(app.state().boxes.length, 1);
  app.set({ undoStack: [{ boxes: [box(), box()], tags: [] }], readonly: true });
  app.api.undo();
  assert.equal(app.state().boxes.length, 1);
});

test('deleteSelected removes the selected box and clears selection', () => {
  ready({ boxes: [box(), box()], selected: 0 });
  app.api.deleteSelected();
  assert.equal(app.state().boxes.length, 1);
  assert.equal(app.state().selected, -1);
  assert.equal(app.state().dirty, true);
});

test('toggleFixSelected flips the transient fixed flag', () => {
  ready({ selected: 0 });
  app.api.toggleFixSelected();
  assert.equal(app.state().boxes[0].fixed, true);
  app.api.toggleFixSelected();
  assert.equal(app.state().boxes[0].fixed, false);
});

test('syncClassSelect updates lastSelected even without a class select element', () => {
  ready();
  app.api.syncClassSelect(0);
  assert.equal(app.state().lastSelected, 0);
});

test('renderSidePanel builds a row per box and updateSidePanelState syncs it', () => {
  ready({ boxes: [box(), box({ class: 1, cx: 0.25 })] });
  app.api.renderSidePanel();
  const rows = app.$('boxList').querySelectorAll('.box-row');
  assert.equal(rows.length, 2);
  assert.equal(app.$('sidePanelCount').textContent, '2');
  assert.equal(rows[1].querySelector('.box-row-class').value, '1');
  assert.equal(rows[1].querySelector('.box-row-cx').value, '0.25');

  app.set({ selected: 1 });
  app.api.updateSidePanelState();
  assert.equal(rows[0].querySelector('.box-row-class').disabled, true);
  assert.equal(rows[1].querySelector('.box-row-class').disabled, false);
  assert.equal(rows[1].classList.contains('selected'), true);
});

test('changing a row class edits the box and pushes an undo step', () => {
  ready({ selected: 0 });
  app.api.renderSidePanel();
  app.change(app.$('boxList').querySelector('.box-row-class'), '1');
  assert.equal(app.state().boxes[0].class, 1);
  assert.equal(app.state().dirty, true);
  assert.equal(app.state().undoStack.length, 1);
});

test('editing a row point coordinate updates the box', () => {
  ready({ selected: 0 });
  app.api.renderSidePanel();
  const cx = app.$('boxList').querySelector('.box-row-cx');
  cx.value = '0.25';
  cx.dispatchEvent(new app.window.Event('input', { bubbles: true }));
  assert.equal(app.state().boxes[0].cx, 0.25);
  assert.equal(app.state().dirty, true);
});

test('the row delete button removes the box', () => {
  ready({ selected: 0, boxes: [box(), box()] });
  app.api.renderSidePanel();
  app.click(app.$('boxList').querySelector('.box-row-del'));
  assert.equal(app.state().boxes.length, 1);
  assert.equal(app.state().selected, -1);
});

test('the row fix button toggles the fixed flag', () => {
  ready({ selected: 0 });
  app.api.renderSidePanel();
  app.click(app.$('boxList').querySelector('.box-row-fix'));
  assert.equal(app.state().boxes[0].fixed, true);
});

test('selectFromPanel selects a box and updates the class select', () => {
  ready({ boxes: [box(), box()] });
  app.api.selectFromPanel(1);
  assert.equal(app.state().selected, 1);
  assert.equal(app.state().lastSelected, 1);
});

test('markDirty schedules an auto-save only when auto-save is on', () => {
  ready({ autoSave: false });
  app.api.markDirty();
  assert.equal(app.state().dirty, true);
  assert.equal(app.state().autoSaveTimer, null);
  app.set({ dirty: false, autoSave: true });
  app.api.scheduleAutoSave();
  assert.notEqual(app.state().autoSaveTimer, null);
});

test('flushAutoSave writes pending edits and clears the timer', async () => {
  ready({ autoSave: true, dirty: true });
  app.fetchMock.on('/api/annotations?key=train%2Fa.jpg', () => ({
    body: { ok: true, count: 1, tags_count: 0, available_tags: ['fire'] },
  }));
  const ok = await app.api.flushAutoSave();
  assert.equal(ok, true);
  assert.equal(app.state().dirty, false);
  assert.equal(app.state().autoSaveTimer, null);
  assert.deepEqual(plain(app.state().availableTags), ['fire']);
});

test('save posts the boxes and tags and clears dirty', async () => {
  ready({ boxes: [box()], imageTags: ['fire'] });
  let posted = null;
  app.fetchMock.onPrefix('/api/annotations', (url, method, entry) => {
    posted = JSON.parse(entry.body);
    return { body: { ok: true, count: 1, tags_count: 1, available_tags: [] } };
  });
  const ok = await app.api.save();
  assert.equal(ok, true);
  assert.equal(posted.boxes.length, 1);
  assert.deepEqual(posted.tags, ['fire']);
  assert.equal(app.state().dirty, false);
});

test('save reports failure and keeps the image dirty', async () => {
  ready({ dirty: true });
  app.fetchMock.onPrefix('/api/annotations', () => ({ status: 500, ok: false, body: { error: 'nope' } }));
  const ok = await app.api.save();
  assert.equal(ok, false);
  assert.equal(app.state().dirty, true);
});

test('runAppAction dispatches the built-in action handlers', async () => {
  ready({ boxes: [box(), box(), box()], selected: -1, lastSelected: 0, boxesVisible: true });
  app.api.runAppAction('app_sel_box', { preventDefault() {} });
  assert.equal(app.state().selected, 0);
  app.api.runAppAction('app_sel_box', { preventDefault() {} });
  assert.equal(app.state().selected, 1);

  app.set({ selected: 0 });
  app.api.runAppAction('app_fix_box', { preventDefault() {} });
  assert.equal(app.state().boxes[0].fixed, true);

  const before = app.state().boxesVisible;
  app.api.runAppAction('app_show_hide', { preventDefault() {} });
  assert.equal(app.state().boxesVisible, !before);

  app.set({ selected: 0 });
  app.api.runAppAction('app_del', { preventDefault() {} });
  assert.equal(app.state().boxes.length, 2);
});

test('app_box_details toggles the details flag', () => {
  ready({ boxDetailsVisible: true });
  app.api.runAppAction('app_box_details', { preventDefault() {} });
  assert.equal(app.state().boxDetailsVisible, false);
  app.api.runAppAction('app_box_details', { preventDefault() {} });
  assert.equal(app.state().boxDetailsVisible, true);
});

test('app_box_details hides the corner buttons and handles from hit-testing', () => {
  ready({ imgW: 100, imgH: 100, boxes: [box()], selected: -1, boxDetailsVisible: true });
  assert.equal(app.api.hitTest({ x: 42, y: 42 }).type, 'class');
  app.set({ selected: 0 });
  assert.equal(app.api.hitTest({ x: 40, y: 40 }).type, 'handle');
  app.set({ boxDetailsVisible: false });
  assert.equal(app.api.hitTest({ x: 42, y: 42 }).type, 'box');
  assert.equal(app.api.hitTest({ x: 40, y: 40 }).type, 'box');
});

test('runAppAction rejects an unknown action name', async () => {
  await assert.rejects(() => app.api.runAppAction('app_nope', {}), /unknown app action/);
});

test('app_select_next_box / app_select_prev_box wrap the selection', () => {
  ready({ boxes: [box(), box(), box()], selected: -1, lastSelected: 0, boxesVisible: true });
  app.api.runAppAction('app_select_next_box', { preventDefault() {} });
  assert.equal(app.state().selected, 0);
  app.api.runAppAction('app_select_next_box', { preventDefault() {} });
  assert.equal(app.state().selected, 1);
  app.api.runAppAction('app_select_prev_box', { preventDefault() {} });
  assert.equal(app.state().selected, 0);
  app.api.runAppAction('app_select_prev_box', { preventDefault() {} });
  assert.equal(app.state().selected, 2);
});

test('app_clear_tags removes every tag and marks the image dirty', () => {
  ready({ imageTags: ['fire', 'smoke'], dirty: false });
  app.api.runAppAction('app_clear_tags', { preventDefault() {} });
  assert.deepEqual(plain(app.state().imageTags), []);
  assert.equal(app.state().dirty, true);
});

test('app_clear_tags / app_copy_labels_from_prev do nothing in read-only mode', async () => {
  ready({ readonly: true, imageTags: ['fire'], images: [{ split: 'train', name: 'a.jpg' }] });
  app.api.runAppAction('app_clear_tags', { preventDefault() {} });
  assert.deepEqual(plain(app.state().imageTags), ['fire']);
  await app.api.runAppAction('app_copy_labels_from_prev', { preventDefault() {} });
  assert.equal(app.state().dirty, false);
});

test('app_copy_labels_from_prev copies boxes and tags from the previous image', async () => {
  ready({
    images: [{ split: 'train', name: 'a.jpg' }, { split: 'train', name: 'b.jpg' }],
    currentIndex: 1,
    boxes: [],
    imageTags: ['mine'],
  });
  app.fetchMock.on('/api/annotations?key=train%2Fa.jpg', () => ({
    body: { boxes: [box({ cx: 0.3 })], tags: ['fire'] },
  }));
  await app.api.runAppAction('app_copy_labels_from_prev', { preventDefault() {} });
  assert.equal(app.state().boxes.length, 1);
  assert.equal(app.state().boxes[0].cx, 0.3);
  assert.deepEqual(plain(app.state().imageTags), ['fire']);
  assert.equal(app.state().dirty, true);
});

test('dispatchAppShortcut runs a bound app action', () => {
  ready({ appShortcuts: { app_show_hide: { shortcut: 'H', label: 'Show/hide' } }, boxesVisible: true });
  const handled = app.api.dispatchAppShortcut({
    code: 'KeyH', key: 'h', ctrlKey: false, altKey: false, shiftKey: false, metaKey: false,
    preventDefault() {},
  });
  assert.equal(handled, true);
  assert.equal(app.state().boxesVisible, false);
});

test('dispatchAppShortcut runs app_box_details on comma', () => {
  ready({ appShortcuts: { app_box_details: { shortcut: ',', label: 'Box details' } }, boxDetailsVisible: true });
  const handled = app.api.dispatchAppShortcut({
    code: 'Comma', key: ',', ctrlKey: false, altKey: false, shiftKey: false, metaKey: false,
    preventDefault() {},
  });
  assert.equal(handled, true);
  assert.equal(app.state().boxDetailsVisible, false);
});
