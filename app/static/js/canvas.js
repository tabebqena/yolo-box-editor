// app/static/js/canvas.js — interaction state, drawing, hit-testing, read-only
'use strict';

// interaction state
let mode = 'idle';     // idle | drawing | moving | resizing
let start = null;      // canvas px
let dragStart = null;  // canvas px
let mouse = null;      // canvas px
let origBox = null;    // normalized snapshot at drag start
// active resize-handle name (nw, n, …) during a resize
let handle = null;
// Indices left out of the cached base layer while interacting (the boxes being
// moved/resized); empty when idle. Group moves leave every selected box out.
let dragIndices = [];
// Normalized snapshots of the boxes being moved, so a group move applies the
// same delta to each of them.
let dragOrigBoxes = null;

// Mouse-only "draw on top" mode (canvas toolbar button): while on, a plain drag
// always starts a new box even on top of an existing one, without holding the
// force-draw modifier. Persisted in settings; keyboard users use the modifier.
let forceDrawMode = false;
const FORCE_DRAW_MODE_KEY = 'ybe_force_draw_mode';

// Offscreen layer holding the image and every box except the one being
// dragged, so a per-mousemove redraw can blit it and repaint only the active
// box instead of re-stroking all boxes (the cost that made drags lag on images
// with many boxes). Built lazily and re-sized with the main canvas.
let baseCanvas = null;
let baseCtx = null;
let baseExclude = '';   // key of the box-index set left out of the layer ('' = none)
let baseReady = false;  // layer matches the current scene

// The decoded frame currently on screen, preferred over `imageEl`. It is a
// `createImageBitmap` result, closed and replaced on every image so the browser
// frees the previous bitmap's native memory immediately. An <img> instead keeps
// a decoded bitmap cached by URL, and because every load is cache-busted that
// cache grows with the number of images viewed — the tab gets heavier and
// heavier. `null` means the fallback <img> path is in use.
let currentBitmap = null;
// Monotonic id of the newest requested image; a late decode for an older
// request is closed and dropped instead of overwriting the current frame.
let imageLoadSeq = 0;

// the single <img> backing the canvas when createImageBitmap is unavailable
// (e.g. the jsdom tests); loading it resizes the canvas
const imageEl = new Image();
imageEl.onload = () => {
  imgW = imageEl.naturalWidth;
  imgH = imageEl.naturalHeight;
  canvas.width = imgW;
  canvas.height = imgH;
  dbg('image loaded', { src: imageEl.src, size: `${imgW}x${imgH}` });
  draw();
};
imageEl.onerror = () => {
  dbgWarn('image failed to load', { src: imageEl.src });
  blankImage();
};

/**
 * Drop the current decoded frame (bitmap and/or <img> source) so its native
 * memory can be reclaimed. Safe to call when nothing is loaded.
 * @returns {void}
 */
function releaseFrame() {
  if (currentBitmap) {
    currentBitmap.close();
    currentBitmap = null;
  }
  imageEl.removeAttribute('src');
}

/**
 * Blank the editor after the current image could not be loaded (e.g. removed by
 * an action) so no stale frame keeps showing a deleted image.
 * @returns {void}
 */
function blankImage() {
  releaseFrame();
  imgW = 0;
  imgH = 0;
  canvas.width = 0;
  canvas.height = 0;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  boxes = [];
  clearBoxSelection();
  draw();
}

/**
 * Show the image at `url` on the canvas. Prefers a decoded `ImageBitmap`
 * (closed when replaced) over the shared <img> element; falls back to the <img>
 * when `createImageBitmap` is not available.
 * @param {string} url
 * @returns {Promise<void>} Resolves once the frame is applied (or failed).
 */
