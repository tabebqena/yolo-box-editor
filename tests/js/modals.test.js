'use strict';

// The shared modal open/close/backdrop/Escape behaviour and each concrete modal.

const { test, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const { createApp, plain } = require('./helpers/app.js');

let app;
beforeEach(() => { app = createApp(); });
afterEach(() => { app.cleanup(); });

test('openModal / closeModal toggle the hidden class', () => {
  app.api.closeModal('settingsModal');
  assert.equal(app.api.isHidden('settingsModal'), true);
  app.api.openModal('settingsModal');
  assert.equal(app.api.isHidden('settingsModal'), false);
  app.api.closeModal('settingsModal');
  assert.equal(app.api.isHidden('settingsModal'), true);
});

test('clicking a modal backdrop closes it, clicking inside does not', () => {
  app.api.openSettingsModal();
  // click on the inner box (a descendant) must not close
  app.click(app.$('settingsModal').querySelector('.modal-box'));
  assert.equal(app.api.isHidden('settingsModal'), false);
  // click on the backdrop itself closes
  app.click('settingsModal');
  assert.equal(app.api.isHidden('settingsModal'), true);
});

test('ESCAPE_CLOSERS lists the overlays in priority order', () => {
  assert.deepEqual(
    plain(app.consts.ESCAPE_CLOSERS.map((entry) => entry[0])),
    ['yamlEditorModal', 'actionResult', 'changelogModal', 'tipModal',
      'loadDataModal', 'settingsModal', 'updateModal', 'notifPanel']
  );
});

test('Escape closes the highest-priority open overlay', () => {
  app.api.openSettingsModal();
  app.api.openUpdateModal();
  assert.equal(app.api.isHidden('settingsModal'), false);
  assert.equal(app.api.isHidden('updateModal'), false);
  app.keydown(app.document, { key: 'Escape' });
  assert.equal(app.api.isHidden('settingsModal'), true, 'settings wins over update');
  assert.equal(app.api.isHidden('updateModal'), false);
  app.keydown(app.document, { key: 'Escape' });
  assert.equal(app.api.isHidden('updateModal'), true);
});

test('Escape closes the notification panel last', () => {
  app.api.toggleNotifPanel(true);
  assert.equal(app.api.isHidden('notifPanel'), false);
  app.keydown(app.document, { key: 'Escape' });
  assert.equal(app.api.isHidden('notifPanel'), true);
});

test('openSettingsModal focuses the dataset input when no dataset is loaded', () => {
  app.set({ datasetLoaded: false });
  app.api.openSettingsModal();
  assert.equal(app.$('settingsModal').querySelector('.settings-tab.active').dataset.tab, 'dataset');
  assert.equal(app.document.activeElement, app.$('dataYaml'));
});

test('load-data modal opens through the auto-modal queue', async () => {
  app.api.openLoadDataModal();
  await app.flush();
  assert.equal(app.api.isHidden('loadDataModal'), false);
  app.api.closeLoadDataModal();
  assert.equal(app.api.isHidden('loadDataModal'), true);
});

test('auto modals show one at a time and release the next on close', async () => {
  const order = [];
  app.api.queueAutoModal('a', () => order.push('a'));
  app.api.queueAutoModal('b', () => order.push('b'));
  await app.flush();
  assert.deepEqual(plain(order), ['a']);
  app.api.releaseAutoModal('a');
  await app.flush();
  assert.deepEqual(plain(order), ['a', 'b']);
  // a queued id is never enqueued twice
  app.api.queueAutoModal('a', () => order.push('a2'));
  app.api.queueAutoModal('b', () => order.push('b2'));
  assert.equal(app.state().autoModalCurrent, 'b');
});

test('changelog modal shows the title and one list item per change', () => {
  app.api.showChangelog('9.9.9', ['one', 'two']);
  assert.equal(app.api.isHidden('changelogModal'), false);
  assert.match(app.$('changelogTitle').textContent, /9\.9\.9/);
  const items = app.$('changelogList').querySelectorAll('li');
  assert.equal(items.length, 2);
  assert.equal(items[1].textContent, 'two');
  app.api.closeChangelog();
  assert.equal(app.api.isHidden('changelogModal'), true);
});

test('tip modal renders the queued tip text', async () => {
  app.api.queueAutoModal('tip', () => {
    app.$('tipText').textContent = 'a tip';
    app.api.openModal('tipModal');
  });
  await app.flush();
  assert.equal(app.$('tipText').textContent, 'a tip');
  assert.equal(app.api.isHidden('tipModal'), false);
  app.api.closeTipModal();
  assert.equal(app.api.isHidden('tipModal'), true);
});

test('update modal shows availability and closes', () => {
  app.set({ updateInfo: { update_available: true, latest_version: '2.0.0', current_version: '1.0.0' } });
  app.api.openUpdateModal();
  assert.match(app.$('updateModalSummary').textContent, /2\.0\.0 is available/);
  app.api.closeUpdateModal();
  assert.equal(app.api.isHidden('updateModal'), true);
});

test('yaml editor open/close manages the current file', () => {
  app.set({ yamlEditor: { kind: 'action', name: 'x', writable: true, text: 'a: 1', source: 'user', status: 'current', api_version: 1 } });
  app.api.openModal('yamlEditorModal');
  app.api.closeYamlEditor();
  assert.equal(app.api.isHidden('yamlEditorModal'), true);
  assert.equal(app.state().yamlEditor, null);
});

test('password modal clears its fields and opens', () => {
  app.$('pwCurrent').value = 'old';
  app.$('pwNew').value = 'x';
  app.$('pwConfirm').value = 'y';
  app.api.openPasswordModal();
  assert.equal(app.api.isHidden('passwordModal'), false);
  assert.equal(app.$('pwCurrent').value, '');
  assert.equal(app.$('pwNew').value, '');
  assert.equal(app.$('pwConfirm').value, '');
  app.api.closePasswordModal();
  assert.equal(app.api.isHidden('passwordModal'), true);
});

test('class picker lists every class and closes again', () => {
  app.set({ classes: ['cat', 'dog'], selected: 0, boxes: [{ class: 0, cx: 0.5, cy: 0.5, w: 0.2, h: 0.2 }] });
  app.api.openClassPicker(10, 10);
  assert.equal(app.api.isHidden('classPicker'), false);
  assert.equal(app.$('classPicker').querySelectorAll('button').length, 2);
  app.api.closeClassPicker();
  assert.equal(app.api.isHidden('classPicker'), true);
});
