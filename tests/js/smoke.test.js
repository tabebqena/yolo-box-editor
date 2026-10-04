'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createApp } = require('./helpers/app.js');

test('harness boots app.js and exposes helpers', async (t) => {
  const app = createApp();
  t.after(() => app.cleanup());

  assert.equal(typeof app.api.toast, 'function');
  assert.equal(typeof app.api.mk, 'function');
  assert.equal(app.state().images.length, 0);

  // mk() builds an element.
  const btn = app.api.mk('button', 'primary', 'Save');
  assert.equal(btn.tagName, 'BUTTON');
  assert.equal(btn.className, 'primary');
  assert.equal(btn.textContent, 'Save');

  // option() builds an <option>.
  const opt = app.api.option('a', 'A');
  assert.equal(opt.tagName, 'OPTION');
  assert.equal(opt.value, 'a');
  assert.equal(opt.textContent, 'A');

  // toast() renders into #toasts.
  app.api.toast('hello', { type: 'success', timeout: 100000 });
  assert.equal(app.$('toasts').children.length, 1);
  assert.match(app.$('toasts').textContent, /hello/);
});
