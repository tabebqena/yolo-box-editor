'use strict';

// Extension authoring: form components, builders, save/delete/YAML editing.

const { test, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const { createApp, plain } = require('./helpers/app.js');

let app;
beforeEach(() => { app = createApp(); app.window.confirm = () => true; });
afterEach(() => { app.cleanup(); });

const CFG = {
  ok: true,
  app_actions: ['app_next'],
  backend_actions: ['backend_rescan_images'],
  hook_events: ['save'],
  extension_api_version: 2,
  placeholders: { action: [{ token: '{PIPE_PATH}', description: 'pipe' }], filter: [] },
  action_defs: [{ name: 'MyAction', enabled: true, source: 'user', status: 'current', api_version: 2 }],
  hook_defs: [],
  filter_defs: [],
};

test('applyExtensionConfig stores the catalogs and renders the builders', () => {
  app.api.applyExtensionConfig(CFG);
  const s = app.state();
  assert.deepEqual(plain(s.appActions), ['app_next']);
  assert.deepEqual(plain(s.backendActions), ['backend_rescan_images']);
  assert.deepEqual(plain(s.hookEvents), ['save']);
  assert.equal(s.extensionApiVersion, 2);
  assert.ok(app.$('actionBuilder').querySelector('.ext-editor'));
  assert.ok(app.$('hookBuilder').querySelector('.ext-editor'));
  assert.ok(app.$('filterBuilder').querySelector('.ext-editor'));
  assert.match(app.$('actionDefs').textContent, /MyAction/);
});

test('extEditor / extSection / extTextField / extCheckbox build their parts', () => {
  const ed = app.api.extEditor('New action', 'action.yaml');
  assert.match(ed.editor.className, /ext-editor/);
  assert.match(ed.editor.querySelector('.ext-editor-title').textContent, /New action/);
  assert.match(ed.editor.querySelector('.ext-editor-badge').textContent, /action\.yaml/);
  assert.ok(ed.body && ed.foot);

  const sec = app.api.extSection('Steps', 'in order');
  assert.equal(sec.sec.querySelector('.ext-section-title').textContent, 'Steps');
  assert.equal(sec.sec.querySelector('.ext-section-hint').textContent, 'in order');

  const field = app.api.extTextField('Name', 'e.g. X');
  assert.equal(field.row.querySelector('.ext-field-label').textContent, 'Name');
  assert.equal(field.input.placeholder, 'e.g. X');

  const cb = app.api.extCheckbox('Active', true);
  assert.equal(cb.input.type, 'checkbox');
  assert.equal(cb.input.checked, true);
});

test('makeEntryList collects command and reference steps', () => {
  app.set({ appActions: ['app_next'], actionDefs: [{ name: 'MyAction', enabled: true }] });
  const builder = app.api.newBuilder('action', app.document.createElement('div'), () => []);
  const list = app.api.makeEntryList(builder, { allowRefs: true, addLabel: '+ Add step' });
  list.addRow({ type: 'cmd', value: 'echo hi' });
  list.addRow(null);
  const type = list.querySelectorAll('.ext-type')[1];
  type.value = 'action';
  type.dispatchEvent(new app.window.Event('change', { bubbles: true }));
  list.querySelector('.ext-ref-select').value = 'MyAction';
  assert.deepEqual(plain(list.entries()), ['echo hi', 'action_MyAction']);
});

test('makeArgList collects filter arguments', () => {
  const args = app.api.makeArgList({ palette: null });
  args.addArg({ name: 'N', required: true, default: '2', options: ['a', 'b'] });
  assert.deepEqual(plain(args.args()), [{ name: 'N', required: true, default: '2', options: ['a', 'b'] }]);
});

test('makeCommandPalette lists placeholders and inserts a token', () => {
  const builder = app.api.newBuilder('action', app.document.createElement('div'),
    () => [{ token: '{PIPE_PATH}', description: 'pipe' }]);
  builder.lastCmdInput = null;
  const palette = app.api.makeCommandPalette(builder);
  const btn = palette.querySelector('.ext-palette-btn');
  assert.equal(btn.textContent, '{PIPE_PATH}');
  app.api.extInsertToken(builder, '{PIPE_PATH}');
  // no command input yet: warns instead of throwing
  assert.match(app.$('toasts').textContent, /Add a command step first/);
});

test('renderFilterBuilder shows argument and step fields', () => {
  app.api.applyExtensionConfig(CFG);
  assert.ok(app.$('filterBuilder').querySelector('.ext-args'));
  assert.ok(app.$('filterBuilder').querySelector('.ext-cmd-input'));
});

test('each create form wires its save button to its endpoint', async () => {
  const calls = [];
  app.fetchMock.on((u) => u.startsWith('/api/'), (url) => {
    calls.push(url);
    return { body: { ok: true, app_actions: [], backend_actions: [], hook_events: [],
      placeholders: { action: [], filter: [] }, action_defs: [], hook_defs: [], filter_defs: [] } };
  });
  app.api.applyExtensionConfig(CFG);

  const clickSave = async (rootId, nameValue) => {
    const root = app.$(rootId);
    const first = root.querySelector('.ext-field-input');
    if (nameValue !== undefined && first) first.value = nameValue;
    root.querySelector('.ext-editor-foot .primary').click();
    await app.flush();
  };

  await clickSave('actionBuilder', 'A');
  await clickSave('hookBuilder');        // first field is the event select
  await clickSave('filterBuilder', 'F');
  assert.deepEqual(calls, ['/api/actions/save', '/api/hooks/save', '/api/filters/save']);
});

test('renderDefList exposes YAML / Delete for user files', () => {
  const defs = [
    { name: 'u', source: 'user', status: 'current', api_version: 2 },
    { name: 's', source: 'shipped', status: 'current', api_version: 2 },
    { name: 'new', source: 'user', status: 'newer', api_version: 3 },
  ];
  const wrap = app.api.renderDefList('action', defs);
  const rows = wrap.querySelectorAll('.ext-def');
  assert.equal(rows.length, 3);
  assert.ok(rows[0].querySelector('.ext-open'));
  assert.ok(rows[0].querySelector('.ext-delete'));
  assert.equal(rows[1].querySelector('.ext-delete'), null); // shipped: no delete
  assert.equal(rows[2].querySelector('.ext-open'), null);   // newer: no YAML edit
});

test('buildFilterBlock renders argument inputs and selectedFilterChain reads them', () => {
  app.set({
    filters: [{ name: 'keep', description: 'd', arguments: [{ name: 'N', default: '2' }] }],
    activeFilters: [{ name: 'keep', arguments: { N: '3' } }],
  });
  const block = app.api.buildFilterBlock(0);
  assert.ok(block.querySelector('.filter-chain-select'));
  const body = app.$('filterPanelBody');
  body.appendChild(block);
  assert.deepEqual(plain(app.api.selectedFilterChain()), [{ name: 'keep', arguments: { N: '3' } }]);
  assert.equal(block.querySelector('.filter-arg-input').value, '3');
});

test('postExtension retries once with overwrite on a 409', async () => {
  let calls = 0;
  app.fetchMock.on('/api/actions/save', () => {
    calls += 1;
    return calls === 1 ? { status: 409, body: { error: 'exists' } } : { body: { ok: true, app_actions: [] } };
  });
  const data = await app.api.postExtension('/api/actions/save', { name: 'x', steps: [] });
  assert.equal(calls, 2);
  assert.equal(data.ok, true);
});

test('saveActionForm posts the form and applies the returned config', async () => {
  app.fetchMock.on('/api/actions/save', () => ({ body: CFG }));
  const builder = {
    nameInput: { value: 'Greet' },
    steps: { entries: () => ['echo hi'] },
    after: { entries: () => [] },
  };
  await app.api.saveActionForm(builder);
  assert.deepEqual(plain(app.state().appActions), ['app_next']);
});

test('saveFilterForm posts name, description and arguments', async () => {
  let posted = null;
  app.fetchMock.on('/api/filters/save', (url, method, entry) => {
    posted = JSON.parse(entry.body);
    return { body: CFG };
  });
  const builder = {
    nameInput: { value: 'KeepN' },
    args: { args: () => [{ name: 'N', required: false, default: '2', options: [] }] },
    steps: { entries: () => ['cat'] },
  };
  await app.api.saveFilterForm(builder, { value: 'keeps every N' }, { checked: true });
  assert.equal(posted.name, 'KeepN');
  assert.equal(posted.description, 'keeps every N');
  assert.equal(posted.arguments[0].name, 'N');
});

test('deleteExtension confirms then removes the file', async () => {
  let posted = null;
  app.fetchMock.on('/api/extensions/delete', (url, method, entry) => {
    posted = JSON.parse(entry.body);
    return { body: CFG };
  });
  await app.api.deleteExtension('action', 'Old');
  assert.deepEqual(plain(posted), { kind: 'action', name: 'Old' });
});

test('setExtensionDisabled posts and refreshes the hooks/actions', async () => {
  app.fetchMock.on('/api/extensions/disabled', () => ({
    body: { ok: true, hooks: ['on_save'], actions: ['app_next'], ...CFG },
  }));
  await app.api.setExtensionDisabled('action', 'A', true);
  assert.deepEqual(plain([...app.state().hooksByName]), ['on_save']);
});

test('openYamlEditor loads a file into the editor modal', async () => {
  app.fetchMock.on((u) => u.startsWith('/api/extensions/file'), () => ({
    body: {
      ok: true, kind: 'action', name: 'A', text: 'name: A', writable: true,
      source: 'user', status: 'current', api_version: 2,
    },
  }));
  await app.api.openYamlEditor('action', 'A');
  assert.equal(app.api.isHidden('yamlEditorModal'), false);
  assert.equal(app.$('yamlEditorText').value, 'name: A');
  assert.equal(app.state().yamlEditor.name, 'A');
});

test('saveYamlEditor writes the text back and refreshes extensions', async () => {
  app.set({ yamlEditor: { kind: 'action', name: 'A', writable: true } });
  app.$('yamlEditorText').value = 'name: A2';
  app.fetchMock.on('/api/extensions/file', () => ({
    body: { ok: true, kind: 'action', name: 'A', text: 'name: A2', source: 'user', status: 'current', api_version: 2 },
  }));
  app.fetchMock.on('/api/config', () => ({ body: CFG }));
  await app.api.saveYamlEditor();
  assert.equal(app.state().yamlEditor.text, 'name: A2');
});
