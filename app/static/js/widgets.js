// app/static/js/widgets.js — user-defined custom widgets (Layout tab + dock)
'use strict';

// ------------------------------------------------------------------------- //
// custom widgets
//
// A widget is one YAML file (widgets/*.yaml) with a list of controls. Buttons
// run an action (by name) or inline steps; select/checkbox/input are state only,
// passed to the button's action as {WIDGET_<ID>} placeholders. Each widget docks
// or floats like the built-in ones (see appearance.js); here we build its
// controls and its Layout-tab Section, then register it.
// ------------------------------------------------------------------------- //
// Widget keys currently registered (so a config reload can clear them first).
let customWidgetNames = [];

/**
 * Turn a widget name into a DOM-id-safe slug.
 * @param {string} name - Widget name.
 * @returns {string} The slug.
 */
function widgetSlug(name) {
  return String(name).replace(/[^A-Za-z0-9_-]+/g, '_');
}

/**
 * Build the control markup for one widget and attach a `collect()` helper.
 * @param {object} def - The widget definition from /api/config.
 * @returns {HTMLElement} The widget body content.
 */
function buildWidgetContent(def, runner) {
  const root = mk('div', 'widget-content');
  (def.controls || []).forEach((ctrl, i) => {
    if (ctrl.type === 'button') {
      const b = mk('button', 'widget-button', ctrl.label || 'Run');
      b.type = 'button';
      b.title = ctrl.action ? `Run action "${ctrl.action}"` : 'Run this widget step';
      b.addEventListener('click', () => runner(i, root));
      root.appendChild(b);
    } else if (ctrl.type === 'select') {
      const row = mk('label', 'widget-field');
      row.appendChild(mk('span', 'widget-label', ctrl.label || ctrl.id));
      const sel = mk('select', 'widget-input');
      (ctrl.options || []).forEach((o) => sel.appendChild(option(o, o)));
      sel.value = ctrl.default;
      sel.dataset.controlId = ctrl.id;
      row.appendChild(sel);
      root.appendChild(row);
    } else if (ctrl.type === 'checkbox') {
      const row = mk('label', 'widget-field widget-check');
      const cb = mk('input', 'widget-input');
      cb.type = 'checkbox';
      cb.checked = !!ctrl.default;
      cb.dataset.controlId = ctrl.id;
      row.append(cb, document.createTextNode(ctrl.label || ctrl.id));
      root.appendChild(row);
    } else { // input
      const row = mk('label', 'widget-field');
      row.appendChild(mk('span', 'widget-label', ctrl.label || ctrl.id));
      const inp = mk('input', 'widget-input');
      inp.type = 'text';
      inp.placeholder = ctrl.placeholder || '';
      inp.value = ctrl.default || '';
      inp.dataset.controlId = ctrl.id;
      row.appendChild(inp);
      root.appendChild(row);
    }
  });
  root.collect = () => {
    const values = {};
    qsa('[data-control-id]', root).forEach((node) => {
      const id = node.dataset.controlId;
      if (node.type === 'checkbox') values[id] = node.checked ? '1' : '0';
      else values[id] = node.value;
    });
    return values;
  };
  return root;
}

/**
 * Drive a widget/package button through the backend action chain, running any
 * paused client (`app_*`) actions in between.
 * @param {string} url - `/api/widgets/run` or `/api/extensions/run`.
 * @param {object} body - Request body (without `target`).
 * @param {string} label - Button label for prompts/toasts.
 * @returns {Promise<void>}
 */
async function driveWidgetRun(url, body, label) {
  if (currentIndex < 0 || !images[currentIndex]) {
    toast('Open an image first', { type: 'warning' });
    return;
  }
  const target = `${images[currentIndex].split}/${images[currentIndex].name}`;
  if (!confirm(`Run "${label}" on ${target}?`)) return;
  setActionButtonsDisabled(true);
  try {
    let data = await postJson(url, Object.assign({ target }, body));
    // The chain pauses at each client (app_*) action: run it, then resume.
    while (data.ok && data.client_action) {
      let result;
      try {
        await runAppAction(data.client_action);
        result = { ok: true };
      } catch (err) {
        result = { ok: false, error: err.message };
      }
      data = await postJson('/api/actions/run', { uid: data.uid, result });
    }
    if (!data.ok) {
      toast(`"${label}" failed: ${data.error || 'see console'}`, { type: 'error' });
      return;
    }
    toast(`"${label}" done`, { type: 'success' });
  } catch (err) {
    toast(`"${label}" failed: ${err.message}`, { type: 'error' });
  } finally {
    setActionButtonsDisabled(readonly);
  }
}