function displayImage(url) {
  const seq = ++imageLoadSeq;
  if (typeof createImageBitmap !== 'function') {
    // Fallback: reuse the <img> as before (jsdom has no createImageBitmap).
    return new Promise((resolve) => {
      const done = () => {
        imageEl.removeEventListener('load', done);
        imageEl.removeEventListener('error', done);
        resolve();
      };
      imageEl.addEventListener('load', done);
      imageEl.addEventListener('error', done);
      imageEl.removeAttribute('src');
      imageEl.src = url;
    });
  }
  return fetch(url, { cache: 'no-store' })
    .then((res) => {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.blob();
    })
    .then((blob) => createImageBitmap(blob, { imageOrientation: 'from-image' }))
    .then((bitmap) => {
      if (seq !== imageLoadSeq) { bitmap.close(); return; } // superseded
      releaseFrame();
      currentBitmap = bitmap;
      imgW = bitmap.width;
      imgH = bitmap.height;
      canvas.width = imgW;
      canvas.height = imgH;
      dbg('image loaded', { src: url, size: `${imgW}x${imgH}` });
      draw();
    })
    .catch((err) => {
      if (seq !== imageLoadSeq) return; // a newer image superseded this one
      dbgWarn('image failed to load', { src: url, error: String(err) });
      blankImage();
    });
}

/**
 * Clamp a number to the 0..1 range.
 * @param {number} v - Value to clamp.
 * @returns {number}
 */
function clamp01(v) {
  return Math.max(0, Math.min(1, v));
}

/**
 * Convert a normalized YOLO box to a canvas pixel rect.
 * @param {{cx:number,cy:number,w:number,h:number}} b - Normalized box.
 * @returns {{x:number,y:number,w:number,h:number}}
 */
function toPx(b) {
  return {
    x: (b.cx - b.w / 2) * imgW,
    y: (b.cy - b.h / 2) * imgH,
    w: b.w * imgW,
    h: b.h * imgH,
  };
}

/**
 * Convert a canvas pixel rect to a normalized YOLO box.
 * @param {{x:number,y:number,w:number,h:number}} r - Pixel rect.
 * @returns {{class:number,cx:number,cy:number,w:number,h:number}}
 */
function toNorm(r) {
  return {
    class: defaultClass,
    cx: clamp01((r.x + r.w / 2) / imgW),
    cy: clamp01((r.y + r.h / 2) / imgH),
    w: clamp01(r.w / imgW),
    h: clamp01(r.h / imgH),
  };
}

/**
 * Build the axis-aligned pixel rect spanned by two points.
 * @param {{x:number,y:number}} a
 * @param {{x:number,y:number}} b
 * @returns {{x:number,y:number,w:number,h:number}}
 */
function normRect(a, b) {
  return {
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    w: Math.abs(a.x - b.x),
    h: Math.abs(a.y - b.y),
  };
}

/**
 * Clamp a canvas pixel point to the loaded image bounds.
 * @param {{x:number,y:number}} p
 * @returns {{x:number,y:number}}
 */
function clampToImage(p) {
  return {
    x: Math.max(0, Math.min(imgW, p.x)),
    y: Math.max(0, Math.min(imgH, p.y)),
  };
}

/**
 * Return the eight resize-handle positions for a pixel rect.
 * @param {{x:number,y:number,w:number,h:number}} r
 * @returns {Array<{x:number,y:number,name:string}>}
 */
function handlePoints(r) {
  const midX = r.x + r.w / 2;
  const midY = r.y + r.h / 2;
  return [
    { x: r.x, y: r.y, name: 'nw' },
    { x: midX, y: r.y, name: 'n' },
    { x: r.x + r.w, y: r.y, name: 'ne' },
    { x: r.x + r.w, y: midY, name: 'e' },
    { x: r.x + r.w, y: r.y + r.h, name: 'se' },
    { x: midX, y: r.y + r.h, name: 's' },
    { x: r.x, y: r.y + r.h, name: 'sw' },
    { x: r.x, y: midY, name: 'w' },
  ];
}

/**
 * Redraw the canvas: image, boxes, handles and in-progress interactions, then
 * sync the side panel. This is the full path, used whenever the scene changed
 * (new image, selection, box edit, toggle…).
 */
function draw() {
  fastDrawQueued = false; // a full draw supersedes any queued fast repaint
  paintScene(true);
  syncSidePanel();
  syncCanvasToolbar();
}

/**
 * Hot path for an in-progress drag or draw: blit the cached base layer and
 * repaint only the active box (or the in-progress rectangle). Unlike `draw()`
 * it never rebuilds the layer and never touches the side panel — a full
 * `draw()` runs once on mouse-up.
 */
function drawFast() {
  paintScene(false);
}

// True while a fast repaint is queued for the next animation frame.
let fastDrawQueued = false;

