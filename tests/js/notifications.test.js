'use strict';

// Toasts and the notification bell.

const { test, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const { createApp } = require('./helpers/app.js');

let app;
beforeEach(() => { app = createApp(); });
afterEach(() => { app.cleanup(); });

test('toast renders a dismissible node with the right type class', () => {
  const { node, dismiss } = app.api.toast('hello', { type: 'success', timeout: 100000 });
  const container = app.$('toasts');
  assert.equal(container.children.length, 1);
  assert.equal(node.className, 'toast toast-success');
  assert.match(node.querySelector('.toast-message').textContent, /hello/);
  dismiss();
  assert.equal(container.children.length, 0);
});

test('toast ignores empty messages', () => {
  assert.ok(!app.api.toast(''));
  assert.ok(!app.api.toast(null));
  assert.equal(app.$('toasts').children.length, 0);
});

test('toast shows an action button that runs its handler and dismisses', () => {
  let acted = 0;
  const { node } = app.api.toast('update', {
    type: 'info',
    sticky: true,
    action: { label: 'How', onClick: () => { acted += 1; } },
  });
  const action = node.querySelector('.toast-action');
  assert.equal(action.textContent, 'How');
  action.dispatchEvent(new app.window.MouseEvent('click', { bubbles: true }));
  assert.equal(acted, 1);
  assert.equal(app.$('toasts').children.length, 0);
});

test('toast keeps at most five on screen', () => {
  for (let i = 0; i < 7; i++) app.api.toast('m' + i, { type: 'info', timeout: 100000 });
  assert.equal(app.$('toasts').children.length, 5);
});

test('errors and warnings are recorded in the bell history; info is not', () => {
  app.api.toast('boom', { type: 'error' });
  assert.equal(app.state().notifLog.length, 1);
  assert.equal(app.state().notifUnread, 1);
  app.api.toast('careful', { type: 'warning' });
  assert.equal(app.state().notifLog.length, 2);
  app.api.toast('fyi', { type: 'info' });
  assert.equal(app.state().notifLog.length, 2);
  app.api.toast('fyi kept', { type: 'info', log: true });
  assert.equal(app.state().notifLog.length, 3);
});

test('repeated identical errors are not duplicated in the log', () => {
  app.api.toast('same', { type: 'error' });
  app.api.toast('same', { type: 'error' });
  assert.equal(app.state().notifLog.length, 1);
  assert.equal(app.state().notifUnread, 2);
});

test('updateNotifBadge shows a capped count and hides at zero', () => {
  app.set({ notifUnread: 0 });
  app.api.updateNotifBadge();
  assert.equal(app.$('notifBadge').classList.contains('hidden'), true);
  app.set({ notifUnread: 7 });
  app.api.updateNotifBadge();
  assert.equal(app.$('notifBadge').textContent, '7');
  assert.equal(app.$('notifBadge').classList.contains('hidden'), false);
  app.set({ notifUnread: 150 });
  app.api.updateNotifBadge();
  assert.equal(app.$('notifBadge').textContent, '99+');
});

test('renderNotifPanel shows an empty state and then the log', () => {
  app.set({ notifLog: [] });
  app.api.renderNotifPanel();
  assert.equal(app.$('notifList').querySelector('.notif-empty').textContent, 'No notifications.');

  app.set({ notifLog: [{ type: 'error', msg: 'bad', at: 1 }, { type: 'info', msg: 'ok', at: 2 }] });
  app.api.renderNotifPanel();
  const rows = app.$('notifList').querySelectorAll('.notif-item');
  assert.equal(rows.length, 2);
  assert.match(rows[0].className, /notif-item-error/);
  assert.equal(rows[0].querySelector('.notif-item-type').textContent, 'error');
  assert.match(rows[0].textContent, /bad/);
  assert.match(rows[1].className, /notif-item-info/);
});

test('toggleNotifPanel opens, clears unread and updates aria', () => {
  app.set({ notifUnread: 3, notifLog: [{ type: 'error', msg: 'x', at: 1 }] });
  app.$('notifPanel').classList.add('hidden');
  app.api.toggleNotifPanel();
  assert.equal(app.$('notifPanel').classList.contains('hidden'), false);
  assert.equal(app.$('notifBtn').getAttribute('aria-expanded'), 'true');
  assert.equal(app.state().notifUnread, 0);
  app.api.toggleNotifPanel();
  assert.equal(app.$('notifPanel').classList.contains('hidden'), true);
  assert.equal(app.$('notifBtn').getAttribute('aria-expanded'), 'false');
});

test('the notifClear button empties the log and badge', () => {
  app.api.toast('a', { type: 'error' });
  app.click('notifClear');
  assert.equal(app.state().notifLog.length, 0);
  assert.equal(app.state().notifUnread, 0);
  assert.equal(app.$('notifBadge').classList.contains('hidden'), true);
});
