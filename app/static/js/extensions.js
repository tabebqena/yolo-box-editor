// app/static/js/extensions.js — action/hook/filter builder and YAML editor
'use strict';

// ------------------------------------------------------------------------- //
// extension builder (Settings > Actions / Hooks / Filters)
//
// Writes user YAML through the server, so the form removes the need to hand-
// write indentation; every command row gets a click-to-insert placeholder
// palette. A file whose api_version is older than the UI is opened in a raw
// YAML editor instead (see openYamlEditor), which preserves comments.
// ------------------------------------------------------------------------- //
const EXT_TYPE_LABELS = {
  cmd: 'Shell command',
  app: 'App action',
  backend: 'Server action',
  action: 'Other action',
};

function extRefNames() {
  return {
    app: appActions,
    backend: backendActions,
    action: (actionDefs || []).filter((d) => d.enabled !== false).map((d) => d.name),
  };
}

function extTextField(label, hint) {
  const row = mk('label', 'ext-field');
  row.appendChild(mk('span', 'ext-field-label', label));
  const input = mk('input', 'ext-field-input');
  input.type = 'text';
  input.placeholder = hint || '';
  row.appendChild(input);
  return { row, input };
}

function extCheckbox(label, checked) {
  const wrap = mk('label', 'ext-check');
  const input = mk('input');
  input.type = 'checkbox';
  input.checked = !!checked;
  wrap.append(input, document.createTextNode(label));
  return { row: wrap, input };
}

function makeCommandPalette(builder) {
  const root = mk('div', 'ext-palette');
  root.appendChild(mk('span', 'ext-palette-label', 'Insert placeholder:'));
  const btns = mk('div', 'ext-palette-btns');
  root.appendChild(btns);
  root.refresh = () => {
    btns.innerHTML = '';
    const list = builder.getPlaceholders(builder) || [];
    if (!list.length) {
      btns.appendChild(mk('span', 'hint', 'no placeholders'));
      return;
    }
    list.forEach((p) => {
      const b = mk('button', 'ext-palette-btn', p.token);
      b.type = 'button';
      b.title = p.description || p.token;
      b.addEventListener('click', () => extInsertToken(builder, p.token));
      btns.appendChild(b);
    });
  };
  root.refresh();
  return root;
}

function extInsertToken(builder, token) {
  let input = builder.lastCmdInput;
  if (!input || !input.isConnected) input = builder.root.querySelector('.ext-cmd-input');
  if (!input) {
    toast('Add a command step first', { type: 'warning' });
    return;
  }
  const start = input.selectionStart == null ? input.value.length : input.selectionStart;
  const end = input.selectionEnd == null ? input.value.length : input.selectionEnd;
  input.value = input.value.slice(0, start) + token + input.value.slice(end);
  const pos = start + token.length;
  input.focus();
  input.setSelectionRange(pos, pos);
  builder.lastCmdInput = input;
}