/**
 * Queue a fast repaint for the next animation frame. A burst of mousemove
 * events coalesces into a single paint instead of painting once per event (and
 * the input handler no longer paints synchronously). `draw()` cancels any queued
 * fast repaint because its full repaint covers it.
 * @returns {void}
 */
function scheduleFastDraw() {
  if (fastDrawQueued) return;
  fastDrawQueued = true;
  requestAnimationFrame(() => {
    if (!fastDrawQueued) return; // superseded by a full draw()
    fastDrawQueued = false;
    drawFast();
  });
}

/**
 * Compose one frame from the cached base layer plus the active/in-progress
 * element.
 * @param {boolean} forceBase - Rebuild the base layer even if it looks valid.
 */
function paintScene(forceBase) {
  // A zero-sized canvas (no image yet, or a failed load blanked it) has nothing
  // to compose; blitting the matching zero-sized base layer would throw.
  if (!canvas.width || !canvas.height) {
    baseReady = false;
    return;
  }
  const interacting = mode === 'moving' || mode === 'resizing';
  // while dragging, the layer must not contain the box(es) being dragged
  const excludes = interacting
    ? (dragIndices.length ? dragIndices : selectionIndices())
    : [];
  ensureBase(excludes, forceBase);

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(baseCanvas, 0, 0);

  if (interacting) {
    for (const i of excludes) {
      if (boxes[i]) paintBox(ctx, boxes[i], i);
    }
  }

  // a coordinate input highlight only survives while that input keeps focus
  const f = document.activeElement;
  if (editingPoint && (!f || f.dataset.name !== editingPoint.name)) editingPoint = null;
  if (boxesVisible && editingPoint && boxes[editingPoint.i]) {
    drawPointGuide(ctx, toPx(boxes[editingPoint.i]), editingPoint.name);
  }

  if (mode === 'drawing' && start && mouse) {
    const r = normRect(start, mouse);
    ctx.strokeStyle = '#4cc9f0';
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);
    ctx.strokeRect(r.x, r.y, r.w, r.h);
    ctx.setLineDash([]);
  }
}

/**
 * Make sure the base layer is the right size and holds the current scene with
 * `exclude` left out. Rebuilds only when forced, invalidated, or the excluded
 * box changed.
 * @param {number[]} excludes - Box indices to leave out ([] for all of them).
 * @param {boolean} force - Rebuild even when the layer looks current.
 */
function ensureBase(excludes, force) {
  if (!baseCanvas) {
    baseCanvas = document.createElement('canvas');
    baseCtx = baseCanvas.getContext('2d');
  }
  if (baseCanvas.width !== canvas.width || baseCanvas.height !== canvas.height) {
    baseCanvas.width = canvas.width;
    baseCanvas.height = canvas.height;
    force = true; // resizing a canvas clears it
  }
  const key = excludes.join(',');
  if (force || !baseReady || baseExclude !== key) {
    renderBase(excludes);
    baseExclude = key;
    baseReady = true;
  }
}

/**
 * True when box `idx` must stay hidden: `app_isolate_box` is on and a selection
 * exists, so every box other than the selected ones is neither drawn nor
 * hit-tested.
 * @param {number} idx
 * @returns {boolean}
 */
function boxHidden(idx) {
  if (!isolateSelected) return false;
  if (selected < 0 && selectedSet.size === 0) return false;
  return !isBoxSelected(idx);
}

/**
 * Draw the image and every box (except `excludes`) into the base layer.
 * @param {number[]} excludes - Box indices to skip.
 */
function renderBase(excludes) {
  baseCtx.clearRect(0, 0, baseCanvas.width, baseCanvas.height);
  if (currentBitmap) {
    baseCtx.drawImage(currentBitmap, 0, 0);
  } else if (imgW && imgH && imageEl.complete && imageEl.naturalWidth) {
    baseCtx.drawImage(imageEl, 0, 0);
  }
  if (!boxesVisible) return;
  const skip = excludes.length ? new Set(excludes) : null;
  boxes.forEach((b, idx) => {
    if (skip && skip.has(idx)) return;
    if (boxHidden(idx)) return;
    paintBox(baseCtx, b, idx);
  });
}

