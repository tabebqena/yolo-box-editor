// app/static/app.js — login/account, start, boot and final wiring (entry point)
'use strict';

// ---------------------------------------------------------------------------
// login / change password
// Accounts live in the server-side user store (managed with --create-user /
// --list-users); the UI does sign in, sign out and password changes.
// ---------------------------------------------------------------------------
let appStarted = false;

// Show the signed-in-only controls: the Settings > Account tab and its
// Sign out / Change password buttons.
function setAccountControls(visible) {
  setHidden('accountTabBtn', !visible);
  setHidden('logoutBtn', !visible);
  setHidden('changePwBtn', !visible);
}

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

function hideLogin() {
  hideEl('loginOverlay');
  hideEl('loginError');
  el('loginPass').value = '';
}

async function submitLogin(e) {
  if (e) e.preventDefault();
  const btn = el('loginBtn');
  btn.disabled = true;
  try {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: el('loginUser').value, password: el('loginPass').value }),
    });
    if (res.ok) {
      hideLogin();
      setAccountControls(true);
      startApp();
    } else {
      let msg = 'Sign in failed';
      try {
        const d = await res.json();
        if (d && d.error) msg = d.error;
      } catch (err) { /* ignore */ }
      el('loginPass').value = '';
      showLogin(msg);
      el('loginPass').focus();
    }
  } catch (err) {
    showLogin('Could not reach the server');
  } finally {
    btn.disabled = false;
  }
}

async function logout() {
  try { await fetch('/api/logout', { method: 'POST' }); } catch (e) { /* ignore */ }
  location.reload();
}

function openPasswordModal() {
  el('pwCurrent').value = '';
  el('pwNew').value = '';
  el('pwConfirm').value = '';
  el('pwError').classList.add('hidden');
  openModal('passwordModal');
  el('pwCurrent').focus();
}

function closePasswordModal() {
  closeModal('passwordModal');
}

async function savePassword() {
  const err = el('pwError');
  const fail = (msg) => { err.textContent = msg; err.classList.remove('hidden'); };
  const next = el('pwNew').value;
  if (!next) return fail('New password must not be empty');
  if (next !== el('pwConfirm').value) return fail('New passwords do not match');
  const btn = el('passwordSave');
  btn.disabled = true;
  try {
    const res = await fetch('/api/password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password: el('pwCurrent').value, new_password: next }),
    });
    if (res.ok) {
      closePasswordModal();
      toast('Password changed');
    } else {
      let msg = 'Could not change the password';
      try {
        const d = await res.json();
        if (d && d.error) msg = d.error;
      } catch (e) { /* ignore */ }
      fail(msg);
    }
  } catch (e) {
    fail('Could not reach the server');
  } finally {
    btn.disabled = false;
  }
}

// Build the app once, after login has been satisfied.
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

// Ask the server whether a login is needed before starting the app.
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
