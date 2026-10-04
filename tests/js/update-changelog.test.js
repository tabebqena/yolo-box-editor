'use strict';

// Update check, daily update notice, changelog and tip-of-the-day.

const { test, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const { createApp } = require('./helpers/app.js');

let app;
beforeEach(() => { app = createApp(); });
afterEach(() => { app.cleanup(); });

test('renderUpdateStatus covers checking, available, current and unknown', () => {
  app.set({ updateInfo: null });
  app.api.renderUpdateStatus();
  assert.equal(app.$('updateStatus').textContent, 'Checking…');
  assert.equal(app.$('updateHowBtn').classList.contains('hidden'), true);

  app.set({ updateInfo: { update_available: true, latest_version: '2.0.0', current_version: '1.0.0' } });
  app.api.renderUpdateStatus();
  assert.match(app.$('updateStatus').textContent, /Update available: 2\.0\.0 \(you have 1\.0\.0\)/);
  assert.equal(app.$('updateHowBtn').classList.contains('hidden'), false);

  app.set({ updateInfo: { update_available: false, latest_version: '1.0.0', current_version: '1.0.0' } });
  app.api.renderUpdateStatus();
  assert.match(app.$('updateStatus').textContent, /Up to date \(1\.0\.0\)/);

  app.set({ updateInfo: { update_available: false, latest_version: null, current_version: '1.0.0' } });
  app.api.renderUpdateStatus();
  assert.match(app.$('updateStatus').textContent, /latest unknown/);
});

test('refreshUpdateInfo stores the result and re-renders', async () => {
  app.fetchMock.on('/api/update-check', () => ({
    body: { update: { update_available: false, latest_version: '1.0.0', current_version: '1.0.0' } },
  }));
  await app.api.refreshUpdateInfo();
  await app.flush();
  assert.equal(app.state().updateInfo.latest_version, '1.0.0');
  assert.match(app.$('updateStatus').textContent, /Up to date/);
});

test('notifyUpdateDaily logs the notice only once per version and day', () => {
  app.set({ updateInfo: { update_available: true, latest_version: '9.9.9', current_version: '1.0.0' } });
  app.api.notifyUpdateDaily();
  assert.equal(app.state().notifLog.length, 1);
  app.api.notifyUpdateDaily();
  assert.equal(app.state().notifLog.length, 1);
});

test('notifyUpdateDaily does nothing when up to date', () => {
  app.set({ updateInfo: { update_available: false } });
  app.api.notifyUpdateDaily();
  assert.equal(app.state().notifLog.length, 0);
});

test('notifyChangelog shows the notes once per version', async () => {
  app.api.notifyChangelog({ version: '1.2.3', changelog: ['first', 'second'] });
  await app.flush();
  assert.equal(app.api.isHidden('changelogModal'), false);
  assert.match(app.$('changelogTitle').textContent, /1\.2\.3/);
  app.api.closeChangelog();

  app.api.notifyChangelog({ version: '1.2.3', changelog: ['first', 'second'] });
  await app.flush();
  assert.equal(app.api.isHidden('changelogModal'), true);
});

test('maybeShowTip shows one tip a day and remembers it', async () => {
  app.api.maybeShowTip(['tip one', 'tip two']);
  await app.flush();
  assert.equal(app.api.isHidden('tipModal'), false);
  assert.notEqual(app.$('tipText').textContent, '');
  assert.notEqual(app.api.settingsGet('ybe_tip_last'), null);
  app.api.closeTipModal();

  // a second call on the same day is a no-op
  app.api.maybeShowTip(['tip one', 'tip two']);
  await app.flush();
  assert.equal(app.api.isHidden('tipModal'), true);
});

test('maybeShowTip respects the tips switch', async () => {
  app.api.settingsSet('ybe_tips_enabled', '0');
  app.api.maybeShowTip(['tip']);
  await app.flush();
  assert.equal(app.api.isHidden('tipModal'), true);
});