function makeEntryList(builder, opts) {
  const root = mk('div', 'ext-list');
  const rows = mk('div', 'ext-rows');
  root.appendChild(rows);
  const add = mk('button', 'ext-add', opts.addLabel || '+ Add');
  add.type = 'button';
  root.appendChild(add);

  const addRow = (entry) => {
    const row = mk('div', 'ext-entry');
    const type = mk('select', 'ext-type');
    (opts.allowRefs ? ['cmd', 'app', 'backend', 'action'] : ['cmd'])
      .forEach((t) => type.appendChild(option(t, EXT_TYPE_LABELS[t])));
    row.appendChild(type);
    const valueBox = mk('div', 'ext-value');
    row.appendChild(valueBox);
    const remove = mk('button', 'ext-remove', '\u00d7');
    remove.type = 'button';
    remove.title = 'Remove';
    remove.addEventListener('click', () => row.remove());
    row.appendChild(remove);

    const renderValue = () => {
      valueBox.innerHTML = '';
      const t = type.value;
      if (t === 'cmd') {
        const input = mk('input', 'ext-cmd-input');
        input.type = 'text';
        input.placeholder = opts.placeholder || 'shell command…';
        if (entry && entry.type === 'cmd') input.value = entry.value;
        input.addEventListener('focus', () => { builder.lastCmdInput = input; });
        valueBox.appendChild(input);
      } else {
        const names = extRefNames()[t] || [];
        if (!names.length) {
          valueBox.appendChild(mk('span', 'hint', 'none available'));
          return;
        }
        const sel = mk('select', 'ext-ref-select');
        names.forEach((n) => sel.appendChild(option(n, n)));
        if (entry && entry.type === t) sel.value = entry.value;
        valueBox.appendChild(sel);
      }
    };
    type.addEventListener('change', () => { entry = null; renderValue(); });
    if (entry && opts.allowRefs) type.value = entry.type;
    renderValue();
    rows.appendChild(row);
  };

  add.addEventListener('click', () => addRow(null));
  root.addRow = addRow;
  root.entries = () => {
    const out = [];
    rows.querySelectorAll('.ext-entry').forEach((row) => {
      const t = row.querySelector('.ext-type').value;
      if (t === 'cmd') {
        const v = row.querySelector('.ext-cmd-input').value.trim();
        if (v) out.push(v);
      } else {
        const sel = row.querySelector('.ext-ref-select');
        if (sel && sel.value) out.push(t === 'action' ? 'action_' + sel.value : sel.value);
      }
    });
    return out;
  };
  return root;
}

function makeArgList(builder) {
  const root = mk('div', 'ext-args');
  const rows = mk('div', 'ext-arg-rows');
  root.appendChild(rows);
  const add = mk('button', 'ext-add', '+ Add argument');
  add.type = 'button';
  root.appendChild(add);

  const refresh = () => { if (builder.palette) builder.palette.refresh(); };
  const addArg = (arg) => {
    const row = mk('div', 'ext-arg');
    const name = mk('input', 'ext-arg-name');
    name.type = 'text';
    name.placeholder = 'name';
    if (arg) name.value = arg.name || '';
    const req = mk('label', 'ext-arg-req');
    const cb = mk('input', 'ext-arg-required');
    cb.type = 'checkbox';
    if (arg && arg.required) cb.checked = true;
    req.append(cb, document.createTextNode('required'));
    const def = mk('input', 'ext-arg-default');
    def.type = 'text';
    def.placeholder = 'default';
    if (arg && arg.default != null) def.value = arg.default;
    const opt = mk('input', 'ext-arg-options');
    opt.type = 'text';
    opt.placeholder = 'options (comma-separated)';
    if (arg && Array.isArray(arg.options)) opt.value = arg.options.join(', ');
    [name, def, opt].forEach((i) => i.addEventListener('input', refresh));
    const rm = mk('button', 'ext-remove', '\u00d7');
    rm.type = 'button';
    rm.title = 'Remove';
    rm.addEventListener('click', () => { row.remove(); refresh(); });
    row.append(name, req, def, opt, rm);
    rows.appendChild(row);
  };
  add.addEventListener('click', () => { addArg(null); refresh(); });
  root.addArg = addArg;
  root.args = () => {
    const out = [];
    rows.querySelectorAll('.ext-arg').forEach((row) => {
      const n = row.querySelector('.ext-arg-name').value.trim();
      if (!n) return;
      const raw = row.querySelector('.ext-arg-options').value.trim();
      out.push({
        name: n,
        required: row.querySelector('.ext-arg-required').checked,
        default: row.querySelector('.ext-arg-default').value,
        options: raw ? raw.split(',').map((s) => s.trim()).filter(Boolean) : [],
      });
    });
    return out;
  };
  return root;
}