/**
 * Draw one box (outline, and optionally its label/buttons/handles).
 * @param {CanvasRenderingContext2D} g - Target context (main or base layer).
 * @param {{class:number,cx:number,cy:number,w:number,h:number,fixed?:boolean}} b
 * @param {number} idx - Box index, compared with `selected` for the active look.
 */
function paintBox(g, b, idx) {
  const r = toPx(b);
  const active = isBoxSelected(idx);
  const fixed = !!b.fixed;
  // fixed boxes: muted dashed outline, no resize handles (they ignore dragging
  // but can still be clicked / selected)
  g.strokeStyle = fixed ? '#8a93a6' : active ? '#ffd166' : '#2ecc71';
  g.lineWidth = active && !fixed ? 3 : 2;
  if (fixed) g.setLineDash([7, 4]);
  g.strokeRect(r.x, r.y, r.w, r.h);
  g.setLineDash([]);

  if (boxDetailsVisible) {
    const label = `${b.class}: ${classes[b.class] || 'class ' + b.class}`;
    g.font = '14px system-ui, sans-serif';
    const tw = g.measureText(label).width;
    const ly = Math.max(0, r.y - 18);
    g.fillStyle = fixed
      ? 'rgba(138,147,166,0.9)'
      : active ? 'rgba(255,209,102,0.92)' : 'rgba(46,204,113,0.85)';
    g.fillRect(r.x, ly, tw + 8, 18);
    g.fillStyle = '#111';
    g.fillText(label, r.x + 4, ly + 13);

    if (!readonly) {
      drawDeleteButton(g, r);
      drawClassButton(g, r);
    }
    if (active && !readonly && !fixed) drawHandles(g, r);
  }
}

/**
 * Draw the resize handles for a pixel rect.
 * @param {CanvasRenderingContext2D} g - Target context.
 * @param {{x:number,y:number,w:number,h:number}} r
 */
function drawHandles(g, r) {
  g.fillStyle = '#fff';
  g.strokeStyle = '#111';
  g.lineWidth = 1;
  for (const p of handlePoints(r)) {
    g.fillRect(p.x - HANDLE_SIZE / 2, p.y - HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE);
    g.strokeRect(p.x - HANDLE_SIZE / 2, p.y - HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE);
  }
}

/**
 * Highlight the coordinate currently edited in the side panel, so the user
 * sees which value (cx / cy / w / h) the focused input controls. cx/cy show
 * only the box center point in colour; w/h also mark the box edges they span.
 * @param {CanvasRenderingContext2D} g - Target context.
 * @param {{x:number,y:number,w:number,h:number}} r
 * @param {string} name - Coordinate name (cx, cy, w or h).
 */
function drawPointGuide(g, r, name) {
  const midX = r.x + r.w / 2;
  const midY = r.y + r.h / 2;
  g.save();
  g.strokeStyle = '#ff9f1c';
  g.fillStyle = '#ff9f1c';
  g.lineWidth = 2;
  g.setLineDash([6, 4]);
  const dashLine = (x1, y1, x2, y2) => {
    g.beginPath();
    g.moveTo(x1, y1);
    g.lineTo(x2, y2);
    g.stroke();
  };
  if (name === 'w') {
    dashLine(r.x, midY - r.h / 2 - 10, r.x, midY + r.h / 2 + 10);
    dashLine(r.x + r.w, midY - r.h / 2 - 10, r.x + r.w, midY + r.h / 2 + 10);
  } else if (name === 'h') {
    dashLine(midX - r.w / 2 - 10, r.y, midX + r.w / 2 + 10, r.y);
    dashLine(midX - r.w / 2 - 10, r.y + r.h, midX + r.w / 2 + 10, r.y + r.h);
  }
  g.setLineDash([]);
  g.beginPath();
  g.arc(midX, midY, name === 'cx' || name === 'cy' ? 6 : 5, 0, Math.PI * 2);
  g.fill();
  g.restore();
}

/**
 * Pixel rect of the delete button for a box.
 * @param {{x:number,y:number,w:number,h:number}} r
 * @returns {{x:number,y:number,w:number,h:number}}
 */
function deleteBtnRect(r) {
  return { x: r.x + r.w - DEL_BTN, y: r.y, w: DEL_BTN, h: DEL_BTN };
}

