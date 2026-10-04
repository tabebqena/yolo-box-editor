'use strict';

// Login, logout, the Account settings tab and password changes.

const { test, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const { createApp } = require('./helpers/app.js');

let app;
beforeEach(() => { app = createApp(); });
afterEach(() => { app.cleanup(); });

const CONFIG = {
  version: 'test', settings: {}, images: [], splits: [], classes: [], tags: [],
  actions: [], hooks: [], shortcuts: {}, action_shortcuts: {},
  shortcut_errors: [], filter_errors: [], hook_errors: [],
  action_defs: [], hook_defs: [], filter_defs: [], placeholders: {},
};

function mockStartup() {
  app.fetchMock.on('/api/config', () => ({ body: CONFIG }));
  app.fetchMock.on('/api/update-check', () => ({ body: { update: null } }));
  app.fetchMock.on('/api/presence', () => ({ body: { count: 1 } }));
}

test('setAccountControls shows the Account tab and its buttons', () => {
  app.api.setAccountControls(true);
  assert.equal(app.api.isHidden('accountTabBtn'), false);
  assert.equal(app.api.isHidden('logoutBtn'), false);
  assert.equal(app.api.isHidden('changePwBtn'), false);
  app.api.setAccountControls(false);
  assert.equal(app.api.isHidden('accountTabBtn'), true);
  assert.equal(app.api.isHidden('logoutBtn'), true);
  assert.equal(app.api.isHidden('changePwBtn'), true);
});

test('showLogin reveals the overlay, hides account controls and shows the message', () => {
  app.api.setAccountControls(true);
  app.api.showLogin('Nope');
  assert.equal(app.api.isHidden('loginOverlay'), false);
  assert.equal(app.$('loginError').textContent, 'Nope');
  assert.equal(app.api.isHidden('loginError'), false);
  assert.equal(app.api.isHidden('accountTabBtn'), true);
  assert.equal(app.document.activeElement, app.$('loginUser'));
});

test('hideLogin clears the overlay and the password', () => {
  app.api.showLogin();
  app.$('loginPass').value = 'secret';
  app.api.hideLogin();
  assert.equal(app.api.isHidden('loginOverlay'), true);
  assert.equal(app.$('loginPass').value, '');
});

test('submitLogin signs in and starts the app', async () => {
  mockStartup();
  app.fetchMock.on('/api/login', () => ({ body: { ok: true } }));
  app.$('loginUser').value = 'admin';
  app.$('loginPass').value = 'admin';
  await app.api.submitLogin({ preventDefault() {} });
  await app.flush();
  assert.equal(app.api.isHidden('loginOverlay'), true);
  assert.equal(app.state().appStarted, true);
  assert.equal(app.api.isHidden('accountTabBtn'), false);
});

test('submitLogin reports a bad password', async () => {
  app.fetchMock.on('/api/login', () => ({ status: 401, body: { error: 'Bad credentials' } }));
  app.$('loginPass').value = 'wrong';
  await app.api.submitLogin({ preventDefault() {} });
  assert.equal(app.api.isHidden('loginOverlay'), false);
  assert.equal(app.$('loginError').textContent, 'Bad credentials');
  assert.equal(app.$('loginPass').value, '');
});

test('a 401 response surfaces the sign-in form', async () => {
  app.fetchMock.on('/api/other', () => ({ status: 401, body: {} }));
  await app.window.fetch('/api/other');
  assert.equal(app.api.isHidden('loginOverlay'), false);
});

test('savePassword validates the new password', async () => {
  app.api.openPasswordModal();
  app.$('pwNew').value = '';
  await app.api.savePassword();
  assert.match(app.$('pwError').textContent, /must not be empty/);

  app.$('pwNew').value = 'a';
  app.$('pwConfirm').value = 'b';
  await app.api.savePassword();
  assert.match(app.$('pwError').textContent, /do not match/);
});

test('savePassword posts a valid change', async () => {
  let posted = null;
  app.fetchMock.on('/api/password', (url, method, entry) => {
    posted = JSON.parse(entry.body);
    return { body: { ok: true } };
  });
  app.api.openPasswordModal();
  app.$('pwCurrent').value = 'old';
  app.$('pwNew').value = 'newpass';
  app.$('pwConfirm').value = 'newpass';
  await app.api.savePassword();
  assert.equal(posted.current_password, 'old');
  assert.equal(posted.new_password, 'newpass');
  assert.equal(app.api.isHidden('passwordModal'), true);
});

test('savePassword shows a server error', async () => {
  app.fetchMock.on('/api/password', () => ({ status: 400, body: { error: 'Wrong current password' } }));
  app.api.openPasswordModal();
  app.$('pwCurrent').value = 'x';
  app.$('pwNew').value = 'y';
  app.$('pwConfirm').value = 'y';
  await app.api.savePassword();
  assert.equal(app.$('pwError').textContent, 'Wrong current password');
});

test('logout posts to the server', async () => {
  let called = false;
  app.fetchMock.on('/api/logout', () => { called = true; return { body: { ok: true } }; });
  try {
    Object.defineProperty(app.window.location, 'reload', { configurable: true, value: () => {} });
  } catch (e) { /* jsdom may forbid it */ }
  await app.api.logout();
  assert.equal(called, true);
});

test('boot shows login when authentication is required', async () => {
  app.fetchMock.on('/api/session', () => ({ body: { auth_required: true, authenticated: false } }));
  await app.api.boot();
  assert.equal(app.api.isHidden('loginOverlay'), false);
  assert.equal(app.state().appStarted, false);
});

test('boot starts the app when no login is needed', async () => {
  mockStartup();
  app.fetchMock.on('/api/session', () => ({ body: { auth_required: false, authenticated: true } }));
  await app.api.boot();
  await app.flush();
  assert.equal(app.state().appStarted, true);
  assert.equal(app.api.isHidden('loginOverlay'), true);
});
