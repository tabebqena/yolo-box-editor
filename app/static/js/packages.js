// app/static/js/packages.js — Settings > Extensions (package subtabs)
'use strict';

// ------------------------------------------------------------------------- //
// extension packages
//
// An extension package is a folder (extensions/<id>/) with an extension.yaml
// manifest that groups actions, hooks, filters and widgets. This is an additive
// view over the existing extensions: the Actions/Hooks/Filters tabs still edit
// loose files exactly as before, and here each package gets a subtab listing its
// parts plus an optional declarative settings form (the manifest's `settings:`).
// ------------------------------------------------------------------------- //
// Human-readable labels for the package part kinds.
const PACKAGE_PART_LABELS = {
  action: 'Actions',
  hook: 'Hooks',
  filter: 'Filters',
  widget: 'Widgets',
};
// Panel loads in flight, so a config refresh does not fetch the same script twice.
const panelLoading = {};

/**
 * Build the parts list (one row per extension file) for a package subtab.
 * @param {object} pkg - The package definition from /api/config.
 * @returns {HTMLElement}
 */
function buildPackageParts(pkg) {
  const wrap = mk('div', 'package-parts');
  const kinds = Object.keys(PACKAGE_PART_LABELS).filter((k) => (pkg.parts || {})[k]);
  if (!kinds.length) {
    wrap.appendChild(mk('p', 'hint', 'This package ships no extension files yet.'));
    return wrap;
  }
  kinds.forEach((kind) => {
    const sec = mk('div', 'package-part');
    sec.appendChild(mk('div', 'settings-group-title', PACKAGE_PART_LABELS[kind]));
    pkg.parts[kind].forEach((fname) => {
      const name = fname.replace(/\.yaml$/, '');
      const row = mk('div', 'package-part-row');
      row.appendChild(mk('span', 'ext-def-name', name));
      const actions = mk('div', 'ext-def-actions');
      const open = mk('button', 'ext-open', 'YAML');
      open.type = 'button';
      open.title = 'Open in the YAML editor';
      open.addEventListener('click', () => openYamlEditor(kind, name));
      actions.appendChild(open);
      row.appendChild(actions);
      sec.appendChild(row);
    });
    wrap.appendChild(sec);
  });
  return wrap;
}

/**
 * Build the declarative settings form for a package (the manifest `settings:`).
 * @param {object} pkg - The package definition.
 * @returns {HTMLElement}
 */
function buildPackageSettings(pkg) {
  const sec = mk('div', 'package-settings');
  const title = (pkg.settings && pkg.settings.title) || 'Settings';
  sec.appendChild(mk('div', 'settings-group-title', title));
  const content = buildWidgetContent(
    pkg.settings || { controls: [] },
    (i, root) => runPackageControl(pkg.id, i, root));
  sec.appendChild(content);
  return sec;
}

/**
 * Build one package's subtab panel.
 * @param {object} pkg - The package definition.
 * @returns {HTMLElement}
 */
function buildPackagePanel(pkg) {
  const panel = mk('div', 'package-panel');
  const head = mk('div', 'package-head');
  head.appendChild(mk('span', 'package-name', pkg.name));
  head.appendChild(mk('span', 'ext-badge ext-badge-' + pkg.source, pkg.source));
  if (pkg.version) head.appendChild(mk('span', 'ext-badge', 'v' + pkg.version));
  head.appendChild(versionBadge(pkg));
  if (!pkg.active) head.appendChild(mk('span', 'ext-badge ext-badge-outdated', 'disabled'));

  const toggle = mk('label', 'package-active');
  const cb = mk('input');
  cb.type = 'checkbox';
  cb.checked = !!pkg.active;
  cb.title = 'Enable or disable this package';
  cb.addEventListener('change', () => setPackageActive(pkg, cb));
  toggle.append(cb, mk('span', null, 'Enabled'));
  head.appendChild(toggle);
  panel.appendChild(head);
  if (pkg.description) panel.appendChild(mk('p', 'hint', pkg.description));
  if (pkg.author) panel.appendChild(mk('p', 'hint', 'by ' + pkg.author));

  panel.appendChild(buildPackageParts(pkg));
  if (pkg.ui) {
    const note = pkg.ui.status === 'newer'
      ? ' (newer than the app — not loaded)'
      : (pkg.active ? '' : ' (package disabled)');
    panel.appendChild(mk('p', 'hint', 'UI panel: ' + (pkg.ui.title || pkg.id) + note));
  }
  panel.appendChild(buildPackagePermissions(pkg));
  if (pkg.settings && (pkg.settings.controls || []).length) {
    panel.appendChild(buildPackageSettings(pkg));
  }
  return panel;
}

/**
 * Build the permissions section: what the package declares, plus any artifact
 * it ships without declaring (the honesty check).
 * @param {object} pkg - The package definition.
 * @returns {HTMLElement}
 */