/**
 * Pixel rect of the class-cycle button for a box.
 * @param {{x:number,y:number,w:number,h:number}} r
 * @returns {{x:number,y:number,w:number,h:number}}
 */
function classBtnRect(r) {
  return { x: r.x, y: r.y, w: DEL_BTN, h: DEL_BTN };
}

/**
 * Draw the class-cycle button in the top-left of a box.
 * @param {CanvasRenderingContext2D} g - Target context.
 * @param {{x:number,y:number,w:number,h:number}} r
 */
function drawClassButton(g, r) {
  const d = classBtnRect(r);
  g.fillStyle = 'rgba(76, 201, 240, 0.9)';
  g.fillRect(d.x, d.y, d.w, d.h);
  g.strokeStyle = '#111';
  g.lineWidth = 1;
  g.strokeRect(d.x, d.y, d.w, d.h);
  g.fillStyle = '#111';
  g.font = 'bold 13px system-ui, sans-serif';
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.fillText('/', d.x + d.w / 2, d.y + d.h / 2 + 1);
  g.textAlign = 'start';
  g.textBaseline = 'alphabetic';
}

/**
 * Draw the delete button in the top-right of a box.
 * @param {CanvasRenderingContext2D} g - Target context.
 * @param {{x:number,y:number,w:number,h:number}} r
 */
function drawDeleteButton(g, r) {
  const d = deleteBtnRect(r);
  g.fillStyle = 'rgba(231, 76, 60, 0.9)';
  g.fillRect(d.x, d.y, d.w, d.h);
  g.strokeStyle = '#111';
  g.lineWidth = 1;
  g.strokeRect(d.x, d.y, d.w, d.h);
  const cx = d.x + d.w / 2;
  const cy = d.y + d.h / 2;
  const inset = 4;
  g.strokeStyle = '#fff';
  g.lineWidth = 2;
  g.beginPath();
  g.moveTo(cx - inset, cy - inset);
  g.lineTo(cx + inset, cy + inset);
  g.moveTo(cx + inset, cy - inset);
  g.lineTo(cx - inset, cy + inset);
  g.stroke();
}

/**
 * Convert a mouse event to canvas pixel coordinates.
 * @param {MouseEvent} e
 * @returns {{x:number,y:number}}
 */
function canvasPos(e) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  return {
    x: (e.clientX - rect.left) * scaleX,
    y: (e.clientY - rect.top) * scaleY,
  };
}

/**
 * Hit-test a canvas point against the selected box's resize handles only.
 * Cheap (O(1)) helper for the hover cursor, which does not care about the
 * buttons or the other boxes.
 * @param {{x:number,y:number}} p
 * @returns {string|null} The handle name, or null.
 */
function handleHit(p) {
  if (!boxesVisible || !boxDetailsVisible || selected < 0 || boxes[selected].fixed) return null;
  const r = toPx(boxes[selected]);
  for (const hp of handlePoints(r)) {
    if (Math.abs(p.x - hp.x) <= HANDLE_SIZE && Math.abs(p.y - hp.y) <= HANDLE_SIZE) {
      return hp.name;
    }
  }
  return null;
}

/**
 * Hit-test a canvas point against handles, buttons and boxes.
 * @param {{x:number,y:number}} p
 * @returns {{type:string,handle?:string,index?:number}}
 */
function hitTest(p) {
  // hidden boxes are not drawn, so they must not swallow clicks either
  if (!boxesVisible) return { type: 'none' };
  const h = handleHit(p);
  if (h) return { type: 'handle', handle: h, index: selected };
  if (boxDetailsVisible) {
    for (let i = boxes.length - 1; i >= 0; i--) {
      if (boxHidden(i)) continue;
      const d = deleteBtnRect(toPx(boxes[i]));
      if (p.x >= d.x && p.x <= d.x + d.w && p.y >= d.y && p.y <= d.y + d.h) {
        return { type: 'delete', index: i };
      }
    }
    for (let i = boxes.length - 1; i >= 0; i--) {
      if (boxHidden(i)) continue;
      const c = classBtnRect(toPx(boxes[i]));
      if (p.x >= c.x && p.x <= c.x + c.w && p.y >= c.y && p.y <= c.y + c.h) {
        return { type: 'class', index: i };
      }
    }
  }
  // A fixed box is a protected frame: let clicks pass through to the editable
  // boxes inside it. Prefer the topmost non-fixed box containing the point and
  // only fall back to the fixed box when nothing editable is under the cursor,
  // so a fixed box can still be selected/unfixed where it is not covered.
  let fixedHit = -1;
  for (let i = boxes.length - 1; i >= 0; i--) {
    if (boxHidden(i)) continue;
    const r = toPx(boxes[i]);
    if (p.x >= r.x && p.x <= r.x + r.w && p.y >= r.y && p.y <= r.y + r.h) {
      if (!boxes[i].fixed) return { type: 'box', index: i };
      if (fixedHit < 0) fixedHit = i;
    }
  }
  if (fixedHit >= 0) return { type: 'box', index: fixedHit };
  return { type: 'none' };
}

