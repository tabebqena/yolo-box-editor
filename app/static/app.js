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
  if (isAdmin) loadAdminUsers();
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
boot();
