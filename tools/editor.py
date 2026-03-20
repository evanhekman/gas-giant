#!/usr/bin/env python3
"""Pixel art sprite editor for gas-giant.
Run: python3 tools/editor.py
Then open: http://localhost:8765
Sprites saved to: assets/sprites/<name>.png
"""

import json
import os
import struct
import webbrowser
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "assets", "sprites"
)
PORT = 8765


# ── PNG encode / decode (pure stdlib) ─────────────────────────────────────────


def png_encode(pixels):
    """Encode list-of-rows of [r,g,b,a] to PNG bytes (RGBA, 8-bit)."""
    h = len(pixels)
    w = len(pixels[0]) if h else 0

    def chunk(tag, data):
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    raw = b"".join(b"\x00" + bytes(c for px in row for c in px) for row in pixels)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def png_decode(data):
    """Decode PNG bytes → (pixels, width, height). pixels[y][x] = [r,g,b,a]."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "Not a valid PNG"
    pos = 8
    width = height = color_type = 0
    bpp = 4
    idat = b""

    while pos < len(data):
        ln = struct.unpack(">I", data[pos : pos + 4])[0]
        tag = data[pos + 4 : pos + 8]
        cd = data[pos + 8 : pos + 8 + ln]
        pos += 12 + ln
        if tag == b"IHDR":
            width, height = struct.unpack(">II", cd[:8])
            color_type = cd[9]
            bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type, 4)
        elif tag == b"IDAT":
            idat += cd
        elif tag == b"IEND":
            break

    raw = zlib.decompress(idat)
    stride = width * bpp
    prev = bytes(stride)
    rpos = 0
    pixels = []

    for _ in range(height):
        ft = raw[rpos]
        rpos += 1
        row = bytearray(raw[rpos : rpos + stride])
        rpos += stride
        if ft == 1:
            for i in range(bpp, stride):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                a = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + (a + prev[i]) // 2) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = row[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                row[i] = (row[i] + pr) & 0xFF
        prev = bytes(row)
        if color_type == 6:
            pixels.append(
                [
                    [row[x * 4], row[x * 4 + 1], row[x * 4 + 2], row[x * 4 + 3]]
                    for x in range(width)
                ]
            )
        elif color_type == 2:
            pixels.append(
                [
                    [row[x * 3], row[x * 3 + 1], row[x * 3 + 2], 255]
                    for x in range(width)
                ]
            )
        elif color_type == 0:
            pixels.append([[row[x], row[x], row[x], 255] for x in range(width)])
        else:
            raise ValueError(f"Unsupported PNG color type {color_type}")

    return pixels, width, height


# ── HTML / JS ─────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Gas Giant — Sprite Editor</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: #16161a; color: #c8c8d0;
  font-family: 'Courier New', monospace; font-size: 12px;
  display: flex; height: 100vh; overflow: hidden;
}

/* ── panels ── */
#panel-left {
  width: 180px; min-width: 180px;
  background: #101014; border-right: 1px solid #2a2a35;
  display: flex; flex-direction: column; padding: 8px; gap: 8px; overflow: hidden;
}
#panel-right {
  width: 200px; min-width: 200px;
  background: #101014; border-left: 1px solid #2a2a35;
  display: flex; flex-direction: column; padding: 8px; gap: 6px; overflow: hidden;
}
#main {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 10px;
  background: #1a1a22; overflow: hidden;
}

/* ── sections ── */
.section { display: flex; flex-direction: column; gap: 4px; }
.section-title {
  color: #555; font-size: 10px; letter-spacing: 1px; text-transform: uppercase;
  border-bottom: 1px solid #252530; padding-bottom: 3px; margin-bottom: 2px;
}

/* ── controls ── */
button {
  background: #202030; color: #a8a8c0; border: 1px solid #333348;
  padding: 3px 8px; cursor: pointer; font-family: inherit; font-size: 11px;
}
button:hover { background: #2a2a42; color: #c8c8e0; }
button.active { background: #2a2a58; border-color: #5858a8; color: #d0d0ff; }
button.danger { border-color: #582020; }
button.danger:hover { background: #381818; }
.row { display: flex; gap: 4px; }
.row button { flex: 1; }

input[type=text] {
  background: #18181f; color: #b8b8d0; border: 1px solid #333348;
  padding: 3px 6px; font-family: inherit; font-size: 11px; width: 100%;
}
input[type=text]:focus { outline: none; border-color: #5858a8; }

select {
  background: #202030; color: #b8b8d0; border: 1px solid #333348;
  font-family: inherit; font-size: 11px; padding: 2px 4px;
}

/* ── sprite list ── */
#sprite-list-wrap {
  flex: 1; overflow-y: auto; min-height: 0;
}
#sprite-list {
  display: flex; flex-direction: column; gap: 2px;
}
.sprite-item {
  padding: 3px 6px; cursor: pointer;
  border: 1px solid transparent; border-radius: 2px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.sprite-item:hover { background: #202030; }
.sprite-item.active { background: #20204a; border-color: #404090; }

/* ── canvas ── */
#canvas-wrap { position: relative; border: 1px solid #2a2a3a; }
canvas { display: block; image-rendering: pixelated; image-rendering: crisp-edges; }
#overlay-canvas { position: absolute; top: 0; left: 0; pointer-events: none; }

/* ── palette ── */
#palette-groups { display: flex; flex-direction: column; gap: 8px; }
.pal-group { display: flex; flex-direction: column; gap: 3px; }
.pal-group-header {
  display: flex; align-items: center; gap: 4px;
  color: #555; font-size: 10px; letter-spacing: 1px; text-transform: uppercase;
  border-bottom: 1px solid #252530; padding-bottom: 2px; cursor: default;
}
.pal-group-name {
  flex: 1; background: none; border: none; color: #555;
  font-family: inherit; font-size: 10px; letter-spacing: 1px; text-transform: uppercase;
  padding: 0; cursor: text; outline: none; min-width: 0;
}
.pal-group-name:focus { color: #b0b0d0; border-bottom: 1px solid #5858a8; }
.pal-group-del { cursor: pointer; color: #442222; font-size: 11px; padding: 0 2px; flex-shrink: 0; }
.pal-group-del:hover { color: #cc4444; }
.pal-swatches {
  display: flex; flex-wrap: wrap; gap: 3px;
  min-height: 12px; padding: 2px;
  border: 1px solid transparent; border-radius: 2px;
}
.pal-swatches.drag-over { border-color: #5858a8; background: #1a1a30; }
.swatch {
  width: 22px; height: 22px;
  border: 2px solid #2a2a3a; cursor: pointer; flex-shrink: 0;
}
.swatch:hover { border-color: #6a6a9a; }
.swatch.selected { border-color: #ffffff; }
.swatch.dragging { opacity: 0.4; }
.swatch.transparent {
  background-color: transparent;
  background-image:
    linear-gradient(45deg, #444 25%, transparent 25%),
    linear-gradient(-45deg, #444 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, #444 75%),
    linear-gradient(-45deg, transparent 75%, #444 75%);
  background-position: 0 0, 0 4px, 4px -4px, -4px 0px;
  background-size: 8px 8px;
}
#hex-row { display: flex; gap: 4px; align-items: center; }
#hex-row input { flex: 1; }
#hex-preview { width: 22px; height: 22px; border: 1px solid #333; flex-shrink: 0; }
#group-target-select {
  background: #202030; color: #b8b8d0; border: 1px solid #333348;
  font-family: inherit; font-size: 11px; padding: 2px 4px; width: 100%;
}

#status { color: #484860; font-size: 11px; }
</style>
</head>
<body>

<!-- ── LEFT PANEL: sprite browser ── -->
<div id="panel-left">
  <div class="section-title">Sprites</div>
  <div id="sprite-list-wrap">
    <div id="sprite-list"></div>
  </div>

  <div class="section">
    <div class="section-title">New sprite</div>
    <input type="text" id="new-name" placeholder="sprite_name" />
    <div class="row">
      <button id="btn-8"  class="active" onclick="setNewSize(8)">8×8</button>
      <button id="btn-32" onclick="setNewSize(32)">32×32</button>
    </div>
    <button onclick="newSprite()">Create blank</button>
    <button onclick="duplicateSprite()">Duplicate current</button>
  </div>

  <div class="section" style="margin-top:auto">
    <button onclick="saveSprite()">Save  [Ctrl+S]</button>
  </div>
</div>

<!-- ── CENTER: canvas + toolbar ── -->
<div id="main">
  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:center">
    <button id="tool-draw"  class="active" onclick="setTool('draw')">Draw</button>
    <button id="tool-erase" onclick="setTool('erase')">Erase</button>
    <button id="tool-fill"  onclick="setTool('fill')">Fill</button>
    <span style="color:#333">│</span>
    <button id="brush-1" class="active" onclick="setBrush(1)">1px</button>
    <button id="brush-2" onclick="setBrush(2)">2px</button>
    <button id="brush-4" onclick="setBrush(4)">4px</button>
    <span style="color:#333">│</span>
    <button onclick="undo()">Undo  [Ctrl+Z]</button>
    <span style="color:#333">│</span>
    <button id="btn-grid" class="active" onclick="toggleGrid()">Grid</button>
    <span style="color:#333">│</span>
    Zoom&nbsp;
    <select id="zoom-select" onchange="setZoom(+this.value)">
      <option value="1">1×</option>
      <option value="2">2×</option>
      <option value="4">4×</option>
      <option value="8">8×</option>
      <option value="16" selected>16×</option>
      <option value="32">32×</option>
    </select>
  </div>

  <div id="canvas-wrap">
    <canvas id="pixel-canvas"></canvas>
    <canvas id="overlay-canvas"></canvas>
  </div>

  <div id="status">no sprite loaded</div>
</div>

<!-- ── RIGHT PANEL: palette ── -->
<div id="panel-right">
  <div style="display:flex;align-items:baseline;gap:6px;flex-shrink:0">
    <div class="section-title">Palette</div>
    <span id="color-hover" style="font-size:11px;color:#666;font-family:inherit;letter-spacing:0"></span>
  </div>

  <!-- transparent always at top -->
  <div style="flex-shrink:0">
    <div class="swatch transparent" id="swatch-transparent"
         onclick="selectTransparent()"
         onmouseenter="document.getElementById('color-hover').textContent='transparent'"
         onmouseleave="document.getElementById('color-hover').textContent=''"></div>
  </div>

  <!-- scrollable groups area -->
  <div style="flex:1;overflow-y:auto;min-height:0">
    <div id="palette-groups"></div>
  </div>

  <!-- add color -->
  <div class="section" style="flex-shrink:0;border-top:1px solid #252530;padding-top:6px;margin-top:4px">
    <div class="section-title">Add to group</div>
    <select id="group-target-select"></select>
    <div id="hex-row" style="margin-top:4px">
      <input type="text" id="hex-input" placeholder="#rrggbb" maxlength="7" />
      <div id="hex-preview"></div>
    </div>
    <div class="row" style="margin-top:4px">
      <button onclick="addColor()">Add  [Enter]</button>
      <button class="danger" onclick="removeColor()">Remove</button>
    </div>
    <button onclick="addGroup()" style="margin-top:4px;width:100%">+ New group</button>
  </div>
</div>

<script>
// ── state ──────────────────────────────────────────────────────────────────────
let canvasW = 8, canvasH = 8;
let pixels  = [];       // [y][x] = [r,g,b,a] or null
// paletteGroups: [{name, colors: ['#rrggbb', ...]}, ...]
let paletteGroups = [];
// selColor: {group, index} | 'transparent' | null
let selColor = null;
let tool     = 'draw';
let brushSize = 1;
let zoom     = 16;
let gridOn   = true;
let history  = [];      // array of pixel snapshots
let painting = false;
let newSize  = 8;
let currentSprite = null;

const canvas  = document.getElementById('pixel-canvas');
const overlay = document.getElementById('overlay-canvas');
const ctx     = canvas.getContext('2d');
const octx    = overlay.getContext('2d');

// ── canvas init ────────────────────────────────────────────────────────────────
function initPixels(w, h) {
  canvasW = w; canvasH = h;
  pixels = Array.from({length: h}, () => Array(w).fill(null));
}

function resizeCanvas() {
  const w = canvasW * zoom, h = canvasH * zoom;
  canvas.width = overlay.width = w;
  canvas.height = overlay.height = h;
  canvas.style.width = overlay.style.width = w + 'px';
  canvas.style.height = overlay.style.height = h + 'px';
  checkerPat = null; // resizing resets the canvas context, invalidating the cached pattern
}

// ── rendering ──────────────────────────────────────────────────────────────────
let checkerPat = null;
function getChecker() {
  if (checkerPat) return checkerPat;
  const c = document.createElement('canvas'); c.width = c.height = 4;
  const x = c.getContext('2d');
  x.fillStyle = '#2a2a2a'; x.fillRect(0,0,4,4);
  x.fillStyle = '#3a3a3a'; x.fillRect(0,0,2,2); x.fillRect(2,2,2,2);
  checkerPat = ctx.createPattern(c, 'repeat');
  return checkerPat;
}

function render() {
  ctx.fillStyle = getChecker();
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  for (let y = 0; y < canvasH; y++) {
    for (let x = 0; x < canvasW; x++) {
      const px = pixels[y][x];
      if (px) {
        ctx.fillStyle = `rgba(${px[0]},${px[1]},${px[2]},${px[3]/255})`;
        ctx.fillRect(x*zoom, y*zoom, zoom, zoom);
      }
    }
  }
  renderGrid();
}

function renderGrid() {
  octx.clearRect(0, 0, overlay.width, overlay.height);
  if (!gridOn || zoom < 3) return;
  octx.strokeStyle = 'rgba(0,0,0,0.4)';
  octx.lineWidth = 0.5;
  for (let x = 0; x <= canvasW; x++) {
    octx.beginPath(); octx.moveTo(x*zoom+0.5, 0); octx.lineTo(x*zoom+0.5, canvasH*zoom); octx.stroke();
  }
  for (let y = 0; y <= canvasH; y++) {
    octx.beginPath(); octx.moveTo(0, y*zoom+0.5); octx.lineTo(canvasW*zoom, y*zoom+0.5); octx.stroke();
  }
}

// ── palette ────────────────────────────────────────────────────────────────────

function selEq(a, b) {
  if (a === b) return true;
  if (!a || !b || typeof a !== 'object' || typeof b !== 'object') return false;
  return a.group === b.group && a.index === b.index;
}

function renderPalette() {
  // transparent swatch
  const ts = document.getElementById('swatch-transparent');
  ts.classList.toggle('selected', selColor === 'transparent');

  // groups
  const container = document.getElementById('palette-groups');
  container.innerHTML = '';

  paletteGroups.forEach((group, gi) => {
    const groupEl = document.createElement('div');
    groupEl.className = 'pal-group';

    // header
    const header = document.createElement('div');
    header.className = 'pal-group-header';

    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.className = 'pal-group-name';
    nameInput.value = group.name;
    nameInput.onchange = () => { group.name = nameInput.value; savePalette(); refreshGroupSelect(); };

    const delBtn = document.createElement('span');
    delBtn.className = 'pal-group-del';
    delBtn.textContent = '✕';
    delBtn.title = 'Delete group';
    delBtn.onclick = () => { paletteGroups.splice(gi, 1); renderPalette(); savePalette(); refreshGroupSelect(); };

    header.appendChild(nameInput);
    header.appendChild(delBtn);

    // swatches container (drop target)
    const swatchRow = document.createElement('div');
    swatchRow.className = 'pal-swatches';
    swatchRow.dataset.group = gi;

    swatchRow.addEventListener('dragover', e => { e.preventDefault(); swatchRow.classList.add('drag-over'); });
    swatchRow.addEventListener('dragleave', () => swatchRow.classList.remove('drag-over'));
    swatchRow.addEventListener('drop', e => {
      e.preventDefault();
      swatchRow.classList.remove('drag-over');
      const data = JSON.parse(e.dataTransfer.getData('text/plain'));
      const srcGroup = paletteGroups[data.group];
      const color = srcGroup.colors[data.index];
      // insert into target group (duplicate allowed)
      paletteGroups[gi].colors.push(color);
      // remove from source only if same group drag-reorder or user opts to move
      // for cross-group: keep original (copy semantics); within same group: move
      if (data.group === gi) {
        const removeIdx = data.index < paletteGroups[gi].colors.length - 1 ? data.index : data.index;
        paletteGroups[gi].colors.splice(removeIdx, 1);
      }
      selColor = { group: gi, index: paletteGroups[gi].colors.length - 1 };
      renderPalette(); savePalette();
    });

    group.colors.forEach((col, ci) => {
      const s = document.createElement('div');
      s.className = 'swatch' + (selEq(selColor, {group: gi, index: ci}) ? ' selected' : '');
      s.style.background = col;
      s.title = col;
      s.draggable = true;
      s.onclick = () => { selColor = {group: gi, index: ci}; renderPalette(); };
      s.addEventListener('mouseenter', () => { document.getElementById('color-hover').textContent = col; });
      s.addEventListener('mouseleave', () => { document.getElementById('color-hover').textContent = ''; });
      s.addEventListener('dragstart', e => {
        s.classList.add('dragging');
        e.dataTransfer.setData('text/plain', JSON.stringify({group: gi, index: ci}));
      });
      s.addEventListener('dragend', () => s.classList.remove('dragging'));
      swatchRow.appendChild(s);
    });

    groupEl.appendChild(header);
    groupEl.appendChild(swatchRow);
    container.appendChild(groupEl);
  });
}

function refreshGroupSelect() {
  const sel = document.getElementById('group-target-select');
  const prev = sel.value;
  sel.innerHTML = '';
  paletteGroups.forEach((g, i) => {
    const opt = document.createElement('option');
    opt.value = i; opt.textContent = g.name || `Group ${i+1}`;
    sel.appendChild(opt);
  });
  if (prev !== '' && prev < paletteGroups.length) sel.value = prev;
}

function addGroup() {
  paletteGroups.push({ name: 'Group ' + (paletteGroups.length + 1), colors: [] });
  renderPalette(); savePalette(); refreshGroupSelect();
}

function hexToRgba(hex) {
  const h = hex.replace('#', '');
  if (!/^[0-9a-fA-F]{6}$/.test(h)) return null;
  const n = parseInt(h, 16);
  return [(n>>16)&0xff, (n>>8)&0xff, n&0xff, 255];
}

async function savePalette() {
  await fetch('/api/palette', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(paletteGroups),
  });
}

async function loadPalette() {
  const res = await fetch('/api/palette');
  const data = await res.json();
  if (!data.length) return;
  // backwards compat: flat array of hex strings → single default group
  if (typeof data[0] === 'string') {
    paletteGroups = [{ name: 'Default', colors: data }];
  } else {
    paletteGroups = data;
  }
  selColor = paletteGroups[0]?.colors.length ? { group: 0, index: 0 } : null;
  renderPalette();
  refreshGroupSelect();
}

function addColor() {
  const raw = document.getElementById('hex-input').value.trim();
  const hex = raw.startsWith('#') ? raw.toLowerCase() : '#' + raw.toLowerCase();
  if (!/^#[0-9a-f]{6}$/.test(hex)) { alert('Invalid hex — use #rrggbb'); return; }
  if (!paletteGroups.length) paletteGroups.push({ name: 'Default', colors: [] });
  const gi = parseInt(document.getElementById('group-target-select').value) || 0;
  paletteGroups[gi].colors.push(hex);
  selColor = { group: gi, index: paletteGroups[gi].colors.length - 1 };
  renderPalette(); savePalette(); refreshGroupSelect();
  document.getElementById('hex-input').value = '';
  document.getElementById('hex-preview').style.background = '';
}

function removeColor() {
  if (!selColor || selColor === 'transparent' || typeof selColor !== 'object') return;
  const g = paletteGroups[selColor.group];
  if (!g) return;
  g.colors.splice(selColor.index, 1);
  selColor = g.colors.length ? { group: selColor.group, index: Math.min(selColor.index, g.colors.length - 1) } : null;
  renderPalette(); savePalette();
}

function selectTransparent() {
  selColor = 'transparent';
  renderPalette();
}

document.getElementById('hex-input').addEventListener('input', function () {
  const raw = this.value.trim();
  const hex = raw.startsWith('#') ? raw : '#' + raw;
  document.getElementById('hex-preview').style.background =
    /^#[0-9a-fA-F]{6}$/.test(hex) ? hex : '';
});

document.getElementById('hex-input').addEventListener('keydown', function (e) {
  if (e.key === 'Enter') addColor();
});

// ── tools ──────────────────────────────────────────────────────────────────────
function setTool(t) {
  tool = t;
  ['draw','erase','fill'].forEach(id =>
    document.getElementById('tool-' + id).classList.toggle('active', id === t)
  );
}

function currentFill() {
  if (selColor === 'transparent') return null;
  if (selColor && typeof selColor === 'object') {
    const hex = paletteGroups[selColor.group]?.colors[selColor.index];
    return hex ? hexToRgba(hex) : null;
  }
  return null;
}

// flat list of all colors across groups for Ctrl+[/] cycling
function allColors() {
  return paletteGroups.flatMap((g, gi) => g.colors.map((_, ci) => ({ group: gi, index: ci })));
}

function paintAt(x, y) {
  if (tool === 'fill') {
    if (x >= 0 && y >= 0 && x < canvasW && y < canvasH) floodFill(x, y);
    render();
    return;
  }
  const fill = (tool === 'erase' || selColor === 'transparent') ? null : currentFill();
  if (tool === 'draw' && !fill) return;
  for (let dy = 0; dy < brushSize; dy++) {
    for (let dx = 0; dx < brushSize; dx++) {
      const px = x + dx, py = y + dy;
      if (px >= 0 && py >= 0 && px < canvasW && py < canvasH) {
        pixels[py][px] = fill ? [...fill] : null;
      }
    }
  }
  render();
}

function setBrush(size) {
  brushSize = size;
  [1, 2, 4].forEach(s =>
    document.getElementById('brush-' + s).classList.toggle('active', s === size)
  );
}

function sameColor(a, b) {
  if (a === null && b === null) return true;
  if (a === null || b === null) return false;
  return a[0]===b[0] && a[1]===b[1] && a[2]===b[2] && a[3]===b[3];
}

function floodFill(sx, sy) {
  const target = pixels[sy][sx];
  const fill   = currentFill();
  if (sameColor(target, fill)) return;
  const queue   = [[sx, sy]];
  const visited = new Set();
  while (queue.length) {
    const [x, y] = queue.shift();
    if (x<0||y<0||x>=canvasW||y>=canvasH) continue;
    const key = y * canvasW + x;
    if (visited.has(key) || !sameColor(pixels[y][x], target)) continue;
    visited.add(key);
    pixels[y][x] = fill ? [...fill] : null;
    queue.push([x+1,y],[x-1,y],[x,y+1],[x,y-1]);
  }
}

// ── mouse ──────────────────────────────────────────────────────────────────────
function canvasPos(e) {
  const r = canvas.getBoundingClientRect();
  return [
    Math.floor((e.clientX - r.left)  / zoom),
    Math.floor((e.clientY - r.top) / zoom),
  ];
}

canvas.addEventListener('mousedown', e => {
  e.preventDefault();
  if (e.button === 2) {
    pushHistory();
    const [x, y] = canvasPos(e);
    for (let dy = 0; dy < brushSize; dy++)
      for (let dx = 0; dx < brushSize; dx++) {
        const px = x + dx, py = y + dy;
        if (px >= 0 && py >= 0 && px < canvasW && py < canvasH) pixels[py][px] = null;
      }
    render();
    return;
  }
  pushHistory();
  painting = true;
  const [x, y] = canvasPos(e);
  paintAt(x, y);
  if (tool === 'fill') painting = false;
});
canvas.addEventListener('mousemove', e => {
  if (e.buttons === 2) {
    const [x, y] = canvasPos(e);
    for (let dy = 0; dy < brushSize; dy++)
      for (let dx = 0; dx < brushSize; dx++) {
        const px = x + dx, py = y + dy;
        if (px >= 0 && py >= 0 && px < canvasW && py < canvasH) pixels[py][px] = null;
      }
    render();
    return;
  }
  if (!painting) return;
  paintAt(...canvasPos(e));
});
canvas.addEventListener('mouseup',    () => { painting = false; });
canvas.addEventListener('mouseleave', () => { painting = false; });
canvas.addEventListener('contextmenu', e => e.preventDefault());

// ── history ────────────────────────────────────────────────────────────────────
function pushHistory() {
  history.push(pixels.map(row => row.map(px => px ? [...px] : null)));
  if (history.length > 64) history.shift();
}

function undo() {
  if (!history.length) return;
  pixels = history.pop();
  render();
}

// ── zoom & grid ────────────────────────────────────────────────────────────────
function setZoom(z) {
  zoom = z;
  checkerPat = null;
  resizeCanvas();
  render();
}

function toggleGrid() {
  gridOn = !gridOn;
  document.getElementById('btn-grid').classList.toggle('active', gridOn);
  renderGrid();
}

// ── new size selector ──────────────────────────────────────────────────────────
function setNewSize(s) {
  newSize = s;
  document.getElementById('btn-8').classList.toggle('active',  s === 8);
  document.getElementById('btn-32').classList.toggle('active', s === 32);
}

// ── sprite browser ─────────────────────────────────────────────────────────────
async function refreshSprites() {
  const res   = await fetch('/api/sprites');
  const names = await res.json();
  const list  = document.getElementById('sprite-list');
  list.innerHTML = '';
  if (!names.length) {
    list.innerHTML = '<span style="color:#444;font-size:11px">none yet</span>';
    return;
  }
  names.forEach(name => {
    const el = document.createElement('div');
    el.className = 'sprite-item' + (name === currentSprite ? ' active' : '');
    el.textContent = name;
    el.onclick = () => loadSprite(name);
    list.appendChild(el);
  });
}

async function loadSprite(name) {
  const res = await fetch('/api/sprites/' + encodeURIComponent(name));
  if (!res.ok) { alert('Failed to load ' + name); return; }
  const data = await res.json();
  canvasW = data.width;
  canvasH = data.height;
  pixels  = data.pixels;
  currentSprite = name;
  history = [];
  resizeCanvas();
  render();
  refreshSprites();
  setStatus(name + '  ' + canvasW + '×' + canvasH);
}

function duplicateSprite() {
  if (!currentSprite) { alert('No sprite loaded to duplicate'); return; }
  const name = document.getElementById('new-name').value.trim();
  if (!name) { alert('Enter a name for the duplicate'); return; }
  // deep copy current pixels into a new sprite with the given name
  pixels = pixels.map(row => row.map(px => px ? [...px] : null));
  currentSprite = name;
  history = [];
  refreshSprites();
  setStatus(name + '  ' + canvasW + '×' + canvasH + '  (unsaved)');
}

function newSprite() {
  const name = document.getElementById('new-name').value.trim();
  if (!name) { alert('Enter a sprite name'); return; }
  initPixels(newSize, newSize);
  currentSprite = name;
  history = [];
  resizeCanvas();
  render();
  refreshSprites();
  setStatus(name + '  ' + newSize + '×' + newSize + '  (unsaved)');
}

async function saveSprite() {
  if (!currentSprite) { alert('No sprite loaded'); return; }
  const res = await fetch('/api/sprites/' + encodeURIComponent(currentSprite), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ width: canvasW, height: canvasH, pixels }),
  });
  if (res.ok) {
    setStatus(currentSprite + '  ' + canvasW + '×' + canvasH + '  — saved ✓');
    refreshSprites();
  } else {
    alert('Save failed');
  }
}

function setStatus(msg) {
  document.getElementById('status').textContent = msg;
}

// ── keyboard shortcuts ─────────────────────────────────────────────────────────
document.addEventListener('keydown', e => {
  const typing = document.activeElement.tagName === 'INPUT';
  if ((e.ctrlKey || e.metaKey) && e.key === 'z') { e.preventDefault(); undo(); }
  if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); saveSprite(); }
  if ((e.ctrlKey || e.metaKey) && e.key === 'n') { e.preventDefault(); document.getElementById('new-name').focus(); }
  if ((e.ctrlKey || e.metaKey) && e.key === '[') {
    e.preventDefault();
    const all = allColors();
    if (all.length) {
      const cur = all.findIndex(c => selEq(c, selColor));
      selColor = all[(cur <= 0 ? all.length : cur) - 1];
      renderPalette();
    }
  }
  if ((e.ctrlKey || e.metaKey) && e.key === ']') {
    e.preventDefault();
    const all = allColors();
    if (all.length) {
      const cur = all.findIndex(c => selEq(c, selColor));
      selColor = all[(cur + 1) % all.length];
      renderPalette();
    }
  }
  if (typing) return;
  if (e.key === 'd') setTool('draw');
  if (e.key === 'e') setTool('erase');
  if (e.key === 'f') setTool('fill');
  if (e.key === 'g') toggleGrid();
  if (e.key === '1') setBrush(1);
  if (e.key === '2') setBrush(2);
  if (e.key === '4') setBrush(4);
  if (e.key === 'm') applyEraseMask();
});

// ── mask erase ─────────────────────────────────────────────────────────────────
let eraseMask = null; // null pixels from h_cond_empty_0

async function loadEraseMask() {
  const res = await fetch('/api/sprites/h_cond_0');
  if (!res.ok) return;
  const data = await res.json();
  // store which (x,y) positions are transparent in the mask
  eraseMask = [];
  for (let y = 0; y < data.height; y++)
    for (let x = 0; x < data.width; x++)
      if (!data.pixels[y][x] || data.pixels[y][x][3] === 0)
        eraseMask.push([x, y]);
}

function applyEraseMask() {
  if (!eraseMask) { alert('Mask not loaded'); return; }
  pushHistory();
  for (const [x, y] of eraseMask)
    if (y < canvasH && x < canvasW) pixels[y][x] = null;
  render();
}

// ── boot ───────────────────────────────────────────────────────────────────────
initPixels(8, 8);
resizeCanvas();
render();
renderPalette();
refreshGroupSelect();
refreshSprites();
loadPalette();
loadEraseMask();
</script>
</body>
</html>
"""