function versionBadge(def) {
  if (def.status === 'newer') return mk('span', 'ext-badge ext-badge-newer', 'newer than app');
  if (def.status === 'current') return mk('span', 'ext-badge ext-badge-current', 'v' + (def.api_version || extensionApiVersion));
  return mk('span', 'ext-badge ext-badge-outdated', def.api_version ? ('outdated v' + def.api_version) : 'outdated');
}

function renderDefList(kind, defs) {
  const wrap = mk('div', 'ext-defs');
  wrap.appendChild(mk('div', 'settings-group-title', 'Existing'));
  if (!defs || !defs.length) {
    wrap.appendChild(mk('p', 'hint', 'None yet.'));
    return wrap;
  }
  const canToggle = (kind === 'action' || kind === 'hook') && datasetLoaded;
  defs.forEach((def) => {
    const enabled = def.enabled !== false;
    const row = mk('div', 'ext-def' + (canToggle && !enabled ? ' ext-def-disabled' : ''));
    const main = mk('div', 'ext-def-main');
    main.appendChild(mk('span', 'ext-def-name', def.name));
    if (def.event) main.appendChild(mk('span', 'ext-def-sub', def.event));
    main.appendChild(mk('span', 'ext-badge ext-badge-' + def.source, def.source));
    main.appendChild(versionBadge(def));
    row.appendChild(main);

    const actions = mk('div', 'ext-def-actions');
    if (canToggle) {
      const toggle = extCheckbox('Enabled for this dataset', enabled);
      toggle.input.addEventListener('change',
        () => setExtensionDisabled(kind, def.name, !toggle.input.checked));
      actions.appendChild(toggle.row);
    }
    if (def.status !== 'newer' && (def.status === 'outdated' || def.source === 'user')) {
      const open = mk('button', 'ext-open', 'YAML');
      open.type = 'button';
      open.title = 'Open in the YAML editor';
      open.addEventListener('click', () => openYamlEditor(kind, def.name));
      actions.appendChild(open);
    }
    if (def.source === 'user') {
      const del = mk('button', 'ext-delete', 'Delete');
      del.type = 'button';
      del.addEventListener('click', () => deleteExtension(kind, def.name));
      actions.appendChild(del);
    }
    row.appendChild(actions);
    wrap.appendChild(row);
  });
  return wrap;
}

function extFormButtons(label, onSave, onClear) {
  const bar = mk('div', 'settings-actions ext-form-actions');
  const save = mk('button', 'primary', label);
  save.type = 'button';
  save.disabled = readonly;
  if (readonly) save.title = 'Read-only mode';
  save.addEventListener('click', onSave);
  const clear = mk('button', null, 'Clear');
  clear.type = 'button';
  clear.addEventListener('click', onClear);
  bar.append(save, clear);
  return bar;
}

function newBuilder(kind, root, getPlaceholders) {
  return { kind, root, lastCmdInput: null, getPlaceholders, palette: null };
}

function applyExtensionConfig(cfg) {
  appActions = cfg.app_actions || [];
  backendActions = cfg.backend_actions || [];
  hookEvents = cfg.hook_events || [];
  extensionApiVersion = cfg.extension_api_version || 1;
  placeholders = cfg.placeholders || { action: [], filter: [] };
  actionDefs = cfg.action_defs || [];
  hookDefs = cfg.hook_defs || [];
  filterDefs = cfg.filter_defs || [];
  renderActionBuilder();
  renderHookBuilder();
  renderFilterBuilder();
}

// The create forms are laid out as a small editor: a titled header, grouped
// sections and a footer action bar. `extEditor` returns the pieces so each
// builder can drop fields into `body` and buttons into `foot`.
function extEditor(title, badge) {
  const editor = mk('div', 'ext-editor');
  const head = mk('div', 'ext-editor-head');
  head.appendChild(mk('span', 'ext-editor-dot'));
  head.appendChild(mk('span', 'ext-editor-title', title));
  if (badge) head.appendChild(mk('span', 'ext-editor-badge', badge));
  editor.appendChild(head);
  const body = mk('div', 'ext-editor-body');
  editor.appendChild(body);
  const foot = mk('div', 'ext-editor-foot');
  editor.appendChild(foot);
  return { editor, body, foot };
}

