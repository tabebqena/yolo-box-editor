// Annotate extension panel (example).
//
// Runs in the sandboxed iframe. It never touches the dataset's labels: it reads
// the model's boxes from the package backend (`YBE.call('annotate.get', ...)`)
// and draws them as render-only overlays with `YBE.callbacks.setDrawnBoxes`.
//
// The panel is the single place its settings live. The Annotate button starts
// the run in the backend (`annotate.start`) and then *polls* `annotate.progress`
// instead of waiting on one long request, so a multi-minute run never times out.
(async function () {
  'use strict';

  var COLOR = '#e75480';
  var key = null;
  var running = false;
  var pollTimer = null;
  var modelBoxes = [];

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
    '.bar{height:6px;border-radius:3px;background:var(--bg-sunken,#222);',
    'border:1px solid var(--border,#555);margin-top:5px;overflow:hidden}',
    '.bar > i{display:block;height:100%;width:0;background:' + COLOR + ';',
    'transition:width .3s ease}',
    '.box-list{max-height:170px;overflow:auto;margin-top:8px}',
    '.box-row{display:flex;align-items:center;justify-content:space-between;',
    'gap:8px;font-size:12px;padding:3px 0;border-top:1px solid var(--border,#333)}',
    '.box-row:first-child{border-top:0}',
    '.box-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;',
    'white-space:nowrap}',
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
  var classes = field('Model classes', 'smoke,fire (optional)');
  classes.input.title =
    'Comma-separated class names in the model\'s own order. Leave empty to use ' +
    'the dataset classes.';
  var classHint = el('div', 'hint',
    'Model classes override the dataset class names (empty = dataset classes).');
  classHint.style.marginBottom = '6px';

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
  var barFill = el('i');
  var bar = el('div', 'bar');
  bar.appendChild(barFill);
  var boxList = el('div', 'box-list');

  document.body.appendChild(model.row);
  document.body.appendChild(output.row);
  document.body.appendChild(conf.row);
  document.body.appendChild(classes.row);
  document.body.appendChild(classHint);
  document.body.appendChild(runBtn);
  document.body.appendChild(showLabel);
  document.body.appendChild(status);
  document.body.appendChild(bar);
  document.body.appendChild(boxList);

  function setStatus(text) { status.textContent = text; }

  function setProgress(done, total) {
    var pct = total ? Math.max(0, Math.min(100, Math.round(done * 100 / total))) : 0;
    barFill.style.width = pct + '%';
  }

  function setBusy(on) {
    running = !!on;
    runBtn.disabled = running || !!YBE.readonly;
  }

  async function currentKey() {
    var img = await YBE.state.getImage();
    return img ? (img.split + '/' + img.name) : null;
  }

  async function reload(silent) {
    key = await currentKey();
    if (!key) {
      modelBoxes = [];
      YBE.callbacks.clearDrawnBoxes();
      renderBoxes();
      if (!silent) setStatus('No image loaded.');
      return;
    }
    try { modelBoxes = await YBE.call('annotate.get', [key]); }
    catch (e) { modelBoxes = []; }
    await YBE.callbacks.setDrawnBoxes(modelBoxes, { color: COLOR });
    await YBE.callbacks.setDrawnBoxesVisible(show.checked);
    renderBoxes();
  }

  // One row per model box, each with a Save button that turns it into a real,
  // editable box and hides the overlay (until the image is reloaded).
  function renderBoxes() {
    boxList.innerHTML = '';
    if (!modelBoxes.length) {
      boxList.appendChild(el('div', 'hint', 'No extension boxes for this image.'));
      return;
    }
    modelBoxes.forEach(function (box, i) {
      var row = el('div', 'box-row');
      var name = box.label || (box.class + ': class ' + box.class);
      row.appendChild(el('span', 'box-name', name));
      var btn = el('button', 'box-save', 'Save');
      btn.type = 'button';
      btn.title = 'Add this box to the image (editable) and hide the overlay';
      btn.disabled = !!YBE.readonly;
      btn.addEventListener('click', function () { saveBox(i, btn); });
      row.appendChild(btn);
      boxList.appendChild(row);
    });
  }

  async function saveBox(i, btn) {
    if (YBE.readonly) return;
    var box = modelBoxes[i];
    if (!box) return;
    if (btn) btn.disabled = true;
    try {
      await YBE.callbacks.addBox({
        class: (box.target != null ? box.target : box.class),
        cx: box.cx, cy: box.cy, w: box.w, h: box.h,
      });
    } catch (e) {
      if (btn) btn.disabled = false;
      setStatus('Could not add the box: ' + e.message);
      return;
    }
    modelBoxes.splice(i, 1);
    await YBE.callbacks.setDrawnBoxes(modelBoxes, { color: COLOR });
    renderBoxes();
    setStatus('Added a real box \u2014 press Save (Ctrl+S) to keep it.');
  }

  function progressText(p) {
    var done = (p && p.done) || 0;
    var total = (p && p.total) || 0;
    var pct = total ? Math.round(done * 100 / total) : 0;
    if (p && p.error) return 'Failed: ' + p.error;
    if (p && p.phase === 'loading') return 'Loading model\u2026';
    if (p && p.phase === 'starting') return 'Starting\u2026';
    if (p && p.running) {
      var cur = p.current ? ' \u2014 ' + p.current : '';
      return total
        ? 'Annotating ' + done + '/' + total + ' (' + pct + '%)' + cur
        : 'Annotating\u2026' + cur;
    }
    if (p && p.phase === 'done') {
      return 'Done \u2014 ' + done + '/' + total + ' image(s).';
    }
    return 'Ready.';
  }

  function stopPoll() {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  }

  function schedulePoll() {
    stopPoll();
    pollTimer = setTimeout(poll, 900);
  }

  async function poll() {
    var p;
    try {
      p = await YBE.call('annotate.progress', []);
    } catch (e) {
      stopPoll();
      setBusy(false);
      setStatus('Lost track of the run: ' + e.message);
      return;
    }
    setStatus(progressText(p));
    setProgress((p && p.done) || 0, (p && p.total) || 0);
    // Keep the current image's overlays fresh as the run writes labels, so the
    // boxes appear while the model is still working (silent: status is progress).
    await reload(true);
    if (p && p.running) {
      setBusy(true);
      schedulePoll();
      return;
    }
    stopPoll();
    setBusy(false);
    if (p && p.error) setStatus('Failed: ' + p.error);
    else if (p && p.phase === 'done') setStatus(progressText(p));
  }

  async function annotate() {
    if (YBE.readonly) return;
    var target = await currentKey();
    if (!target) { setStatus('Load a dataset first.'); return; }
    var modelPath = model.input.value.trim();
    var out = output.input.value.trim();
    var confidence = conf.input.value.trim() || '0.25';
    if (!modelPath) { setStatus('Set the model path first.'); return; }
    if (!out) { setStatus('Set an output folder first.'); return; }

    setBusy(true);
    setProgress(0, 0);
    setStatus('Starting\u2026');
    var res;
    try {
      res = await YBE.call('annotate.start', [{
        model: modelPath, output_dir: out, conf: confidence,
        classes: classes.input.value.trim(),
      }]);
    } catch (e) {
      setBusy(false);
      setStatus('Failed: ' + e.message);
      return;
    }
    if (!res || res.ok === false) {
      setBusy(!!(res && res.running));
      setStatus('Failed: ' + ((res && res.error) || 'could not start'));
      if (res && res.running) schedulePoll();
      return;
    }
    schedulePoll();
  }

  async function loadState() {
    try {
      var s = await YBE.call('annotate.status', []);
      if (!s) return;
      if (s.model) model.input.value = s.model;
      if (s.conf) conf.input.value = s.conf;
      if (s.classes) classes.input.value = s.classes;
      if (!s.classes && s.auto_classes && s.auto_classes.length) {
        classes.input.placeholder = s.auto_classes.join(',');
        classHint.textContent = 'Using the model\'s classes: ' +
          s.auto_classes.join(', ') + ' (type to override).';
      }
      if (s.output_dir) output.input.value = s.output_dir;
      if (s.running) {
        setBusy(true);
        setStatus('Annotating\u2026');
        schedulePoll();
      }
    } catch (e) { /* ignore */ }
  }

  // Always refresh the overlays, even mid-run: existing labels should show and
  // new ones appear as the model writes them. `silent` keeps the progress status.
  YBE.on('image_loaded', function () { reload(running); });
  YBE.on('images_list_loaded', function () { reload(running); });
  YBE.on('readonly_changed', function () {
    runBtn.disabled = running || !!YBE.readonly;
    reload(running);
  });

  runBtn.disabled = !!YBE.readonly;
  await loadState();
  await reload(running);
}());