// Cursor shown while hovering each resize handle, so the user can see the box
// is ready to resize (and in which direction) before pressing the mouse.
const RESIZE_CURSORS = {
  nw: 'nwse-resize', se: 'nwse-resize',
  ne: 'nesw-resize', sw: 'nesw-resize',
  n: 'ns-resize', s: 'ns-resize',
  e: 'ew-resize', w: 'ew-resize',
};

/**
 * Update the canvas cursor for the hovered resize handle.
 * @param {{x:number,y:number}} p
 */
function updateCursor(p) {
  if (mode !== 'idle' || readonly || !boxesVisible) return;
  const name = handleHit(p);
  canvas.style.cursor = name ? RESIZE_CURSORS[name] || 'crosshair' : '';
}

/**
 * True when the force-draw modifier is held for this event. The modifier is
 * configured by the `app_force_draw` binding in your shortcuts.txt
 * (e.g. <Ctrl>, <Alt> or <Ctrl+Shift>); it is not a keydown action. Falls back
 * to Ctrl when unbound. Ctrl/Meta are the Linux-safe choices — many window
 * managers swallow Alt+drag, and Shift is reserved for selecting boxes.
 * @param {KeyboardEvent|MouseEvent} e
 * @returns {boolean}
 */
function forceDrawActive(e) {
  if (forceDrawMode) return true;
  const info = appShortcuts['app_force_draw'];
  const spec = (info && info.shortcut) || 'Ctrl';
  const mods = spec.split('+').map((s) => s.trim().toLowerCase()).filter(Boolean);
  if (!mods.length) return false;
  return mods.every((m) => {
    if (m === 'ctrl' || m === 'control') return e.ctrlKey;
    if (m === 'alt') return e.altKey;
    if (m === 'shift') return e.shiftKey;
    if (m === 'meta' || m === 'cmd' || m === 'command') return e.metaKey;
    return false;
  });
}

/**
 * Sync the class select to a box (or the default) and remember the last pick.
 * @param {number} idx - Selected box index, or -1.
 */
function syncClassSelect(idx) {
  if (idx >= 0) lastSelected = idx;
  const sel = el('classSelect');
  if (!sel) return;
  sel.value = idx >= 0 ? boxes[idx].class : defaultClass;
}

/**
 * Move the selected box by dragging, keeping it inside the image.
 * @param {{x:number,y:number}} p - Current canvas pixel point.
 */
function moveBox(p) {
  if (!dragUndoPushed) { pushUndo(); dragUndoPushed = true; }
  const dx = (p.x - dragStart.x) / imgW;
  const dy = (p.y - dragStart.y) / imgH;
  // Move every selected box (a plain click selects one; Ctrl+click adds more).
  const list = dragOrigBoxes && dragOrigBoxes.length
    ? dragOrigBoxes
    : [{ i: selected, b: origBox }];
  for (const { i, b } of list) {
    if (!b) continue;
    // clamp the centre so the whole box stays inside the image, not just its
    // centre point (the window-level drag can report coordinates off-canvas)
    const cx = Math.max(b.w / 2, Math.min(1 - b.w / 2, b.cx + dx));
    const cy = Math.max(b.h / 2, Math.min(1 - b.h / 2, b.cy + dy));
    boxes[i] = { ...b, cx, cy };
  }
  moved = true;
  scheduleFastDraw(); // cached layer + the moved boxes; full draw() runs on mouse-up
}

/**
 * Resize the selected box from the active handle.
 * @param {{x:number,y:number}} p - Current canvas pixel point.
 */