/**
 * Run one widget button on the current image.
 * @param {string} widgetName - The widget's name.
 * @param {number} controlIndex - The button's index in `controls`.
 * @param {HTMLElement} root - The widget content holding the control values.
 * @returns {Promise<void>}
 */
async function runWidgetControl(widgetName, controlIndex, root) {
  const def = (widgetDefs || []).find((w) => w.name === widgetName);
  if (!def) return;
  const control = (def.controls || [])[controlIndex] || {};
  await driveWidgetRun('/api/widgets/run', {
    widget: widgetName,
    control: controlIndex,
    values: root && root.collect ? root.collect() : {},
  }, control.label || widgetName);
}

/**
 * Run one button of an extension package's `settings:` block.
 * @param {string} packageId - The package id.
 * @param {number} controlIndex - The button's index in the settings controls.
 * @param {HTMLElement} root - The settings content holding the control values.
 * @returns {Promise<void>}
 */
async function runPackageControl(packageId, controlIndex, root) {
  const pkg = (extensionPackages || []).find((p) => p.id === packageId);
  if (!pkg || !pkg.settings) return;
  const control = (pkg.settings.controls || [])[controlIndex] || {};
  await driveWidgetRun('/api/extensions/run', {
    package: packageId,
    control: controlIndex,
    values: root && root.collect ? root.collect() : {},
  }, control.label || pkg.name);
}

/**
 * Build the Layout-tab settings block for one custom widget (Show + Location).
 * @param {object} def - The widget definition.
 * @param {HTMLElement} container - The container to append to.
 * @returns {{select: HTMLElement, checkbox: HTMLElement}} The built controls.
 */
function buildWidgetSetting(def, container) {
  const slug = widgetSlug(def.name);
  const box = mk('div', 'widget-setting');
  const head = mk('div', 'widget-setting-head');
  head.appendChild(mk('span', 'settings-group-title', def.title || def.name));
  const toggle = mk('label', 'widget-toggle');
  toggle.title = 'Show or hide this widget';
  const cb = mk('input');
  cb.type = 'checkbox';
  cb.id = 'widgetVis_' + slug;
  toggle.append(cb, mk('span', null, 'Show'));
  head.appendChild(toggle);
  box.appendChild(head);

  const row = mk('label', 'settings-row');
  row.setAttribute('for', 'widgetDock_' + slug);
  row.appendChild(mk('span', 'widget-field-label', 'Location'));
  const sel = mk('select');
  sel.id = 'widgetDock_' + slug;
  [['float', 'Floating window'], ['left', 'Left panel'],
    ['right', 'Right panel'], ['bottom', 'Bottom panel']].forEach(([v, t]) => {
    sel.appendChild(option(v, t));
  });
  row.appendChild(sel);
  box.appendChild(row);
  container.appendChild(box);
  return { select: sel, checkbox: cb };
}

/**
 * Rebuild the custom widgets and their Layout-tab settings from `widgetDefs`.
 * @returns {void}
 */
function renderCustomWidgets() {
  const root = el('customWidgetSettings');
  if (!root) return;
  customWidgetNames.forEach(unregisterWidget);
  customWidgetNames = [];
  root.innerHTML = '';
  (widgetDefs || []).forEach((def) => {
    if (!def || def.status === 'newer') return; // too new to render safely
    const content = buildWidgetContent(def, (i, root) => runWidgetControl(def.name, i, root));
    const frame = createWidgetFrame(def.name, def.title || def.name);
    frame.body.appendChild(content);
    const controls = buildWidgetSetting(def, root);
    frame.hide.addEventListener('click', () => setWidgetVisible(def.name, false));

    registerWidget(def.name, {
      frame: frame.frame, body: frame.body, content,
      select: controls.select.id, visibleSw: controls.checkbox.id,
    });
    const saved = getDock(def.name);
    controls.select.value = saved;
    controls.select.addEventListener('change',
      () => setWidgetDock(def.name, controls.select.value));
    controls.checkbox.checked = getWidgetVisible(def.name);
    controls.checkbox.addEventListener('change',
      () => setWidgetVisible(def.name, controls.checkbox.checked));
    customWidgetNames.push(def.name);
  });
}
