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
  selected = -1;
  imageTags = [];
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
 * Redraw the canvas: image, boxes, handles and in-progress interactions.
 * @param {false} [panelMode] - Forwarded to `syncSidePanel`: omitted syncs the
 *   whole side panel, `false` skips it during an in-progress interaction
 *   (drawing a box, or dragging one); the panel is synced on mouse-up.
 */
function draw(panelMode) {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (currentBitmap) {
    ctx.drawImage(currentBitmap, 0, 0);
  } else if (imgW && imgH && imageEl.complete && imageEl.naturalWidth) {
    ctx.drawImage(imageEl, 0, 0);
  }

  // a coordinate input highlight only survives while that input keeps focus
  const f = document.activeElement;
  if (editingPoint && (!f || f.dataset.name !== editingPoint.name)) editingPoint = null;

  if (boxesVisible) {
    boxes.forEach((b, idx) => {
      const r = toPx(b);
      const active = idx === selected;
      // fixed boxes: muted dashed outline, no resize handles (they ignore
      // dragging but can still be clicked / selected)
      const fixed = !!b.fixed;
      ctx.strokeStyle = fixed ? '#8a93a6' : active ? '#ffd166' : '#2ecc71';
      ctx.lineWidth = active && !fixed ? 3 : 2;
      if (fixed) ctx.setLineDash([7, 4]);
      ctx.strokeRect(r.x, r.y, r.w, r.h);
      ctx.setLineDash([]);

      if (boxDetailsVisible) {
        const label = `${b.class}: ${classes[b.class] || 'class ' + b.class}`;
        ctx.font = '14px system-ui, sans-serif';
        const tw = ctx.measureText(label).width;
        const ly = Math.max(0, r.y - 18);
        ctx.fillStyle = fixed
          ? 'rgba(138,147,166,0.9)'
          : active ? 'rgba(255,209,102,0.92)' : 'rgba(46,204,113,0.85)';
        ctx.fillRect(r.x, ly, tw + 8, 18);
        ctx.fillStyle = '#111';
        ctx.fillText(label, r.x + 4, ly + 13);

        if (!readonly) {
          drawDeleteButton(r);
          drawClassButton(r);
        }
        if (active && !readonly && !fixed) drawHandles(r);
      }
      if (editingPoint && editingPoint.i === idx) drawPointGuide(r, editingPoint.name);
    });
  }

  if (mode === 'drawing' && start && mouse) {
    const r = normRect(start, mouse);
    ctx.strokeStyle = '#4cc9f0';
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);
    ctx.strokeRect(r.x, r.y, r.w, r.h);
    ctx.setLineDash([]);
  }

  syncSidePanel(panelMode);
}

/**
 * Draw the resize handles for a pixel rect.
 * @param {{x:number,y:number,w:number,h:number}} r
 */
function drawHandles(r) {
  ctx.fillStyle = '#fff';
  ctx.strokeStyle = '#111';
  ctx.lineWidth = 1;
  for (const p of handlePoints(r)) {
    ctx.fillRect(p.x - HANDLE_SIZE / 2, p.y - HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE);
    ctx.strokeRect(p.x - HANDLE_SIZE / 2, p.y - HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE);
  }
}

/**
 * Highlight the coordinate currently edited in the side panel, so the user
 * sees which value (cx / cy / w / h) the focused input controls. cx/cy show
 * only the box center point in colour; w/h also mark the box edges they span.
 * @param {{x:number,y:number,w:number,h:number}} r
 * @param {string} name - Coordinate name (cx, cy, w or h).
 */
