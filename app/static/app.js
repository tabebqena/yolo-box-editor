// app/static/app.js — login/account, start, boot and final wiring (entry point)
'use strict';

// ---------------------------------------------------------------------------
// login / change password
// Accounts live in the server-side user store (managed with --create-user /
// --list-users); the UI does sign in, sign out and password changes.
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
boot();