# ── HTTP server ────────────────────────────────────────────────────────────────


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # silence request logs

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/":
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path == "/api/palette":
            fpath = os.path.join(ASSETS_DIR, "palette.json")
            if os.path.exists(fpath):
                with open(fpath) as f:
                    self.send_json(json.load(f))
            else:
                self.send_json([])

        elif path == "/api/sprites":
            if os.path.isdir(ASSETS_DIR):
                names = sorted(
                    f[:-4] for f in os.listdir(ASSETS_DIR) if f.endswith(".png")
                )
            else:
                names = []
            self.send_json(names)

        elif path.startswith("/api/sprites/"):
            name = path[len("/api/sprites/") :]
            fpath = os.path.join(ASSETS_DIR, name + ".png")
            if not os.path.exists(fpath):
                self.send_json({"error": "not found"}, 404)
                return
            try:
                with open(fpath, "rb") as f:
                    pxs, w, h = png_decode(f.read())
                self.send_json({"width": w, "height": h, "pixels": pxs})
            except Exception as ex:
                self.send_json({"error": str(ex)}, 500)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/palette":
            length = int(self.headers.get("Content-Length", 0))
            colors = json.loads(self.rfile.read(length))
            os.makedirs(ASSETS_DIR, exist_ok=True)
            with open(os.path.join(ASSETS_DIR, "palette.json"), "w") as f:
                json.dump(colors, f)
            self.send_json({"ok": True})

        elif path.startswith("/api/sprites/"):
            name = path[len("/api/sprites/") :]
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            pxs = body["pixels"]
            # null → fully transparent [0,0,0,0]
            norm = [[(px if px else [0, 0, 0, 0]) for px in row] for row in pxs]
            os.makedirs(ASSETS_DIR, exist_ok=True)
            fpath = os.path.join(ASSETS_DIR, name + ".png")
            with open(fpath, "wb") as f:
                f.write(png_encode(norm))
            self.send_json({"ok": True})
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    os.makedirs(ASSETS_DIR, exist_ok=True)
    url = f"http://localhost:{PORT}"
    print(f"Sprite editor  →  {url}")
    print(f"Sprites dir    →  {os.path.abspath(ASSETS_DIR)}")
    print("Ctrl+C to stop")
    # webbrowser.open(url)
    HTTPServer(("localhost", PORT), Handler).serve_forever()