function extSection(title, hint) {
  const sec = mk('div', 'ext-section');
  const head = mk('div', 'ext-section-head');
  head.appendChild(mk('span', 'ext-section-title', title));
  if (hint) head.appendChild(mk('span', 'ext-section-hint', hint));
  sec.appendChild(head);
  const body = mk('div', 'ext-section-body');
  sec.appendChild(body);
  return { sec, body };
}

// The three create forms (Settings > Actions / Hooks / Filters) differ only in
// a few fields and options; each is described by a spec and built by the shared
// renderExtensionBuilder below.
const EXTENSION_SPECS = {
  action: {
    kind: 'action',
    rootId: 'actionBuilder',
    defsRootId: 'actionDefs',
    title: 'New action',
    badge: 'action.yaml',
    saveLabel: 'Create action',
    getPlaceholders: () => placeholders.action || [],
    details: {
      hint: 'the button label is the name',
      fields: [{ type: 'text', key: 'name', label: 'Name', hint: 'e.g. Remove box' }],
    },
    steps: { allowRefs: true, addLabel: '+ Add step',
      hint: 'run in order · stop on the first failure' },
    afterSuccess: { allowRefs: true, addLabel: '+ Add after-success',
      hint: 'optional · runs after all steps' },
    defs: () => actionDefs,
    save: (b) => saveActionForm(b),
  },
  hook: {
    kind: 'hook',
    rootId: 'hookBuilder',
    defsRootId: 'hookDefs',
    title: 'New hook',
    badge: 'on_<event>.yaml',
    saveLabel: 'Create hook',
    getPlaceholders: () => placeholders.action || [],
    details: {
      hint: 'when the hook fires',
      fields: [
        { type: 'select', key: 'event', label: 'Event',
          options: () => hookEvents.map((e) => ({ value: e, text: 'on_' + e })) },
        { type: 'checkbox', key: 'active',
          label: 'Active (uncheck to disable without deleting)', checked: true },
      ],
    },
    steps: { allowRefs: true, addLabel: '+ Add step' },
    afterSuccess: { allowRefs: true, addLabel: '+ Add after-success', hint: 'optional' },
    defs: () => hookDefs,
    save: (b, f) => saveHookForm(b, f.event, f.active),
  },
  filter: {
    kind: 'filter',
    rootId: 'filterBuilder',
    defsRootId: 'filterDefs',
    title: 'New filter',
    badge: 'filter.yaml',
    saveLabel: 'Create filter',
    getPlaceholders: (b) => {
      const list = (placeholders.filter || []).slice();
      (b.args ? b.args.args() : []).forEach((a) => {
        const token = '{' + a.name.toUpperCase() + '}';
        if (!list.some((p) => p.token === token)) {
          list.push({ token, description: 'argument ' + a.name });
        }
      });
      return list;
    },
    details: {
      hint: 'name shown in the Filters tab',
      fields: [
        { type: 'text', key: 'name', label: 'Name', hint: 'e.g. Keep every N-th' },
        { type: 'text', key: 'description', label: 'Description', hint: 'shown in the Filters tab' },
        { type: 'checkbox', key: 'active', label: 'Active', checked: true },
      ],
    },
    args: true,
    steps: { allowRefs: false, addLabel: '+ Add step',
      placeholder: 'shell command using {INPUT_PIPE} / {OUTPUT_PIPE}…',
      hint: 'read {INPUT_PIPE}, write {OUTPUT_PIPE}' },
    defs: () => filterDefs,
    save: (b, f) => saveFilterForm(b, f.description, f.active),
  },
};

