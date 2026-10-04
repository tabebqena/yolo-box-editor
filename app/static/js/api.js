// app/static/js/api.js — thin fetch/JSON helpers shared by every module
'use strict';

/**
 * POST a JSON body and return `{ res, data }`: the raw Response (so callers can
 * check status, e.g. 409) plus the parsed JSON body. `opts.keepalive` is passed
 * through for requests that must survive a page unload.
 * @param {string} url
 * @param {Object} [body]
 * @param {Object} [opts] - `{ keepalive }` passed to fetch.
 * @returns {Promise<{res: Response, data: *}>}
 */
async function apiPost(url, body, opts = {}) {
  const init = {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body === undefined ? {} : body),
  };
  if (opts.keepalive) init.keepalive = true;
  const res = await fetch(url, init);
  return { res, data: await res.json() };
}

/**
 * GET a JSON endpoint and return the parsed body.
 * @param {string} url
 * @returns {Promise<*>}
 */
async function apiGet(url) {
  return (await fetch(url)).json();
}

/**
 * GET a JSON endpoint, resolving null on a non-2xx response (instead of
 * throwing) so callers can treat "no data" and "error" the same way.
 * @param {string} url
 * @returns {Promise<*>}
 */
async function apiGetOrNull(url) {
  const res = await fetch(url);
  return res.ok ? res.json() : null;
}
