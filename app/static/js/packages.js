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
  panel.appendChild(head);
  if (pkg.description) panel.appendChild(mk('p', 'hint', pkg.description));
  if (pkg.author) panel.appendChild(mk('p', 'hint', 'by ' + pkg.author));

  panel.appendChild(buildPackageParts(pkg));
  if (pkg.settings && (pkg.settings.controls || []).length) {
    panel.appendChild(buildPackageSettings(pkg));
  }
  return panel;
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
