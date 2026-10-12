// app/static/app.js — login/account, start, boot and final wiring (entry point)
'use strict';

// ---------------------------------------------------------------------------
// login / change password
// Accounts live in the server-side user store (managed with the `ybe users`
// command); the UI does sign in, sign out and password changes.
// ---------------------------------------------------------------------------
// Guards startApp so the app is built only once after login.
let appStarted = false;

/**
 * Show the signed-in-only controls: the Settings > Account tab and its
 * Sign out / Change password buttons.
 * @param {boolean} visible
 * @returns {void}
 */
function setAccountControls(visible) {
  setHidden('accountTabBtn', !visible);
  setHidden('logoutBtn', !visible);
  setHidden('changePwBtn', !visible);
}

// ---------------------------------------------------------------------------
// roles: admins author/install/manage; restricted users may only label
// ---------------------------------------------------------------------------
// The server enforces every restriction; hiding controls here is only to keep
// the UI honest for a restricted account.
let isAdmin = true; // until /api/config says otherwise (an old payload has no auth)

/**
 * Apply the server's role info: hide the authoring/management surfaces from a
 * restricted account and show the Users tab to an admin.
 * @param {{is_admin?: boolean}} [auth] - The `auth` block of /api/config.
 * @returns {void}
 */
function applyRoleControls(auth) {
  isAdmin = !auth || auth.is_admin !== false;
  ['actions', 'hooks', 'extensions'].forEach((name) => {
    setHidden(document.querySelector('.settings-tab[data-tab="' + name + '"]'), !isAdmin);
    setHidden(document.querySelector('.settings-panel[data-panel="' + name + '"]'), !isAdmin);
  });
  const filtersPanel = document.querySelector('.settings-panel[data-panel="filters"]');
  if (filtersPanel) {
    setHidden(filtersPanel.querySelector('.sub-tab[data-sub="create"]'), !isAdmin);
    setHidden(filtersPanel.querySelector('.sub-panel[data-sub="create"]'), !isAdmin);
  }
  setHidden('adminTabBtn', !isAdmin);
  setHidden('datasetsTabBtn', !isAdmin);
  // A restricted account never sees the raw path/recents; it uses the picker.
  ['dataYaml', 'setDataBtn', 'recentSelect', 'dataYamlLabel'].forEach((id) => {
    setHidden(id, !isAdmin);
  });
  if (isAdmin) {
    loadAdminUsers();
    loadAdminPolicy();
  }
}

/**
 * Fetch and render the account list (admin Users tab).
 * @returns {Promise<void>}
 */
async function loadAdminUsers() {
  const data = await apiGetOrNull('/api/admin/users');
  if (data && data.ok) renderAdminUsers(data.users);
}

/**
 * Render the account rows: name, a role picker and a Remove button.
 * @param {Array<{name: string, role: string}>} users
 * @returns {void}
 */
function renderAdminUsers(users) {
  const root = el('adminUserList');
  if (!root) return;
  root.textContent = '';
  (users || []).forEach((user) => {
    const row = mk('div', 'admin-user-row');
    row.appendChild(mk('span', 'admin-user-name', user.name));
    const role = document.createElement('select');
    role.className = 'admin-user-role';
    ['user', 'admin'].forEach((name) => {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      if (user.role === name) opt.selected = true;
      role.appendChild(opt);
    });
    role.addEventListener('change', () => setAdminRole(user.name, role.value));
    row.appendChild(role);
    const remove = mk('button', 'danger', 'Remove');
    remove.type = 'button';
    remove.addEventListener('click', () => removeAdminUser(user.name));
    row.appendChild(remove);
    root.appendChild(row);
  });
}

/**
 * Create an account from the Users tab form.
 * @returns {Promise<void>}
 */
async function adminAddUser() {
  const name = el('adminNewName').value.trim();
  const password = el('adminNewPass').value;
  const role = el('adminNewRole').value;
  if (!name || !password) {
    toast('Username and password are required');
    return;
  }
  const { res, data } = await apiPost('/api/admin/users', { name, password, role });
  if (res.ok) {
    el('adminNewName').value = '';
    el('adminNewPass').value = '';
    renderAdminUsers(data.users);
    toast('Account added');
  } else {
    toast((data && data.error) || 'Could not add the account');
  }
}

/**
 * Change an account's role.
 * @param {string} name
 * @param {string} role
 * @returns {Promise<void>}
 */
async function setAdminRole(name, role) {
  const { res, data } = await apiPost('/api/admin/users', { name, role });
  if (res.ok) {
    renderAdminUsers(data.users);
  } else {
    toast((data && data.error) || 'Could not change the role');
    loadAdminUsers();
  }
}

/**
 * Remove an account after a confirmation.
 * @param {string} name
 * @returns {Promise<void>}
 */