function resizeBox(p) {
  if (!dragUndoPushed) { pushUndo(); dragUndoPushed = true; }
  p = clampToImage(p);
  const b = origBox;
  const left = (b.cx - b.w / 2) * imgW;
  const right = (b.cx + b.w / 2) * imgW;
  const top = (b.cy - b.h / 2) * imgH;
  const bottom = (b.cy + b.h / 2) * imgH;

  let x1 = left;
  let y1 = top;
  let x2 = right;
  let y2 = bottom;
  if (handle.includes('w')) x1 = p.x;
  if (handle.includes('e')) x2 = p.x;
  if (handle.includes('n')) y1 = p.y;
  if (handle.includes('s')) y2 = p.y;
  // keep every edge within the image
  x1 = Math.max(0, Math.min(imgW, x1));
  x2 = Math.max(0, Math.min(imgW, x2));
  y1 = Math.max(0, Math.min(imgH, y1));
  y2 = Math.max(0, Math.min(imgH, y2));
  if (x2 < x1) [x1, x2] = [x2, x1];
  if (y2 < y1) [y1, y2] = [y2, y1];

  const w = Math.max(x2 - x1, 1);
  const h = Math.max(y2 - y1, 1);
  boxes[selected] = {
    ...origBox,
    cx: clamp01((x1 + x2) / 2 / imgW),
    cy: clamp01((y1 + y2) / 2 / imgH),
    w: clamp01(w / imgW),
    h: clamp01(h / imgH),
  };
  moved = true;
  scheduleFastDraw(); // cached layer + this box only; full draw() runs on mouse-up
}

// How far each keyboard border nudge moves an edge, in normalized units.
const BOX_NUDGE_STEP = 0.005;
// How far each keypress translates a whole box, in normalized units.
const BOX_MOVE_STEP = 0.005;

// Keyboard nudge/move bursts come from held-key auto-repeat; collapse a burst
// into a single undo step so Ctrl+Z undoes the whole adjustment, not one key.
let keyEditUndoAt = 0;
const KEY_EDIT_UNDO_GAP = 700; // ms

/**
 * Push an undo snapshot for a keyboard edit at most once per burst.
 * @returns {void}
 */
function pushKeyEditUndo() {
  const now = Date.now();
  if (now - keyEditUndoAt > KEY_EDIT_UNDO_GAP) pushUndo();
  keyEditUndoAt = now;
}

/**
 * Create a new box at the centre of the image with a default size, select it and
 * open the class picker. Drives the app_new_box shortcut (`N`) and the canvas
 * toolbar's "new box" button, so a box can be created without the mouse.
 * @returns {void}
 */
function newBox() {
  if (readonly || currentIndex < 0 || !imgW || !imgH) return;
  pushUndo();
  boxes.push({ class: defaultClass, cx: 0.5, cy: 0.5, w: 0.25, h: 0.25 });
  selectOnlyBox(boxes.length - 1);
  justDrawn = true;
  syncClassSelect(selected);
  markDirty();
  draw();
  updateHistoryButtons();
  dbg('box created by keyboard', { total: boxes.length });
  runHook('on_box_created');
  openPickerForSelectedBox();
}

/**
 * Translate every selected box by a normalized delta, keeping the whole box
 * inside the image. Drives the app_move_* shortcuts (Alt+arrow) and, indirectly,
 * the toolbar. Applies to the whole selection like a mouse group-drag.
 * @param {number} dx - Normalized horizontal delta.
 * @param {number} dy - Normalized vertical delta.
 * @returns {void}
 */
function moveSelectedBox(dx, dy) {
  const indices = selectionIndices();
  if (readonly || !indices.length) return;
  let changed = false;
  const next = [];
  for (const i of indices) {
    const b = boxes[i];
    const cx = Math.max(b.w / 2, Math.min(1 - b.w / 2, b.cx + dx));
    const cy = Math.max(b.h / 2, Math.min(1 - b.h / 2, b.cy + dy));
    if (cx === b.cx && cy === b.cy) continue;
    next.push([i, { ...b, cx, cy }]);
    changed = true;
  }
  if (!changed) return;
  pushKeyEditUndo();
  for (const [i, b] of next) boxes[i] = b;
  justDrawn = false;
  markDirty();
  draw();
  updateHistoryButtons();
  runHook('on_box_edited');
}