function extFieldFor(field) {
  if (field.type === 'select') {
    const row = mk('label', 'ext-field');
    row.appendChild(mk('span', 'ext-field-label', field.label));
    const select = mk('select', 'ext-field-input');
    (field.options ? field.options() : []).forEach((o) => select.appendChild(option(o.value, o.text)));
    row.appendChild(select);
    return { row, input: select };
  }
  if (field.type === 'checkbox') return extCheckbox(field.label, field.checked);
  return extTextField(field.label, field.hint);
}

function renderExtensionBuilder(spec) {
  const root = el(spec.rootId);
  if (!root) return;
  root.innerHTML = '';
  const ed = extEditor(spec.title, spec.badge);
  root.appendChild(ed.editor);
  const b = newBuilder(spec.kind, ed.body, spec.getPlaceholders);

  const details = extSection('Details', spec.details.hint);
  const fields = {};
  spec.details.fields.forEach((f) => {
    const field = extFieldFor(f);
    details.body.appendChild(field.row);
    fields[f.key] = field.input;
  });
  if (fields.name) b.nameInput = fields.name;
  ed.body.appendChild(details.sec);

  if (spec.args) {
    const args = extSection('Arguments', 'optional · become {NAME} placeholders');
    b.args = makeArgList(b);
    args.body.appendChild(b.args);
    ed.body.appendChild(args.sec);
  }

  const steps = extSection('Steps', spec.steps.hint);
  b.steps = makeEntryList(b, {
    allowRefs: spec.steps.allowRefs,
    addLabel: spec.steps.addLabel,
    placeholder: spec.steps.placeholder,
  });
  steps.body.appendChild(b.steps);
  b.steps.addRow(null);
  ed.body.appendChild(steps.sec);

  if (spec.afterSuccess) {
    const after = extSection('After success', spec.afterSuccess.hint);
    b.after = makeEntryList(b, {
      allowRefs: spec.afterSuccess.allowRefs,
      addLabel: spec.afterSuccess.addLabel,
    });
    after.body.appendChild(b.after);
    ed.body.appendChild(after.sec);
  }

  b.palette = makeCommandPalette(b);
  ed.body.appendChild(b.palette);
  ed.foot.appendChild(extFormButtons(
    spec.saveLabel, () => spec.save(b, fields), () => renderExtensionBuilder(spec)));

  const defsRoot = el(spec.defsRootId);
  if (defsRoot) {
    defsRoot.innerHTML = '';
    defsRoot.appendChild(renderDefList(spec.kind, spec.defs()));
  }
}

// Kept as named entry points: the Settings tabs and other modules call these.
function renderActionBuilder() { renderExtensionBuilder(EXTENSION_SPECS.action); }
function renderHookBuilder() { renderExtensionBuilder(EXTENSION_SPECS.hook); }
function renderFilterBuilder() { renderExtensionBuilder(EXTENSION_SPECS.filter); }

async function postExtension(url, body) {
  let { res, data } = await apiPost(url, body);
  if (res.status === 409) {
    if (!confirm((data.error || 'It already exists') + '. Overwrite it?')) return null;
    body.overwrite = true;
    ({ res, data } = await apiPost(url, body));
  }
  if (!data.ok) {
    toast(data.error || 'Could not save', { type: 'error' });
    return null;
  }
  return data;
}

async function saveActionForm(b) {
  const name = b.nameInput.value.trim();
  if (!name) { toast('Give the action a name', { type: 'warning' }); return; }
  const data = await postExtension('/api/actions/save', {
    name, steps: b.steps.entries(), after_success: b.after.entries(),
  });
  if (!data) return;
  toast(`Action "${name}" saved`, { type: 'success' });
  applyExtensionConfig(data);
}

async function saveHookForm(b, ev, active) {
  const event = ev.value;
  const data = await postExtension('/api/hooks/save', {
    event, active: active.checked, steps: b.steps.entries(), after_success: b.after.entries(),
  });
  if (!data) return;
  toast(`Hook on_${event} saved`, { type: 'success' });
  applyExtensionConfig(data);
}