async function removeAdminUser(name) {
  if (!confirm('Remove account "' + name + '"?')) return;
  const { res, data } = await apiPost(
    '/api/admin/users', { name }, { method: 'DELETE' });
  if (res.ok) {
    renderAdminUsers(data.users);
    toast('Account removed');
  } else {
    toast((data && data.error) || 'Could not remove the account');
  }
}

// ---------------------------------------------------------------------------
// admin Datasets tab and the restricted-user dataset picker
// ---------------------------------------------------------------------------

/**
 * Fetch and render the admin policy (designated datasets + size cap).
 * @returns {Promise<void>}
 */
async function loadAdminPolicy() {
  const data = await apiGetOrNull('/api/admin/policy');
  if (data && data.ok) renderAdminPolicy(data.policy);
}

/**
 * Render the designated dataset list and the size cap (in MB).
 * @param {{datasets: Array, size_limit: number}} policyData
 * @returns {void}
 */
function renderAdminPolicy(policyData) {
  const list = el('adminDatasetList');
  if (list) {
    list.textContent = '';
    (policyData.datasets || []).forEach((ds) => {
      const row = mk('div', 'admin-user-row');
      row.appendChild(mk('span', 'admin-user-name', ds.name + ' (' + ds.id + ')'));
      const remove = mk('button', 'danger', 'Remove');
      remove.type = 'button';
      remove.addEventListener('click', () => removeAdminDataset(ds.id));
      row.appendChild(remove);
      list.appendChild(row);
    });
  }
  const cap = el('policySizeLimit');
  if (cap) cap.value = Math.round((policyData.size_limit || 0) / (1024 * 1024));
}

/**
 * Designate a new dataset from the Datasets tab form.
 * @returns {Promise<void>}
 */
async function adminAddDataset() {
  const name = el('adminDatasetName').value.trim();
  const dataYaml = el('adminDatasetPath').value.trim();
  if (!name || !dataYaml) {
    toast('Name and data.yaml path are required');
    return;
  }
  const { res, data } = await apiPost(
    '/api/admin/policy', { add_dataset: { name, data_yaml: dataYaml } });
  if (res.ok) {
    el('adminDatasetName').value = '';
    el('adminDatasetPath').value = '';
    renderAdminPolicy(data.policy);
    toast('Dataset added');
  } else {
    toast((data && data.error) || 'Could not add the dataset');
  }
}

/**
 * Remove a designated dataset.
 * @param {string} id
 * @returns {Promise<void>}
 */
async function removeAdminDataset(id) {
  if (!confirm('Remove dataset "' + id + '"?')) return;
  const { res, data } = await apiPost('/api/admin/policy', { remove_dataset: id });
  if (res.ok) {
    renderAdminPolicy(data.policy);
    toast('Dataset removed');
  } else {
    toast((data && data.error) || 'Could not remove the dataset');
  }
}

/**
 * Save the per-user label size cap (the field is in MB).
 * @returns {Promise<void>}
 */
async function savePolicySizeLimit() {
  const mb = parseInt(el('policySizeLimit').value, 10) || 0;
  const { res, data } = await apiPost('/api/admin/policy', { size_limit: mb * 1024 * 1024 });
  if (res.ok) {
    renderAdminPolicy(data.policy);
    toast('Size limit saved');
  } else {
    toast((data && data.error) || 'Could not save the size limit');
  }
}

/**
 * Populate the Dataset tab's allowed-dataset picker and quota hint.
 * @param {Array<{id: string, name: string}>} datasets
 * @param {{limit: number, used: number}} [quota]
 * @returns {void}
 */
function renderDatasetPicker(datasets, quota) {
  const picker = el('datasetPicker');
  const select = el('datasetPickSelect');
  if (!picker || !select) return;
  const items = datasets || [];
  setHidden(picker, items.length === 0);
  select.textContent = '';
  items.forEach((ds) => {
    const opt = document.createElement('option');
    opt.value = ds.id;
    opt.textContent = ds.name;
    select.appendChild(opt);
  });
  const hint = el('quotaHint');
  if (hint) {
    const limited = quota && quota.limit > 0;
    setHidden(hint, !limited);
    if (limited) {
      hint.textContent = 'Label storage: ' + Math.round(quota.used / 1024)
        + ' KB of ' + Math.round(quota.limit / 1024) + ' KB used';
    }
  }
}

/**
 * Materialise and open the dataset chosen in the picker.
 * @returns {Promise<void>}
 */
async function loadPickedDataset() {
  const id = el('datasetPickSelect').value;
  if (!id) return;
  const { res, data } = await apiPost('/api/datasets/select', { id });
  if (res.ok) {
    await loadConfig(0, { explicit: true });
    toast('Dataset loaded');
  } else {
    toast((data && data.error) || 'Could not load the dataset');
  }
}

/**
 * Show the sign-in overlay, optionally with an error message.
 * @param {string} [message]
 * @returns {void}
 */
