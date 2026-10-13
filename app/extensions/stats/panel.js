// Dataset statistics extension panel.
//
// Runs in the sandboxed iframe. It only reads: `stats.summary` renders the
// overview tables and `stats.query` answers the query box. No dataset string
// is ever written with innerHTML.
(async function () {
  'use strict';

  var style = document.createElement('style');
  style.textContent = [
    '.bar{display:flex;align-items:center;gap:8px;margin-bottom:6px}',
    'button{border:1px solid var(--border,#555);background:var(--bg-raised,#333);',
    'color:var(--text,#eee);border-radius:4px;padding:3px 9px;cursor:pointer}',
    'button:disabled{opacity:.5;cursor:default}',
    'input{flex:1;min-width:0;background:var(--bg-sunken,#222);color:var(--text,#eee);',
    'border:1px solid var(--border,#555);border-radius:4px;padding:3px 7px}',
    '.hint{opacity:.7;font-size:12px}',
    '.overview{font-size:13px;margin:2px 0 8px}',
    '.section{margin-bottom:10px}',
    '.section h4{margin:0 0 4px;font-size:12px;text-transform:uppercase;',
    'letter-spacing:.04em;opacity:.7}',
    'table{border-collapse:collapse;width:100%;font-size:12px}',
    'th,td{text-align:left;padding:2px 6px;border-top:1px solid var(--border,#333)}',
    'th{opacity:.7;font-weight:600;border-top:0}',
    'td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}',
    '.pill{border:1px solid var(--border,#555);background:var(--bg-raised,#333);',
    'color:var(--text,#eee);border-radius:999px;padding:1px 8px;cursor:pointer;font:inherit}',
    '.pills{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}',
    '.qrow{display:flex;gap:6px;align-items:center}',
    '.qresult{margin-top:6px;font-size:12px}',
    '.qcount{font-size:15px}',
    '.qcount b{font-size:19px}',
    '.matches{max-height:140px;overflow:auto;margin-top:5px;border-top:1px solid var(--border,#333);padding-top:4px}',
    '.match{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px;',
    'white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    '.err{color:var(--red,#e66)}',
  ].join('');
  document.head.appendChild(style);

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function pct(v) { return (Number(v) || 0).toFixed(1) + '%'; }

  function table(headers, rows) {
    var t = document.createElement('table');
    var htr = document.createElement('tr');
    headers.forEach(function (h, i) {
      var th = el('th', i === 0 ? null : 'num', h);
      htr.appendChild(th);
    });
    var thead = document.createElement('thead');
    thead.appendChild(htr);
    t.appendChild(thead);
    var tb = document.createElement('tbody');
    rows.forEach(function (cells) {
      var tr = document.createElement('tr');
      cells.forEach(function (c, i) {
        var td = el('td', i === 0 ? null : 'num');
        if (c instanceof Node) td.appendChild(c);
        else td.textContent = String(c);
        tr.appendChild(td);
      });
      tb.appendChild(tr);
    });
    t.appendChild(tb);
    return t;
  }

  function section(title, node) {
    var s = el('div', 'section');
    s.appendChild(el('h4', null, title));
    s.appendChild(node);
    return s;
  }

  function tagExpr(name) {
    return 'tag:' + (/[\s"']/.test(name) ? '"' + name + '"' : name);
  }

  // --- DOM skeleton -------------------------------------------------------- //
  var refreshBtn = el('button', null, 'Refresh');
  refreshBtn.type = 'button';
  var hint = el('span', 'hint', '');
  var bar = el('div', 'bar');
  bar.appendChild(refreshBtn);
  bar.appendChild(hint);

  var overview = el('div', 'overview', '');
  var body = el('div');

  var qInput = el('input');
  qInput.placeholder = 'tag:smoke and split:train';
  var qBtn = el('button', null, 'Query');
  qBtn.type = 'button';
  var qRow = el('div', 'qrow');
  qRow.appendChild(qInput);
  qRow.appendChild(qBtn);

  var examples = el('div', 'pills');
  var qResult = el('div', 'qresult');
  var queryCard = el('div', 'section');
  queryCard.appendChild(el('h4', null, 'Query'));
  queryCard.appendChild(qRow);
  queryCard.appendChild(examples);
  queryCard.appendChild(qResult);

  document.body.appendChild(bar);
  document.body.appendChild(overview);
  document.body.appendChild(body);
  document.body.appendChild(queryCard);

  function addExample(label, expr) {
    var b = el('button', 'pill', label);
    b.type = 'button';
    b.title = expr;
    b.addEventListener('click', function () { qInput.value = expr; runQuery(); });
    examples.appendChild(b);
  }
  addExample('all', 'all');
  addExample('empty', 'empty');
  addExample('tagged', 'tagged');
  addExample('untagged', 'untagged');

  // --- summary ------------------------------------------------------------- //
  function renderSummary(s) {
    body.textContent = '';
    if (!s || !s.loaded) {
      overview.textContent = 'No dataset loaded.';
      return;
    }
    overview.textContent = s.total + ' image(s) in ' + s.splits.length +
      ' split(s) \u2014 ' + s.labels.boxes + ' box(es), ' +
      s.tags.tagged + ' tagged, ' + s.tags.untagged + ' untagged.';

    if (s.splits.length) {
      body.appendChild(section('By split', table(
        ['Split', 'Images', '%'],
        s.splits.map(function (r) { return [r.name, r.images, pct(r.percent)]; }))));
    }

    var tagsNode;
    if (!s.tags.available.length && !s.tags.unknown.length) {
      tagsNode = el('div', 'hint', 'No tags.yaml beside data.yaml (or no tags used).');
    } else {
      var pills = el('div', 'pills');
      s.tags.available.forEach(function (r) {
        var b = el('button', 'pill', r.name + ' (' + r.images + ')');
        b.type = 'button';
        b.title = 'Query ' + tagExpr(r.name);
        b.addEventListener('click', function () {
          qInput.value = tagExpr(r.name);
          runQuery();
        });
        pills.appendChild(b);
      });
      s.tags.unknown.forEach(function (r) {
        var b = el('button', 'pill', r.name + ' (' + r.images + ') \u26a0');
        b.type = 'button';
        b.title = 'Not in tags.yaml \u2014 query ' + tagExpr(r.name);
        b.addEventListener('click', function () {
          qInput.value = tagExpr(r.name);
          runQuery();
        });
        pills.appendChild(b);
      });
      tagsNode = pills;
      if (s.tags.unknown.length) {
        var warn = el('div', 'hint',
          s.tags.unknown.length + ' tag(s) used on images are not in tags.yaml (\u26a0).');
        var holder = el('div');
        holder.appendChild(pills);
        holder.appendChild(warn);
        tagsNode = holder;
      }
    }
    body.appendChild(section('By tag', tagsNode));

    if (s.classes.length) {
      body.appendChild(section('By class', table(
        ['Class', 'Boxes', 'Images', '% images'],
        s.classes.map(function (r) {
          var name = el('button', 'pill', r.name);
          name.type = 'button';
          name.title = 'Query class:' + r.name;
          name.addEventListener('click', function () {
            qInput.value = 'class:' + (/[\s"']/.test(r.name) ? '"' + r.name + '"' : r.name);
            runQuery();
          });
          return [name, r.boxes, r.images, pct(r.percent_images)];
        }))));
    }

    body.appendChild(section('Labels', table(
      ['Metric', 'Value'],
      [
        ['Images with labels', s.labels.with_labels],
        ['Images with no labels', s.labels.empty],
        ['Boxes total', s.labels.boxes],
        ['Boxes / image (avg)', s.labels.boxes_per_image],
      ])));
  }

  // --- query --------------------------------------------------------------- //
  function renderResult(r) {
    qResult.textContent = '';
    var line = el('div', 'qcount');
    line.appendChild(el('b', null, String(r.count)));
    line.appendChild(document.createTextNode(
      ' of ' + r.total + ' image(s) \u2014 ' + pct(r.percent)));
    qResult.appendChild(line);
    qResult.appendChild(el('div', 'hint', r.description));

    var names = Object.keys(r.by_split);
    if (names.length) {
      qResult.appendChild(table(
        ['Split', 'Matches'],
        names.map(function (n) { return [n, r.by_split[n]]; })));
    }
    if (r.images.length) {
      var list = el('div', 'matches');
      r.images.forEach(function (key) {
        list.appendChild(el('div', 'match', key));
      });
      qResult.appendChild(list);
      if (r.truncated) {
        qResult.appendChild(el('div', 'hint', 'Showing the first 100 matches.'));
      }
    }
  }

  function renderQueryError(msg) {
    qResult.textContent = '';
    qResult.appendChild(el('div', 'err', msg));
  }

  async function runQuery() {
    var expr = (qInput.value || '').trim();
    if (!expr) { qResult.textContent = ''; return; }
    try {
      var r = await YBE.call('stats.query', [expr]);
      renderResult(r);
    } catch (e) {
      renderQueryError(e && e.message ? e.message : String(e));
    }
  }

  async function refresh() {
    refreshBtn.disabled = true;
    try {
      var s = await YBE.call('stats.summary', []);
      renderSummary(s);
      hint.textContent = s && s.data_yaml
        ? s.data_yaml.split(/[\\/]/).pop() : '';
    } catch (e) {
      overview.textContent = 'Could not load statistics: ' +
        (e && e.message ? e.message : String(e));
    } finally {
      refreshBtn.disabled = false;
    }
    if ((qInput.value || '').trim()) await runQuery();
  }

  refreshBtn.addEventListener('click', refresh);
  qBtn.addEventListener('click', runQuery);
  qInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { e.preventDefault(); runQuery(); }
  });

  YBE.on('dataset_loaded', refresh);
  YBE.on('images_list_loaded', refresh);
  YBE.on('saved', function () { /* labels changed: the summary may change */ refresh(); });

  try { await refresh(); } catch (e) { /* the button still lets the user retry */ }
}());