function buildPackagePermissions(pkg) {
  const sec = mk('div', 'package-permissions');
  const errors = pkg.permission_errors || [];
  if (errors.length) {
    sec.appendChild(mk('div', 'settings-group-title', 'Permission issues'));
    errors.forEach((msg) => sec.appendChild(mk('p', 'hint', '\u26a0 ' + msg)));
  }
  sec.appendChild(mk('div', 'settings-group-title', 'Permissions'));
  if (!pkg.permissions) {
    sec.appendChild(mk('p', 'hint',
      'No permissions.yaml — this package does not declare what it uses.'));
    return sec;
  }
  const list = mk('ul', 'permission-list');
  (pkg.permission_lines || []).forEach((line) => list.appendChild(mk('li', null, line)));
  sec.appendChild(list);
  if ((pkg.permission_unknown || []).length) {
    sec.appendChild(mk('p', 'hint',
      'Unknown permissions (not understood by this app): ' + pkg.permission_unknown.join(', ')));
  }
  return sec;
}

/**
 * Persist a package's enabled/disabled override and apply it live (the server
 * loads/unloads the backend; this refreshes the tab and the mounted panels).
 * @param {object} pkg - The package definition.
 * @param {HTMLInputElement} cb - The checkbox that changed.
 * @returns {Promise<void>}
 */
async function setPackageActive(pkg, cb) {
  const want = cb.checked;
  try {
    const { res, data } = await apiPost('/api/extensions/active',
      { package: pkg.id, active: want });
    if (!res.ok || data.ok === false) throw new Error(data.error || 'request failed');
    pkg.active = want;
    toast((want ? 'Enabled ' : 'Disabled ') + pkg.name, { type: 'success' });
    await refreshExtensions();
  } catch (e) {
    cb.checked = !want;
    dbgWarn('package toggle failed', e);
    toast('Could not change "' + pkg.name + '": ' + e.message, { type: 'error' });
  }
}

/**
 * Re-read the package list and re-render the Extensions tab and mounted panels,
 * so an enable/disable takes effect without reloading the page.
 * @returns {Promise<void>}
 */
async function refreshExtensions() {
  try {
    const cfg = await apiGet('/api/config');
    // Mirror loadConfig's extension-related parts so a package's actions, hooks,
    // filters, widgets, panels and shortcuts all appear/disappear live too.
    filters = cfg.filters || [];
    hooksByName = new Set(cfg.hooks || []);
    applyExtensionConfig(cfg);
    populateFilterPanel();
    populateActions(cfg.actions || []);
    renderShortcuts();
  } catch (e) {
    dbgWarn('refresh extensions failed', e);
  }
}

/**
 * Render the Settings > Extensions tab: one subtab per package.
 * @returns {void}
 */
function renderExtensionsTab() {
  const root = el('extensionTabBody');
  if (!root) return;
  root.innerHTML = '';
  const pkgs = extensionPackages || [];
  if (!pkgs.length) {
    root.appendChild(mk('p', 'hint',
      'No extension packages found. Add a folder with an extension.yaml under your extensions/ folder.'));
    return;
  }
  const tabs = mk('div', 'sub-tabs');
  tabs.setAttribute('role', 'tablist');
  const bodies = mk('div');
  pkgs.forEach((pkg, i) => {
    const tab = mk('button', 'sub-tab' + (i === 0 ? ' active' : ''), pkg.name);
    tab.type = 'button';
    tab.dataset.sub = pkg.id;
    tab.setAttribute('role', 'tab');
    tab.addEventListener('click', () => selectSubTab(pkg.id, root));
    tabs.appendChild(tab);

    const panel = mk('div', 'sub-panel' + (i === 0 ? ' active' : ''));
    panel.dataset.sub = pkg.id;
    panel.appendChild(buildPackagePanel(pkg));
    bodies.appendChild(panel);
  });
  root.append(tabs, bodies);
}

// ------------------------------------------------------------------------- //
// sandboxed UI panels (see js/plugin_api.js)
//
// The host fetches each active package's panel script and mounts it in an
// opaque-origin iframe. Mounted panels are kept across config refreshes; only a
// package that disappeared, went inactive, or lost its `ui:` is torn down.
// ------------------------------------------------------------------------- //
/**
 * Reconcile the mounted sandboxed panels with the current packages.
 * @returns {void}
 */
function renderExtensionPanels() {
  const wanted = {};
  (extensionPackages || []).forEach((pkg) => {
    if (!pkg.active || !pkg.ui || pkg.ui.status === 'newer') return;
    wanted['panel.' + pkg.id] = pkg;
  });
  Object.keys(PANELS).forEach((name) => {
    if (!wanted[name]) {
      unmountExtensionPanel(name);
      delete panelLoading[name];
    }
  });
  Object.keys(wanted).forEach((name) => {
    if (PANELS[name] || panelLoading[name]) return;
    loadExtensionPanel(wanted[name]);
  });
}

/**
 * Fetch one package's panel script and mount it.
 * @param {object} pkg - The package definition.
 * @returns {Promise<void>}
 */
async function loadExtensionPanel(pkg) {
  const name = 'panel.' + pkg.id;
  panelLoading[name] = true;
  try {
    const res = await fetch('/api/extensions/script?package=' + encodeURIComponent(pkg.id));
    const text = await res.text();
    if (!res.ok) throw new Error(text || ('HTTP ' + res.status));
    mountExtensionPanel(pkg, text);
  } catch (e) {
    dbgWarn('panel load failed', e);
    toast('Panel "' + (pkg.name || pkg.id) + '" failed to load', { type: 'error' });
  } finally {
    delete panelLoading[name];
  }
}