function showLogin(message) {
  const overlay = el('loginOverlay');
  if (!overlay) return;
  setAccountControls(false);
  showEl('loginOverlay');
  const err = el('loginError');
  if (message) err.textContent = message;
  setHidden(err, !message);
  const user = el('loginUser');
  if (user && !user.value) user.focus();
}

/**
 * Hide the sign-in overlay and clear the password field.
 * @returns {void}
 */
function hideLogin() {
  hideEl('loginOverlay');
  hideEl('loginError');
  el('loginPass').value = '';
}

/**
 * Submit the sign-in form and start the app on success.
 * @param {Event} [e] Submit event, if any.
 * @returns {Promise<void>}
 */
async function submitLogin(e) {
  if (e) e.preventDefault();
  const btn = el('loginBtn');
  btn.disabled = true;
  try {
    const { res, data } = await apiPost('/api/login', {
      username: el('loginUser').value, password: el('loginPass').value,
    });
    if (res.ok) {
      hideLogin();
      setAccountControls(true);
      startApp();
    } else {
      el('loginPass').value = '';
      showLogin((data && data.error) || 'Sign in failed');
      el('loginPass').focus();
    }
  } catch (err) {
    showLogin('Could not reach the server');
  } finally {
    btn.disabled = false;
  }
}

/**
 * Sign out on the server, then reload the page.
 * @returns {Promise<void>}
 */
async function logout() {
  try { await apiPost('/api/logout', {}); } catch (e) { /* ignore */ }
  location.reload();
}

/**
 * Open the change-password modal with empty fields.
 * @returns {void}
 */
function openPasswordModal() {
  el('pwCurrent').value = '';
  el('pwNew').value = '';
  el('pwConfirm').value = '';
  el('pwError').classList.add('hidden');
  openModal('passwordModal');
  el('pwCurrent').focus();
}

/**
 * Close the change-password modal.
 * @returns {void}
 */
function closePasswordModal() {
  closeModal('passwordModal');
}

/**
 * Validate and submit a password change.
 * @returns {Promise<void>}
 */
async function savePassword() {
  const err = el('pwError');
  const fail = (msg) => { err.textContent = msg; err.classList.remove('hidden'); };
  const next = el('pwNew').value;
  if (!next) return fail('New password must not be empty');
  if (next !== el('pwConfirm').value) return fail('New passwords do not match');
  const btn = el('passwordSave');
  btn.disabled = true;
  try {
    const { res, data } = await apiPost('/api/password', {
      current_password: el('pwCurrent').value, new_password: next,
    });
    if (res.ok) {
      closePasswordModal();
      toast('Password changed');
    } else {
      fail((data && data.error) || 'Could not change the password');
    }
  } catch (e) {
    fail('Could not reach the server');
  } finally {
    btn.disabled = false;
  }
}

/**
 * Build the app once, after login has been satisfied.
 * @returns {void}
 */
function startApp() {
  if (appStarted) return;
  appStarted = true;
  loadConfig().catch((err) => {
    console.error('[ybe] config load failed:', err);
    initSettings(); // still build the UI with browser-only settings
  });
  startPresence();
  // The start-thread check may not have finished when the page loads; retry so a
  // freshly found update still reaches the user without a reload.
  refreshUpdateInfo();
  UPDATE_POLL_MS.forEach((ms) => setTimeout(() => refreshUpdateInfo(), ms));
}

/**
 * Ask the server whether a login is needed, then show the login form or start.
 * @returns {Promise<void>}
 */
async function boot() {
  let info = null;
  try {
    const res = await fetch('/api/session');
    if (res.ok) info = await res.json();
  } catch (e) { /* offline: try to start anyway */ }
  if (info && info.auth_required && !info.authenticated) {
    showLogin();
    return;
  }
  if (info && info.auth_required) setAccountControls(true);
  startApp();
}

// With --debug these surface any error that would otherwise only show in the
// browser console; without it they are no-ops.
window.addEventListener('error', (e) => dbgWarn('uncaught error', e.error || e.message));
window.addEventListener('unhandledrejection', (e) => dbgWarn('unhandled rejection', e.reason));

el('loginForm').addEventListener('submit', submitLogin);
el('logoutBtn').addEventListener('click', logout);
el('changePwBtn').addEventListener('click', openPasswordModal);
el('passwordModalClose').addEventListener('click', closePasswordModal);
el('passwordCancel').addEventListener('click', closePasswordModal);
el('passwordSave').addEventListener('click', savePassword);
el('adminAddUser').addEventListener('click', adminAddUser);
el('adminAddDataset').addEventListener('click', adminAddDataset);
el('policySizeLimit').addEventListener('change', savePolicySizeLimit);
el('datasetPickLoad').addEventListener('click', loadPickedDataset);
boot();
