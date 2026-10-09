// Tags extension panel.
//
// Runs in the sandboxed iframe. It talks to the package backend only through
// `YBE.call('tags.*', ...)`: `tags.available`, `tags.get`, `tags.set`,
// `tags.clear`, `tags.copyFromPrev`, `tags.setDir`.
(async function () {
  'use strict';

  var available = [];
  var current = [];
  var key = null;
  var expanded = false;

  var style = document.createElement('style');
  style.textContent = [
    '.tagbar{display:flex;flex-wrap:wrap;align-items:center;gap:4px}',
    '.badge{border:1px solid var(--border,#555);background:var(--bg-raised,#333);',
    'color:var(--text,#eee);border-radius:999px;padding:2px 8px;cursor:pointer}',
    '.badge.on{background:var(--accent,#4a7);border-color:var(--accent,#4a7);color:#fff}',
    '.num{opacity:.6;margin-right:4px;font-size:11px}',
    '.add{display:flex;gap:4px;margin-left:auto}',
    'input{background:var(--bg-sunken,#222);color:var(--text,#eee);',
    'border:1px solid var(--border,#555);border-radius:4px;padding:2px 6px;width:10rem}',
    'button{border:1px solid var(--border,#555);background:var(--bg-raised,#333);',
    'color:var(--text,#eee);border-radius:4px;padding:2px 8px;cursor:pointer}',
    '.hint{opacity:.7;font-size:12px}',
  ].join('');
  document.head.appendChild(style);

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  async function currentKey() {
    var img = await YBE.state.getImage();
    return img ? (img.split + '/' + img.name) : null;
  }

  async function refresh() {
    key = await currentKey();
    try {
      available = await YBE.call('tags.available', []);
    } catch (e) { available = []; }
    if (key) {
      try { current = await YBE.call('tags.get', [key]); } catch (e) { current = []; }
    } else {
      current = [];
    }
    render();
  }

  function render() {
    document.body.textContent = '';
    if (!key) {
      document.body.appendChild(el('div', 'hint', 'No image loaded'));
      return;
    }
    var bar = el('div', 'tagbar');
    var on = {};
    current.forEach(function (t) { on[t] = true; });

    var shown = {};
    function badge(name, active, num) {
      if (shown[name]) return;
      shown[name] = true;
      var b = el('button', 'badge' + (active ? ' on' : ''));
      b.type = 'button';
      if (num) b.appendChild(el('span', 'num', String(num)));
      b.appendChild(document.createTextNode(name));
      b.title = (active ? 'Remove tag "' : 'Add tag "') + name + '"';
      b.addEventListener('click', function () {
        if (YBE.readonly) return;
        setTags(active ? current.filter(function (t) { return t !== name; })
                       : current.concat([name]));
      });
      bar.appendChild(b);
    }

    available.forEach(function (t, i) { badge(t, !!on[t], i + 1); });
    current.forEach(function (t) { if (!on[t]) return; badge(t, true, null); });

    var add = el('div', 'add');
    var input = el('input');
    input.placeholder = 'add a tag…';
    input.maxLength = 64;
    input.disabled = !!YBE.readonly;
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); addFromInput(); }
    });
    var btn = el('button', null, '+');
    btn.type = 'button';
    btn.disabled = !!YBE.readonly;
    btn.addEventListener('click', addFromInput);
    add.appendChild(input);
    add.appendChild(btn);
    bar.appendChild(add);
    document.body.appendChild(bar);

    var fresh = current.filter(function (t) { return available.indexOf(t) < 0; });
    if (!available.length) {
      document.body.appendChild(el('div', 'hint', 'No tags.yaml beside data.yaml'));
    } else if (fresh.length) {
      document.body.appendChild(el('div', 'hint', fresh.length + ' tag(s) not in tags.yaml'));
    }
  }

  function addFromInput() {
    var input = document.querySelector('input');
    if (!input || YBE.readonly) return;
    var name = (input.value || '').trim();
    if (!name || current.indexOf(name) >= 0) return;
    input.value = '';
    setTags(current.concat([name]));
  }

  async function setTags(tags) {
    if (!key || YBE.readonly) return;
    try {
      var res = await YBE.call('tags.set', [key, tags]);
      current = (res && res.tags) || tags;
      if (res && res.available) available = res.available;
      render();
    } catch (e) { /* read-only or write error */ }
  }

  async function toggleByNumber(n) {
    if (n < 1 || n > available.length) return;
    var name = available[n - 1];
    if (current.indexOf(name) >= 0) {
      await setTags(current.filter(function (t) { return t !== name; }));
    } else {
      await setTags(current.concat([name]));
    }
  }

  // Extension app actions arrive as `app_action` events for this package.
  YBE.on('app_action', function (p) {
    var name = p && p.name;
    if (!name) return;
    if (name === 'refresh_image_tags') { refresh(); return; }
    if (name === 'clear_tags') { setTags([]); return; }
    if (name === 'copy_tags_from_prev') {
      if (!key || YBE.readonly) return;
      YBE.call('tags.copyFromPrev', [key]).then(function () { refresh(); });
      return;
    }
    if (name.indexOf('toggle_tag_') === 0) {
      toggleByNumber(parseInt(name.slice('toggle_tag_'.length), 10));
    }
  });

  // Core actions that change this image: reload the tags.
  var RELOAD = ['app_refresh_image_all', 'app_refresh_image_labels',
    'app_copy_labels_from_prev', 'app_reload_images_list'];
  YBE.on('after_app_action', function (p) {
    if (p && RELOAD.indexOf(p.action) >= 0) refresh();
  });
  YBE.on('image_loaded', refresh);
  YBE.on('images_list_loaded', refresh);
  YBE.on('readonly_changed', function () { render(); });

  refresh();
}());