function drawPointGuide(r, name) {
  const midX = r.x + r.w / 2;
  const midY = r.y + r.h / 2;
  ctx.save();
  ctx.strokeStyle = '#ff9f1c';
  ctx.fillStyle = '#ff9f1c';
  ctx.lineWidth = 2;
  ctx.setLineDash([6, 4]);
  const dashLine = (x1, y1, x2, y2) => {
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
  };
  if (name === 'w') {
    dashLine(r.x, midY - r.h / 2 - 10, r.x, midY + r.h / 2 + 10);
    dashLine(r.x + r.w, midY - r.h / 2 - 10, r.x + r.w, midY + r.h / 2 + 10);
  } else if (name === 'h') {
    dashLine(midX - r.w / 2 - 10, r.y, midX + r.w / 2 + 10, r.y);
    dashLine(midX - r.w / 2 - 10, r.y + r.h, midX + r.w / 2 + 10, r.y + r.h);
  }
  ctx.setLineDash([]);
  ctx.beginPath();
  ctx.arc(midX, midY, name === 'cx' || name === 'cy' ? 6 : 5, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
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
 * @param {{x:number,y:number,w:number,h:number}} r
 */
function drawClassButton(r) {
  const d = classBtnRect(r);
  ctx.fillStyle = 'rgba(76, 201, 240, 0.9)';
  ctx.fillRect(d.x, d.y, d.w, d.h);
  ctx.strokeStyle = '#111';
  ctx.lineWidth = 1;
  ctx.strokeRect(d.x, d.y, d.w, d.h);
  ctx.fillStyle = '#111';
  ctx.font = 'bold 13px system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('/', d.x + d.w / 2, d.y + d.h / 2 + 1);
  ctx.textAlign = 'start';
  ctx.textBaseline = 'alphabetic';
}

/**
 * Draw the delete button in the top-right of a box.
 * @param {{x:number,y:number,w:number,h:number}} r
 */
function drawDeleteButton(r) {
  const d = deleteBtnRect(r);
  ctx.fillStyle = 'rgba(231, 76, 60, 0.9)';
  ctx.fillRect(d.x, d.y, d.w, d.h);
  ctx.strokeStyle = '#111';
  ctx.lineWidth = 1;
  ctx.strokeRect(d.x, d.y, d.w, d.h);
  const cx = d.x + d.w / 2;
  const cy = d.y + d.h / 2;
  const inset = 4;
  ctx.strokeStyle = '#fff';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(cx - inset, cy - inset);
  ctx.lineTo(cx + inset, cy + inset);
  ctx.moveTo(cx + inset, cy - inset);
  ctx.lineTo(cx - inset, cy + inset);
  ctx.stroke();
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
      const d = deleteBtnRect(toPx(boxes[i]));
      if (p.x >= d.x && p.x <= d.x + d.w && p.y >= d.y && p.y <= d.y + d.h) {
        return { type: 'delete', index: i };
      }
    }
    for (let i = boxes.length - 1; i >= 0; i--) {
      const c = classBtnRect(toPx(boxes[i]));
      if (p.x >= c.x && p.x <= c.x + c.w && p.y >= c.y && p.y <= c.y + c.h) {
        return { type: 'class', index: i };
      }
    }
  }
  for (let i = boxes.length - 1; i >= 0; i--) {
    const r = toPx(boxes[i]);
    if (p.x >= r.x && p.x <= r.x + r.w && p.y >= r.y && p.y <= r.y + r.h) {
      return { type: 'box', index: i };
    }
  }
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
  // clamp the centre so the whole box stays inside the image, not just its
  // centre point (the window-level drag can report coordinates off-canvas)
  const cx = Math.max(origBox.w / 2, Math.min(1 - origBox.w / 2, origBox.cx + dx));
  const cy = Math.max(origBox.h / 2, Math.min(1 - origBox.h / 2, origBox.cy + dy));
  boxes[selected] = { ...origBox, cx, cy };
  moved = true;
  draw(false); // the side panel is synced once, on mouse-up
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
  draw(false); // the side panel is synced once, on mouse-up
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
  renderTagBar();
  draw();
}

el('readonlySw').addEventListener('change', (e) => {
  readonly = e.target.checked;
  if (readonly) {
    selected = -1;
    clearTimeout(autoSaveTimer); // no writes in read-only mode
    autoSaveTimer = null;
  }
  applyReadonly();
});
