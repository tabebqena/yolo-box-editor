'use strict';

// The filter chain, applying filters and loading datasets / splits / tag dirs.

const { test, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const { createApp, plain } = require('./helpers/app.js');

let app;
beforeEach(() => { app = createApp(); });
afterEach(() => { app.cleanup(); });

const CONFIG = {
  version: 'test', settings: {}, images: [], splits: [], classes: [], tags: [],
  filters: [], active_filters: [], actions: [], hooks: [], shortcuts: {},
  action_shortcuts: {}, shortcut_errors: [], filter_errors: [], hook_errors: [],
  action_defs: [], hook_defs: [], filter_defs: [], placeholders: {},
};

const FILTERS = [
  { name: 'keep', description: 'keep some', arguments: [{ name: 'N', default: '2' }] },
  { name: 'blur', description: 'blur images', arguments: [] },
];

test('populateFilterPanel shows an empty state when there are no filters', () => {
  app.set({ filters: [], activeFilters: [] });
  app.api.populateFilterPanel();
  assert.match(app.$('filterPanelBody').textContent, /No filters found/);
  assert.equal(app.$('filterAddBtn').disabled, true);
});

test('populateFilterPanel renders one block per active filter', () => {
  app.set({ filters: FILTERS, activeFilters: [{ name: 'keep', arguments: { N: '3' } }] });
  app.api.populateFilterPanel();
  assert.equal(app.$('filterPanelBody').querySelectorAll('.filter-chain-item').length, 1);
  assert.equal(app.$('filterPanelBody').querySelector('.filter-arg-input').value, '3');
  assert.equal(app.$('filterAddBtn').disabled, false);
});

test('an argument with options renders a dropdown', () => {
  const filters = [
    { name: 'tag', description: '', arguments: [
      { name: 'tag_name', required: true, options: ['fire', 'smoke'] },
    ] },
  ];
  app.set({ filters, activeFilters: [{ name: 'tag', arguments: { tag_name: 'smoke' } }] });
  app.api.populateFilterPanel();
  const input = app.$('filterPanelBody').querySelector('.filter-arg-input');
  assert.equal(input.tagName, 'SELECT');
  assert.equal(input.value, 'smoke');
  assert.deepEqual(plain([...input.options].map((o) => o.value)), ['fire', 'smoke']);
});

test('the chain caps at eight filters and never drops below one', () => {
  app.set({ filters: FILTERS, activeFilters: [] });
  app.api.populateFilterPanel();
  for (let i = 0; i < 20; i++) app.api.addFilterBlock();
  const blocks = app.$('filterPanelBody').querySelectorAll('.filter-chain-item');
  assert.equal(blocks.length, app.consts.FILTER_CHAIN_MAX);
  assert.equal(app.$('filterAddBtn').disabled, true);

  while (app.$('filterPanelBody').querySelectorAll('.filter-chain-item').length > 1) {
    app.api.removeFilterBlock(app.$('filterPanelBody').querySelector('.filter-chain-item'));
  }
  assert.equal(app.$('filterPanelBody').querySelectorAll('.filter-chain-item').length, 1);
  app.api.removeFilterBlock(app.$('filterPanelBody').querySelector('.filter-chain-item'));
  assert.equal(app.$('filterPanelBody').querySelectorAll('.filter-chain-item').length, 1);
});

test('selectedFilterChain ignores the empty "No filter" slot', () => {
  app.set({ filters: FILTERS, activeFilters: [] });
  app.api.populateFilterPanel();
  const selects = app.$('filterPanelBody').querySelectorAll('.filter-chain-select');
  selects[0].value = '';
  app.api.addFilterBlock();
  const second = app.$('filterPanelBody').querySelectorAll('.filter-chain-select')[1];
  second.value = 'blur';
  assert.deepEqual(plain(app.api.selectedFilterChain()), [{ name: 'blur', arguments: {} }]);
});

test('setFilterApplying toggles the busy state on the buttons', () => {
  app.api.setFilterApplying(true);
  assert.equal(app.$('filterPanelApply').classList.contains('is-loading'), true);
  assert.equal(app.$('filterPanelApply').disabled, true);
  assert.equal(app.$('filterPanelClear').disabled, true);
  app.api.setFilterApplying(false);
  assert.equal(app.$('filterPanelApply').classList.contains('is-loading'), false);
});

test('applyFilterChain posts the chain and reloads the config', async () => {
  let posted = null;
  app.fetchMock.on('/api/filter', (url, method, entry) => {
    posted = JSON.parse(entry.body);
    return { body: { ok: true, images: [], filters: FILTERS, active_filters: [{ name: 'keep' }] } };
  });
  app.fetchMock.on('/api/config', () => ({ body: CONFIG }));
  await app.api.applyFilterChain([{ name: 'keep', arguments: { N: '2' } }]);
  await app.flush();
  assert.equal(posted.filters.length, 1);
  assert.equal(app.api.isHidden('settingsModal'), true);
});

test('applyFilterChain reverts the panel on failure', async () => {
  app.set({ filters: FILTERS, activeFilters: [] });
  app.api.populateFilterPanel();
  app.fetchMock.on('/api/filter', () => ({ status: 400, body: { error: 'bad filter' } }));
  await app.api.applyFilterChain([{ name: 'keep' }]);
  await app.flush();
  assert.equal(app.$('filterPanelBody').querySelectorAll('.filter-chain-item').length, 1);
  assert.match(app.$('toasts').textContent, /bad filter/);
});

test('setSplit posts the split and reloads the config', async () => {
  let posted = null;
  app.fetchMock.on('/api/split', (url, method, entry) => {
    posted = JSON.parse(entry.body);
    return { body: { ok: true } };
  });
  app.fetchMock.on('/api/config', () => ({ body: CONFIG }));
  await app.api.setSplit('val');
  await app.flush();
  assert.equal(posted.split, 'val');
});

test('setSplit shows the spinner and blocks the controls while in flight', async () => {
  app.fetchMock.on('/api/split', () => ({ body: { ok: true } }));
  app.fetchMock.on('/api/config', () => ({ body: CONFIG }));
  const pending = app.api.setSplit('val');
  assert.equal(app.$('splitSpinner').classList.contains('hidden'), false);
  assert.equal(app.$('splitSelect').disabled, true);
  assert.equal(app.$('splitReloadBtn').disabled, true);
  await pending;
  await app.flush();
  assert.equal(app.$('splitSpinner').classList.contains('hidden'), true);
  assert.equal(app.$('splitSelect').disabled, false);
  assert.equal(app.$('splitReloadBtn').disabled, false);
});

test('setSplit reverts the select when the server rejects the split', async () => {
  app.set({ splits: [{ name: 'train' }, { name: 'val' }], activeSplit: 'train' });
  app.api.populateSplitSelect();
  app.fetchMock.on('/api/split', () => ({ status: 400, body: { ok: false, error: 'nope' } }));
  await app.api.setSplit('val');
  await app.flush();
  assert.equal(app.$('splitSelect').value, 'train');
  assert.match(app.$('toasts').textContent, /nope/);
});

test('reloadSplitImages rescans and applies the selected split payload', async () => {
  let method = null;
  app.fetchMock.on('/api/images/rescan', (url, m) => {
    method = m;
    return {
      body: {
        ok: true,
        images: [{ split: 'train', name: 'a.jpg' }],
        active_split: 'train',
        active_filters: [],
      },
    };
  });
  await app.api.reloadSplitImages();
  await app.flush();
  assert.equal(method, 'POST');
  assert.equal(app.state().images.length, 1);
  assert.equal(app.state().activeSplit, 'train');
  assert.equal(app.$('splitReloadBtn').disabled, false);
});


test('loadDataset posts the path, reloads and closes the modals', async () => {
  let posted = null;
  app.fetchMock.on('/api/data', (url, method, entry) => {
    posted = JSON.parse(entry.body);
    return { body: { ok: true } };
  });
  app.fetchMock.on('/api/config', () => ({ body: CONFIG }));
  await app.api.loadDataset('  /data/data.yaml  ');
  await app.flush();
  assert.equal(posted.data_yaml, '/data/data.yaml');
  assert.equal(app.api.isHidden('settingsModal'), true);
  assert.equal(app.api.isHidden('loadDataModal'), true);
});

test('loadDataset warns on an empty path', async () => {
  await app.api.loadDataset('   ');
  assert.match(app.$('toasts').textContent, /Enter the path/);
});