async function saveFilterForm(b, desc, active) {
  const name = b.nameInput.value.trim();
  if (!name) { toast('Give the filter a name', { type: 'warning' }); return; }
  const data = await postExtension('/api/filters/save', {
    name, description: desc.value.trim(), active: active.checked,
    arguments: b.args.args(), steps: b.steps.entries(),
  });
  if (!data) return;
  toast(`Filter "${name}" saved`, { type: 'success' });
  applyExtensionConfig(data);
}

async function deleteExtension(kind, name) {
  if (readonly) { toast('Read-only mode', { type: 'warning' }); return; }
  if (!confirm(`Delete "${name}"? This removes your file.`)) return;
  const data = await postJson('/api/extensions/delete', { kind, name });
  if (!data.ok) { toast(data.error || 'Could not delete', { type: 'error' }); return; }
  toast(`Deleted "${name}"`, { type: 'success' });
  applyExtensionConfig(data);
}

// Disable/enable one action or hook for the loaded dataset only (no file edit).
async function setExtensionDisabled(kind, name, disabled) {
  const data = await postJson('/api/extensions/disabled', { kind, name, disabled });
  if (!data.ok) {
    toast(data.error || 'Could not update', { type: 'error' });
    if (kind === 'action') renderActionBuilder(); else renderHookBuilder();
    return;
  }
  applyExtensionConfig(data);
  hooksByName = new Set(data.hooks || []);
  populateActions(data.actions || []);
  toast(`"${name}" ${disabled ? 'disabled' : 'enabled'} for this dataset`,
    { type: 'success' });
}

async function openYamlEditor(kind, name) {
  let data;
  try {
    data = await apiGet(
      `/api/extensions/file?kind=${encodeURIComponent(kind)}&name=${encodeURIComponent(name)}`);
  } catch (e) {
    toast('Could not open the file', { type: 'error' });
    return;
  }
  if (!data.ok) { toast(data.error || 'Could not open the file', { type: 'error' }); return; }
  yamlEditor = data;
  el('yamlEditorTitle').textContent = `Edit ${name}`;
  el('yamlEditorMeta').textContent =
    `${data.source} file · ${data.status}`
    + (data.api_version ? ` (api_version ${data.api_version})` : '')
    + ` · saving bumps to v${extensionApiVersion}`;
  const textarea = el('yamlEditorText');
  textarea.value = data.text;
  const err = el('yamlEditorError');
  err.textContent = '';
  err.classList.add('hidden');
  const save = el('yamlEditorSave');
  save.disabled = !data.writable;
  save.title = data.writable ? '' : 'Shipped files are read-only here';
  openModal('yamlEditorModal');
  textarea.focus();
}

function closeYamlEditor() {
  closeModal('yamlEditorModal');
  yamlEditor = null;
}

async function saveYamlEditor() {
  if (!yamlEditor || !yamlEditor.writable) return;
  const btn = el('yamlEditorSave');
  btn.disabled = true;
  const err = el('yamlEditorError');
  let data;
  try {
    ({ data } = await apiPost('/api/extensions/file', {
      kind: yamlEditor.kind,
      name: yamlEditor.name,
      text: el('yamlEditorText').value,
      overwrite: true,
    }));
  } catch (e) {
    data = { ok: false, error: 'Network error' };
  }
  btn.disabled = false;
  if (!data.ok) {
    err.textContent = data.error || 'Could not save';
    err.classList.remove('hidden');
    return;
  }
  err.textContent = '';
  err.classList.add('hidden');
  yamlEditor = data;
  el('yamlEditorText').value = data.text;
  el('yamlEditorMeta').textContent =
    `${data.source} file · current (api_version ${data.api_version})`;
  toast('Saved', { type: 'success' });
  await refreshExtensions();
}

async function refreshExtensions() {
  try {
    const cfg = await apiGet('/api/config');
    applyExtensionConfig(cfg);
  } catch (e) { /* the next config load will pick it up */ }
}
