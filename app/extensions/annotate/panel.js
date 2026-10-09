// Annotate extension panel (example).
//
// Runs in the sandboxed iframe. It never touches the dataset's labels: it reads
// the model's boxes from the package backend (`YBE.call('annotate.get', ...)`)
// and draws them as render-only overlays with `YBE.callbacks.setDrawnBoxes`.
// The Annotate button triggers the package's `annotate` action through
// `/api/extensions/run` with the values entered here.
(async function () {
  'use strict';

  var COLOR = '#e75480';
  var buttonIndex = null;
  var key = null;

  var style = document.createElement('style');
  style.textContent = [
    '.row{display:flex;gap:6px;align-items:center;margin-bottom:6px}',
    'label{flex:0 0 5.5rem;opacity:.8;font-size:12px}',
    'input[type=text]{flex:1;background:var(--bg-sunken,#222);color:var(--text,#eee);',
    'border:1px solid var(--border,#555);border-radius:4px;padding:3px 6px;min-width:0}',
    'button{border:1px solid var(--border,#555);background:var(--bg-raised,#333);',
    'color:var(--text,#eee);border-radius:4px;padding:4px 10px;cursor:pointer}',
    'button:disabled{opacity:.5;cursor:default}',
    '.hint{opacity:.7;font-size:12px}',
    '.status{font-size:12px;opacity:.85;margin-top:4px;min-height:1em}',
    '.show{display:flex;gap:6px;align-items:center;font-size:12px;margin-top:6px}',
  ].join('');
  document.head.appendChild(style);

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function field(labelText, placeholder) {
    var row = el('div', 'row');
    row.appendChild(el('label', null, labelText));
    var input = el('input');
    input.type = 'text';
    input.placeholder = placeholder || '';
    row.appendChild(input);
    return { row: row, input: input };
  }

  var model = field('Model', '/path/to/model.pt');
  var output = field('Output', '/path/to/extension_labels');
  var conf = field('Confidence', '0.25');
  conf.input.value = '0.25';

  var runBtn = el('button', null, 'Annotate all images');
  runBtn.type = 'button';
  runBtn.addEventListener('click', annotate);

  var showLabel = el('label', 'show');
  var show = el('input');
  show.type = 'checkbox';
  show.checked = true;
  show.addEventListener('change', function () {
    YBE.callbacks.setDrawnBoxesVisible(show.checked);
  });
  showLabel.appendChild(show);
  showLabel.appendChild(document.createTextNode('Show extension boxes'));

  var status = el('div', 'status', 'Ready.');

  document.body.appendChild(model.row);
  document.body.appendChild(output.row);
  document.body.appendChild(conf.row);
  document.body.appendChild(runBtn);
  document.body.appendChild(showLabel);
  document.body.appendChild(status);

  function setStatus(text) { status.textContent = text; }

  async function currentKey() {
    var img = await YBE.state.getImage();
    return img ? (img.split + '/' + img.name) : null;
  }

  // Find this package's settings button in the config, so the panel can drive
  // the same server-side action with its own values.
  async function findButtonIndex() {
    try {
      var cfg = await YBE.state.getConfig();
      var pkg = (cfg.extension_packages || []).filter(function (p) {
        return p.id === 'annotate';
      })[0];
      var controls = (pkg && pkg.settings && pkg.settings.controls) || [];
      for (var i = 0; i < controls.length; i++) {
        if (controls[i].type === 'button' && controls[i].action === 'annotate') return i;
      }
    } catch (e) { /* ignore */ }
    return null;
  }

  async function loadStatus() {
    try {
      var s = await YBE.call('annotate.status', []);
      if (s && s.output_dir && !output.input.value) output.input.value = s.output_dir;
    } catch (e) { /* ignore */ }
  }

  async function reload() {
    key = await currentKey();
    if (!key) { YBE.callbacks.clearDrawnBoxes(); setStatus('No image loaded.'); return; }
    var boxes = [];
    try { boxes = await YBE.call('annotate.get', [key]); } catch (e) { boxes = []; }
    await YBE.callbacks.setDrawnBoxes(boxes, { color: COLOR });
    await YBE.callbacks.setDrawnBoxesVisible(show.checked);
    setStatus(boxes.length
      ? boxes.length + ' extension box(es) for this image'
      : 'No extension boxes for this image');
  }

  async function annotate() {
    if (YBE.readonly) return;
    var target = await currentKey();
    if (!target) { setStatus('Load a dataset first.'); return; }
    var out = output.input.value.trim();
    if (!out) { setStatus('Set an output folder first.'); return; }
    if (buttonIndex === null) buttonIndex = await findButtonIndex();
    if (buttonIndex === null) { setStatus('No annotate button in the manifest.'); return; }

    // Remember the folder so the backend reads the same place it wrote to.
    try { await YBE.call('annotate.setDir', [out]); }
    catch (e) { setStatus('Could not set the output folder: ' + e.message); return; }

    runBtn.disabled = true;
    setStatus('Annotating… this can take a while.');
    try {
      var res = await YBE.api.post('/api/extensions/run', {
        package: 'annotate',
        control: buttonIndex,
        target: target,
        values: {
          model: model.input.value.trim(),
          output_dir: out,
          conf: conf.input.value.trim() || '0.25',
        },
      });
      if (!res || res.ok === false) throw new Error((res && res.error) || 'run failed');
      setStatus('Done.');
      await reload();
    } catch (e) {
      setStatus('Failed: ' + e.message);
    } finally {
      runBtn.disabled = !!YBE.readonly;
    }
  }

  YBE.on('image_loaded', reload);
  YBE.on('images_list_loaded', reload);
  YBE.on('readonly_changed', function () {
    runBtn.disabled = !!YBE.readonly;
    reload();
  });

  runBtn.disabled = !!YBE.readonly;
  await loadStatus();
  await reload();
}());