/**
 * Move one border of every selected box by the nudge step, keeping the opposite
 * border fixed. Drives the app_widen_* / app_narrow_* shortcuts.
 * @param {'left'|'right'|'top'|'bottom'} edge - Which border to move.
 * @param {boolean} grow - True to widen (outward), false to narrow (inward).
 */
function nudgeSelectedBox(edge, grow) {
  const indices = selectionIndices();
  if (readonly || !indices.length) return;
  const d = grow ? BOX_NUDGE_STEP : -BOX_NUDGE_STEP;
  let changed = false;
  const next = [];
  for (const i of indices) {
    const b = boxes[i];
    let { cx, cy, w, h } = b;
    if (edge === 'left' || edge === 'right') {
      let x1 = cx - w / 2;
      let x2 = cx + w / 2;
      if (edge === 'right') x2 = Math.max(0, Math.min(1, x2 + d));
      else x1 = Math.max(0, Math.min(1, x1 - d));
      if (x2 - x1 < 0.001) continue;
      cx = (x1 + x2) / 2;
      w = x2 - x1;
    } else {
      let y1 = cy - h / 2;
      let y2 = cy + h / 2;
      if (edge === 'bottom') y2 = Math.max(0, Math.min(1, y2 + d));
      else y1 = Math.max(0, Math.min(1, y1 - d));
      if (y2 - y1 < 0.001) continue;
      cy = (y1 + y2) / 2;
      h = y2 - y1;
    }
    next.push([i, { ...b, cx, cy, w, h }]);
    changed = true;
  }
  if (!changed) return;
  pushKeyEditUndo();
  for (const [i, b] of next) boxes[i] = b;
  markDirty();
  draw();
  updateHistoryButtons();
  runHook('on_box_edited');
}

// ------------------------------------------------------------------------- //
// canvas overlay toggles (shared by shortcuts and the toolbar buttons)
// ------------------------------------------------------------------------- //

/**
 * Show or hide the box handles/labels/buttons (outlines-only mode).
 * @returns {void}
 */
function toggleBoxDetails() {
  boxDetailsVisible = !boxDetailsVisible;
  settingsSet(SHOW_BOX_DETAILS_KEY, boxDetailsVisible ? '1' : '0');
  draw();
  syncCanvasToolbar();
}

/**
 * Show or hide the whole box overlay.
 * @returns {void}
 */
function toggleShowBoxes() {
  boxesVisible = !boxesVisible;
  settingsSet(SHOW_BOXES_KEY, boxesVisible ? '1' : '0');
  draw();
  syncCanvasToolbar();
}

/**
 * Draw only the selected box (or all boxes when nothing is selected).
 * @returns {void}
 */
function toggleIsolateBox() {
  isolateSelected = !isolateSelected;
  settingsSet(ISOLATE_BOX_KEY, isolateSelected ? '1' : '0');
  draw();
  syncCanvasToolbar();
}

/**
 * Toggle the mouse-only "draw on top" mode used by the canvas toolbar.
 * @returns {void}
 */
function toggleForceDrawMode() {
  forceDrawMode = !forceDrawMode;
  settingsSet(FORCE_DRAW_MODE_KEY, forceDrawMode ? '1' : '0');
  syncCanvasToolbar();
}

// ------------------------------------------------------------------------- //
// read-only mode
// ------------------------------------------------------------------------- //
/**
 * Apply the read-only state to the canvas controls and redraw.
 */
function applyReadonly() {
  const sw = el('readonlySw');
  sw.checked = readonly;
  // When the server was started with --readonly it is a hard lock.
  sw.disabled = !!readonly && !!sw.dataset.server;
  const classSel = el('classSelect');
  if (classSel) classSel.disabled = readonly;
  setActionButtonsDisabled(readonly);
  updateHistoryButtons();
  draw();
  syncCanvasToolbar();
  emitReadonlyChange();
}

el('readonlySw').addEventListener('change', (e) => {
  readonly = e.target.checked;
  if (readonly) {
    clearBoxSelection();
    clearTimeout(autoSaveTimer); // no writes in read-only mode
    autoSaveTimer = null;
  }
  applyReadonly();
});
