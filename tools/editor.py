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
  font-family: 'Courier New', monospace; font-size: 14px;
  display: flex; height: 100vh; overflow: hidden;
}

/* ── panels ── */
#panel-left {
  width: 360px; min-width: 360px;
  background: #101014; border-right: 1px solid #2a2a35;
  display: flex; flex-direction: column; padding: 8px; gap: 8px; overflow: hidden;
}
#panel-right {
  width: 400px; min-width: 400px;
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
  color: #555; font-size: 12px; letter-spacing: 1px; text-transform: uppercase;
  border-bottom: 1px solid #252530; padding-bottom: 3px; margin-bottom: 2px;
}

/* ── controls ── */
button {
  background: #202030; color: #a8a8c0; border: 1px solid #333348;
  padding: 3px 8px; cursor: pointer; font-family: inherit; font-size: 13px;
}
button:hover { background: #2a2a42; color: #c8c8e0; }
button.active { background: #2a2a58; border-color: #5858a8; color: #d0d0ff; }
button.danger { border-color: #582020; }
button.danger:hover { background: #381818; }
.row { display: flex; gap: 4px; }
.row button { flex: 1; }

input[type=text] {
  background: #18181f; color: #b8b8d0; border: 1px solid #333348;
  padding: 3px 6px; font-family: inherit; font-size: 13px; width: 100%;
}
input[type=text]:focus { outline: none; border-color: #5858a8; }

select {
  background: #202030; color: #b8b8d0; border: 1px solid #333348;
  font-family: inherit; font-size: 13px; padding: 2px 4px;
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

/* ── tabs ── */
#tab-bar {
  display: flex; align-items: flex-end; border-bottom: 1px solid #2a2a3a;
  min-height: 26px; width: 100%; overflow-x: auto; flex-shrink: 0; gap: 2px; padding: 0 4px;
}
.tab {
  padding: 3px 8px; cursor: pointer; border: 1px solid transparent; border-bottom: none;
  font-size: 13px; color: #555; white-space: nowrap; background: #151518;
  display: flex; align-items: center; gap: 5px; border-radius: 2px 2px 0 0;
  max-width: 160px;
}
.tab:hover { color: #aaa; background: #1a1a22; }
.tab.active { color: #c8c8d0; background: #1a1a22; border-color: #2a2a3a; }
.tab-label { overflow: hidden; text-overflow: ellipsis; }
.tab-dirty { color: #8888ff; font-size: 11px; flex-shrink: 0; }
.tab-close { color: #333; font-size: 12px; cursor: pointer; flex-shrink: 0; }
.tab-close:hover { color: #cc4444; }

/* ── canvas ── */
#canvas-wrap { position: relative; border: 1px solid #2a2a3a; }
canvas { display: block; image-rendering: pixelated; image-rendering: crisp-edges; }
#overlay-canvas { position: absolute; top: 0; left: 0; pointer-events: none; }

/* ── palette ── */
#palette-groups { display: flex; flex-direction: column; gap: 8px; }
.pal-group { display: flex; flex-direction: column; gap: 3px; }
.pal-group-header {
  display: flex; align-items: center; gap: 4px;
  color: #555; font-size: 12px; letter-spacing: 1px; text-transform: uppercase;
  border-bottom: 1px solid #252530; padding-bottom: 2px; cursor: default;
}
.pal-group-name {
  flex: 1; background: none; border: none; color: #555;
  font-family: inherit; font-size: 12px; letter-spacing: 1px; text-transform: uppercase;
  padding: 0; cursor: text; outline: none; min-width: 0; text-transform: uppercase;
}
.pal-group-name:focus { color: #b0b0d0; border-bottom: 1px solid #5858a8; }
.pal-group-del { cursor: pointer; color: #442222; font-size: 13px; padding: 0 2px; flex-shrink: 0; }
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
.swatch { position: relative; }
.swatch.unnamed { border-color: #883333; }
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
#hex-row { display: flex; gap: 4px; align-items: center; }
#hex-row input { flex: 1; }
#color-detail-hex-preview { width: 28px; height: 28px; border: 1px solid #333; flex-shrink: 0; border-radius: 2px; }

/* ── sprite props ── */
#sprite-props { display: flex; flex-direction: column; gap: 6px; border-top: 1px solid #252530; padding-top: 8px; margin-top: 4px; flex-shrink: 0; }
#size-btns button { flex: 1; }
#size-btns button.active { background: #2a2a58; border-color: #5858a8; color: #d0d0ff; }
#custom-size-row { display: none; gap: 4px; align-items: center; }
#custom-size-row input { width: 0; flex: 1; }
.prop-label { color: #555; font-size: 12px; margin-bottom: 2px; }

/* ── color detail ── */
#color-detail {
  flex-shrink: 0; border-top: 1px solid #252530; padding-top: 8px; margin-top: 4px;
  display: none; flex-direction: column; gap: 5px;
}
#color-detail.visible { display: flex; }

#status { color: #484860; font-size: 13px; }
</style>
</head>
<body>

<!-- ── LEFT PANEL ── -->
<div id="panel-left">
  <div class="section-title">Sprites</div>
  <div id="sprite-list-wrap">
    <div id="sprite-list"></div>
  </div>

  <div id="sprite-props">
    <div class="section-title" id="props-title">New Sprite</div>

    <div>
      <div class="prop-label">Size</div>
      <div class="row" id="size-btns">
        <button id="sz-8"   onclick="selectSize(8,8)">8</button>
        <button id="sz-32"  onclick="selectSize(32,32)" class="active">32</button>
        <button id="sz-64"  onclick="selectSize(64,64)">64</button>
        <button id="sz-cust" onclick="selectSize('custom')">…</button>
      </div>
      <div id="custom-size-row" class="row" style="margin-top:4px">
        <input type="number" id="custom-w" placeholder="W" min="1" max="512" />
        <span style="color:#555;flex-shrink:0">×</span>
        <input type="number" id="custom-h" placeholder="H" min="1" max="512" />
      </div>
    </div>

    <div id="prop-name-row">
      <div class="prop-label">Name</div>
      <input type="text" id="prop-name" placeholder="sprite_name" />
    </div>

    <div id="prop-folder-row">
      <div class="prop-label">Folder</div>
      <select id="prop-folder" style="width:100%"></select>
    </div>

    <div class="row" style="margin-top:2px">
      <button onclick="saveSprite()">Save  [Ctrl+S]</button>
      <button id="btn-duplicate" onclick="duplicateSprite()">Duplicate</button>
    </div>
    <button onclick="newSprite()">New blank</button>
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

  <div id="tab-bar"></div>
  <div id="canvas-wrap">
    <canvas id="pixel-canvas"></canvas>
    <canvas id="overlay-canvas"></canvas>
  </div>

  <div id="status">no sprite loaded</div>
</div>

<!-- ── RIGHT PANEL: palette ── -->
<div id="panel-right">
  <!-- toolbar -->
  <div class="row" style="flex-shrink:0">
    <button onclick="newColorForm()">+ Color</button>
    <button onclick="addGroup()">+ Group</button>
  </div>

  <!-- transparent swatch -->
  <div style="flex-shrink:0;display:flex;align-items:center;gap:6px">
    <div class="swatch transparent" id="swatch-transparent"
         onclick="selectTransparent()"
         title="transparent"></div>
    <span style="color:#555;font-size:12px">transparent</span>
  </div>

  <!-- scrollable groups -->
  <div style="flex:1;overflow-y:auto;min-height:0">
    <div id="palette-groups"></div>
  </div>

  <!-- color detail (shown when a color is selected) -->
  <div id="color-detail">
    <div class="section-title" id="color-detail-title">Color</div>
    <div id="hex-row">
      <input type="text" id="hex-input" placeholder="#rrggbb" maxlength="7" />
      <div id="color-detail-hex-preview"></div>
    </div>
    <input type="text" id="name-input" placeholder="name (required)" style="text-transform:uppercase" />
    <div class="row">
      <button id="btn-color-confirm" onclick="confirmColorDetail()">Add</button>
      <button id="btn-color-refactor" onclick="refactorSelectedColor()" style="display:none">Refactor</button>
      <button id="btn-color-remove" class="danger" onclick="removeColor()" style="display:none">Remove</button>
    </div>
  </div>
</div>

<script>
// ── state ──────────────────────────────────────────────────────────────────────
let canvasW = 8, canvasH = 8;
let pixels  = [];       // [y][x] = [r,g,b,a] or null
// paletteGroups: [{name, colors: [{hex, name}, ...]}, ...]
let paletteGroups = [];
// selColor: {group, index} | 'transparent' | null
let selColor = null;
let tool     = 'draw';
let brushSize = 1;
let zoom     = 16;
const ZOOM_STEPS = [1, 2, 4, 8, 16, 32];
let gridOn   = true;
let history  = [];      // array of pixel snapshots
let painting = false;
let newW = 32, newH = 32; // size for next new sprite
let currentSprite = null;

// ── tabs ───────────────────────────────────────────────────────────────────────
// each tab: { name, pixels, canvasW, canvasH, history, dirty }
let tabs = [];
let activeTab = -1;

function saveCurrentTab() {
  if (activeTab < 0 || activeTab >= tabs.length) return;
  const t = tabs[activeTab];
  t.name = currentSprite; t.pixels = pixels;
  t.canvasW = canvasW; t.canvasH = canvasH; t.history = history;
}

function restoreTab(idx) {
  const t = tabs[idx];
  currentSprite = t.name; pixels = t.pixels;
  canvasW = t.canvasW; canvasH = t.canvasH; history = t.history;
  activeTab = idx;
}

function openTab(tabData) {
  const existing = tabs.findIndex(t => t.name && t.name === tabData.name);
  if (existing >= 0) { switchTab(existing); return; }
  saveCurrentTab();
  tabs.push(tabData);
  restoreTab(tabs.length - 1);
  resizeCanvas(); render(); renderTabs(); renderSpriteProps();
  setStatus((currentSprite || 'unsaved') + '  ' + canvasW + '×' + canvasH);
}

function updateSpriteListActive() {
  document.querySelectorAll('#sprite-list .sprite-item').forEach(el => {
    el.classList.toggle('active', el.title === currentSprite);
  });
}

function switchTab(idx) {
  if (idx < 0 || idx >= tabs.length) return;
  saveCurrentTab();
  restoreTab(idx);
  resizeCanvas(); render(); renderTabs(); renderSpriteProps();
  updateSpriteListActive();
  setStatus(currentSprite ? currentSprite + '  ' + canvasW + '×' + canvasH : 'no sprite loaded');
}

function closeTab(idx) {
  tabs.splice(idx, 1);
  if (tabs.length === 0) {
    activeTab = -1; currentSprite = null;
    initPixels(8, 8); history = [];
    resizeCanvas(); render(); setStatus('no sprite loaded');
  } else {
    const next = Math.min(idx, tabs.length - 1);
    restoreTab(next);
    resizeCanvas(); render();
    setStatus(currentSprite + '  ' + canvasW + '×' + canvasH);
  }
  renderTabs();
}

function refreshFolderDropdown(selectValue) {
  const sel = document.getElementById('prop-folder');
  const current = selectValue !== undefined ? selectValue : sel.value;
  const allFolders = [...new Set([
    ...(window._spriteFolders || []),
    ...tabs.map(t => { if (!t.name) return ''; const s = t.name.lastIndexOf('/'); return s >= 0 ? t.name.slice(0, s) : ''; })
  ])].filter(f => f).sort();
  sel.innerHTML = '<option value="">(root)</option>';
  allFolders.forEach(f => {
    const opt = document.createElement('option');
    opt.value = f; opt.textContent = f;
    sel.appendChild(opt);
  });
  sel.value = current;
}

function renderSpriteProps() {
  const name = currentSprite || '';
  const slash = name.lastIndexOf('/');
  const base   = slash >= 0 ? name.slice(slash + 1) : name;
  const folder = slash >= 0 ? name.slice(0, slash) : '';
  const isDirty = activeTab >= 0 && tabs[activeTab].dirty;

  document.getElementById('props-title').textContent = name ? 'Sprite' : 'New Sprite';
  document.getElementById('prop-name').value = base;

  // populate folder dropdown (preserves current selection if already set)
  refreshFolderDropdown(folder);

  // size buttons — reflect current canvas
  ['8','32','64'].forEach(s => {
    const btn = document.getElementById('sz-' + s);
    btn.classList.toggle('active', parseInt(s) === canvasW && canvasW === canvasH);
  });

  // duplicate disabled if unsaved
  document.getElementById('btn-duplicate').disabled = !currentSprite || isDirty;
}

function renderTabs() {
  const bar = document.getElementById('tab-bar');
  bar.innerHTML = '';
  tabs.forEach((t, i) => {
    const tab = document.createElement('div');
    tab.className = 'tab' + (i === activeTab ? ' active' : '');
    const label = document.createElement('span');
    label.className = 'tab-label';
    const base = t.name ? t.name.split('/').pop() : 'untitled';
    label.textContent = base;
    label.title = t.name || 'untitled';
    const dirty = document.createElement('span');
    dirty.className = 'tab-dirty';
    dirty.textContent = t.dirty ? '●' : '';
    const close = document.createElement('span');
    close.className = 'tab-close';
    close.textContent = '✕';
    close.onclick = e => { e.stopPropagation(); closeTab(i); };
    tab.appendChild(label);
    tab.appendChild(dirty);
    tab.appendChild(close);
    tab.onclick = () => switchTab(i);
    bar.appendChild(tab);
  });
}

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
        const [r,g,b,a] = pixelRgba(px);
        ctx.fillStyle = `rgba(${r},${g},${b},${a/255})`;
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

function showColorDetail(gi, ci) {
  const entry = paletteGroups[gi]?.colors[ci];
  if (!entry) return;
  const hex  = typeof entry === 'string' ? entry : entry.hex;
  const name = typeof entry === 'object' ? (entry.name || '') : '';
  document.getElementById('color-detail-title').textContent = name || 'Color';
  document.getElementById('hex-input').value = hex;
  document.getElementById('color-detail-hex-preview').style.background = hex;
  document.getElementById('name-input').value = name;
  document.getElementById('btn-color-confirm').textContent = 'Update';
  document.getElementById('btn-color-refactor').style.display = '';
  document.getElementById('btn-color-remove').style.display = '';
  document.getElementById('color-detail').classList.add('visible');
}

function hideColorDetail() {
  document.getElementById('color-detail').classList.remove('visible');
}

function newColorForm() {
  selColor = null;
  renderPalette();
  document.getElementById('color-detail-title').textContent = 'New Color';
  document.getElementById('hex-input').value = '';
  document.getElementById('color-detail-hex-preview').style.background = '';
  document.getElementById('name-input').value = '';
  document.getElementById('btn-color-confirm').textContent = 'Add';
  document.getElementById('btn-color-refactor').style.display = 'none';
  document.getElementById('btn-color-remove').style.display = 'none';
  document.getElementById('color-detail').classList.add('visible');
  document.getElementById('hex-input').focus();
}

function confirmColorDetail() {
  if (selColor && typeof selColor === 'object') updateSelectedColor();
  else addColor();
}

function updateSelectedColor() {
  if (!selColor || selColor === 'transparent' || typeof selColor !== 'object') return;
  const raw = document.getElementById('hex-input').value.trim();
  const hex = raw.startsWith('#') ? raw.toLowerCase() : '#' + raw.toLowerCase();
  if (!/^#[0-9a-f]{6}$/.test(hex)) { alert('Invalid hex'); return; }
  const name = document.getElementById('name-input').value.trim().toUpperCase();
  if (!name) { alert('A name is required'); return; }
  const entry = paletteGroups[selColor.group]?.colors[selColor.index];
  if (!entry) return;
  entry.hex = hex; entry.name = name;
  renderPalette(); savePalette();
}

async function refactorSelectedColor() {
  if (!selColor || selColor === 'transparent' || typeof selColor !== 'object') return;
  const entry = paletteGroups[selColor.group]?.colors[selColor.index];
  if (!entry || !entry.name) { alert('Color must have a name to refactor'); return; }
  const res = await fetch('/api/reexport', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: entry.name }),
  });
  const data = await res.json();
  setStatus(`Refactored "${entry.name}" — ${data.updated} sprite(s) updated`);
}

function renderPalette() {
  // transparent swatch
  const ts = document.getElementById('swatch-transparent');
  ts.classList.toggle('selected', selColor === 'transparent');

  // groups
  const container = document.getElementById('palette-groups');
  container.innerHTML = '';

  paletteGroups.forEach((group, gi) => {
    const isNoGroup = group._noGroup === true;
    const groupEl = document.createElement('div');
    groupEl.className = 'pal-group';

    // header (skip for no-group)
    const header = document.createElement('div');
    header.className = 'pal-group-header';
    if (isNoGroup) {
      header.style.cssText = 'color:#333;font-size:11px;padding-bottom:2px;border-bottom:1px solid #1e1e28';
      header.textContent = 'no group';
    } else {
      const nameInput = document.createElement('input');
      nameInput.type = 'text';
      nameInput.className = 'pal-group-name';
      nameInput.value = group.name;
      nameInput.onchange = () => { group.name = nameInput.value; savePalette(); };

      const delBtn = document.createElement('span');
      delBtn.className = 'pal-group-del';
      delBtn.textContent = '✕';
      delBtn.title = 'Delete group';
      delBtn.onclick = () => { paletteGroups.splice(gi, 1); renderPalette(); savePalette(); };

      header.appendChild(nameInput);
      header.appendChild(delBtn);
    }

    // swatches container (drop target)
    const swatchRow = document.createElement('div');
    swatchRow.className = 'pal-swatches';
    swatchRow.dataset.group = gi;

    // find insertion index based on mouse position within the swatch row
    function dropIndex(e) {
      const swatches = [...swatchRow.querySelectorAll('.swatch')];
      for (let i = 0; i < swatches.length; i++) {
        const r = swatches[i].getBoundingClientRect();
        if (e.clientX < r.left + r.width / 2) return i;
      }
      return swatches.length;
    }

    function clearInsertMarker() {
      swatchRow.querySelectorAll('.insert-marker').forEach(m => m.remove());
    }

    function showInsertMarker(idx) {
      clearInsertMarker();
      const swatches = [...swatchRow.querySelectorAll('.swatch')];
      const marker = document.createElement('div');
      marker.className = 'insert-marker';
      marker.style.cssText = 'width:2px;height:22px;background:#8888ff;flex-shrink:0;border-radius:1px;pointer-events:none';
      if (idx < swatches.length) swatchRow.insertBefore(marker, swatches[idx]);
      else swatchRow.appendChild(marker);
    }

    swatchRow.addEventListener('dragover', e => {
      e.preventDefault();
      swatchRow.classList.add('drag-over');
      showInsertMarker(dropIndex(e));
    });
    swatchRow.addEventListener('dragleave', e => {
      if (!swatchRow.contains(e.relatedTarget)) {
        swatchRow.classList.remove('drag-over');
        clearInsertMarker();
      }
    });
    swatchRow.addEventListener('drop', e => {
      e.preventDefault();
      swatchRow.classList.remove('drag-over');
      clearInsertMarker();
      const data = JSON.parse(e.dataTransfer.getData('text/plain'));
      const color = paletteGroups[data.group].colors[data.index];
      let insertAt = dropIndex(e);

      if (data.group === gi) {
        // reorder within same group
        paletteGroups[gi].colors.splice(data.index, 1);
        if (insertAt > data.index) insertAt--;
        paletteGroups[gi].colors.splice(insertAt, 0, color);
      } else {
        // copy into target group at position
        paletteGroups[gi].colors.splice(insertAt, 0, color);
      }
      selColor = { group: gi, index: insertAt };
      renderPalette(); savePalette();
    });

    group.colors.forEach((entry, ci) => {
      const hex  = typeof entry === 'string' ? entry : entry.hex;
      const name = typeof entry === 'object' && entry.name ? entry.name : '';
      const s = document.createElement('div');
      s.className = 'swatch'
        + (selEq(selColor, {group: gi, index: ci}) ? ' selected' : '')
        + (name ? '' : ' unnamed');
      s.style.background = hex;
      s.title = name ? `${hex}  (${name})` : hex;
      s.draggable = true;
      s.onclick = () => {
        selColor = {group: gi, index: ci};
        renderPalette();
        showColorDetail(gi, ci);
      };
      s.addEventListener('mouseenter', () => { document.getElementById('color-hover').textContent = name ? `${hex} · ${name}` : hex; });
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

function ensureNoGroup() {
  if (!paletteGroups.length || paletteGroups[0]._noGroup !== true) {
    paletteGroups.unshift({ name: '', colors: [], _noGroup: true });
  }
}

function addGroup() {
  ensureNoGroup();
  paletteGroups.push({ name: 'Group ' + paletteGroups.length, colors: [] });
  renderPalette(); savePalette();
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
  // backwards compat: flat array of hex strings → no-group
  if (typeof data[0] === 'string') {
    paletteGroups = [{ name: '', colors: data.map(h => ({ hex: h, name: '' })), _noGroup: true }];
  } else {
    paletteGroups = data.map((g, i) => ({
      ...g,
      _noGroup: g._noGroup || i === 0 && !g.name,
      colors: g.colors.map(c => typeof c === 'string' ? { hex: c, name: '' } : c)
    }));
    ensureNoGroup();
  }
  selColor = paletteGroups[0]?.colors.length ? { group: 0, index: 0 } : null;
  renderPalette();
}

function addColor() {
  const raw  = document.getElementById('hex-input').value.trim();
  const hex  = raw.startsWith('#') ? raw.toLowerCase() : '#' + raw.toLowerCase();
  const name = document.getElementById('name-input').value.trim().toUpperCase();
  if (!/^#[0-9a-f]{6}$/.test(hex)) { alert('Invalid hex — use #rrggbb'); return; }
  if (!name) { alert('A name is required'); document.getElementById('name-input').focus(); return; }
  ensureNoGroup();
  // always add to no-group (index 0)
  paletteGroups[0].colors.push({ hex, name });
  selColor = { group: 0, index: paletteGroups[0].colors.length - 1 };
  renderPalette(); savePalette();
  showColorDetail(0, selColor.index);
  document.getElementById('hex-input').value = '';
  document.getElementById('name-input').value = '';
}

function removeColor() {
  if (!selColor || selColor === 'transparent' || typeof selColor !== 'object') return;
  const g = paletteGroups[selColor.group];
  if (!g) return;
  g.colors.splice(selColor.index, 1);
  selColor = g.colors.length ? { group: selColor.group, index: Math.min(selColor.index, g.colors.length - 1) } : null;
  hideColorDetail();
  renderPalette(); savePalette();
}

function setColorName(nameVal) {
  if (!selColor || selColor === 'transparent' || typeof selColor !== 'object') return;
  const entry = paletteGroups[selColor.group]?.colors[selColor.index];
  if (!entry) return;
  entry.name = nameVal.trim().toUpperCase();
  renderPalette(); savePalette();
}

function selectTransparent() {
  selColor = 'transparent';
  hideColorDetail();
  renderPalette();
}

document.getElementById('hex-input').addEventListener('input', function () {
  const raw = this.value.trim().replace(/^#/, '');
  const preview = document.getElementById('color-detail-hex-preview');
  if (/^[0-9a-fA-F]{6}$/.test(raw)) {
    preview.style.background = '#' + raw;
    preview.style.opacity = '1';
  } else if (/^[0-9a-fA-F]{3}$/.test(raw)) {
    // expand shorthand: abc → aabbcc
    const expanded = raw.split('').map(c => c + c).join('');
    preview.style.background = '#' + expanded;
    preview.style.opacity = '0.6';
  } else {
    preview.style.background = '';
    preview.style.opacity = '1';
  }
});

document.getElementById('hex-input').addEventListener('keydown', function (e) {
  if (e.key === 'Enter') { e.preventDefault(); document.getElementById('name-input').focus(); }
});
document.getElementById('name-input').addEventListener('keydown', function (e) {
  if (e.key === 'Enter') {
    // if color-detail is visible, update selected; otherwise add new
    confirmColorDetail();
  }
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
    const entry = paletteGroups[selColor.group]?.colors[selColor.index];
    if (!entry) return null;
    const hex  = typeof entry === 'string' ? entry : entry.hex;
    const name = typeof entry === 'object' ? entry.name : '';
    const rgba = hexToRgba(hex);
    if (!rgba) return null;
    if (!name) {
      setStatus('⚠ color has no name — add one before painting');
      return null;
    }
    return { name, rgba };
  }
  return null;
}

function cloneFill(fill) {
  if (!fill) return null;
  if (Array.isArray(fill)) return [...fill];
  return { name: fill.name, rgba: [...fill.rgba] };
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
        pixels[py][px] = cloneFill(fill);
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

// pixels can be null, [r,g,b,a], or {name, rgba:[r,g,b,a]}
function pixelRgba(px) {
  if (!px) return null;
  return Array.isArray(px) ? px : px.rgba;
}

function sameColor(a, b) {
  const ra = pixelRgba(a), rb = pixelRgba(b);
  if (ra === null && rb === null) return true;
  if (ra === null || rb === null) return false;
  return ra[0]===rb[0] && ra[1]===rb[1] && ra[2]===rb[2] && ra[3]===rb[3];
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
    pixels[y][x] = cloneFill(fill);
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
  history.push(pixels.map(row => row.map(px => px ? (Array.isArray(px) ? [...px] : {name: px.name, rgba: [...px.rgba]}) : null)));
  if (history.length > 64) history.shift();
  if (activeTab >= 0) tabs[activeTab].dirty = true;
  renderTabs();
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

// ── size selector ─────────────────────────────────────────────────────────────
function selectSize(w, h) {
  const custom = w === 'custom';
  document.getElementById('custom-size-row').style.display = custom ? 'flex' : 'none';
  ['8','32','64','cust'].forEach(id =>
    document.getElementById('sz-' + id).classList.remove('active'));
  if (!custom) {
    newW = w; newH = h;
    document.getElementById('sz-' + w).classList.add('active');
    // if a sprite is loaded, offer resize
    if (currentSprite && (w !== canvasW || h !== canvasH)) {
      if (confirm(`Resize from ${canvasW}×${canvasH} to ${w}×${h}? Pixels outside the new bounds will be cropped.`)) {
        pushHistory();
        const newPixels = Array.from({length: h}, (_, y) =>
          Array.from({length: w}, (_, x) => (pixels[y] && pixels[y][x] !== undefined ? pixels[y][x] : null))
        );
        pixels = newPixels; canvasW = w; canvasH = h;
        if (activeTab >= 0) { tabs[activeTab].canvasW = w; tabs[activeTab].canvasH = h; }
        resizeCanvas(); render();
      }
    }
  } else {
    document.getElementById('sz-cust').classList.add('active');
  }
}

function getNewSize() {
  if (document.getElementById('sz-cust').classList.contains('active')) {
    const w = parseInt(document.getElementById('custom-w').value) || 0;
    const h = parseInt(document.getElementById('custom-h').value) || 0;
    if (!w || !h) { alert('Enter custom width and height'); return null; }
    return [w, h];
  }
  return [newW, newH];
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

  // group by folder (everything before the last '/')
  const folders = {};
  names.forEach(name => {
    const slash = name.lastIndexOf('/');
    const folder = slash >= 0 ? name.slice(0, slash) : '';
    const base   = slash >= 0 ? name.slice(slash + 1) : name;
    (folders[folder] = folders[folder] || []).push({ name, base });
  });
  window._spriteFolders = Object.keys(folders).filter(f => f);
  refreshFolderDropdown(); // update options, preserve current selection

  if (!window._collapsedFolders) window._collapsedFolders = new Set();
  const collapsedFolders = window._collapsedFolders;

  function renderList() {
    list.innerHTML = '';
    Object.entries(folders).sort(([a],[b]) => a.localeCompare(b)).forEach(([folder, items]) => {
      if (folder) {
        const hdr = document.createElement('div');
        const collapsed = collapsedFolders.has(folder);
        hdr.style.cssText = 'color:#555;font-size:10px;letter-spacing:1px;text-transform:uppercase;padding:4px 4px 2px;cursor:pointer;user-select:none;border-top:1px solid #1e1e28;margin-top:2px';
        hdr.textContent = (collapsed ? '▶ ' : '▼ ') + folder;
        hdr.onclick = () => {
          if (collapsed) collapsedFolders.delete(folder);
          else collapsedFolders.add(folder);
          renderList();
        };
        list.appendChild(hdr);
        if (collapsed) return;
      }
      items.forEach(({ name, base }) => {
        const el = document.createElement('div');
        el.className = 'sprite-item' + (name === currentSprite ? ' active' : '');
        el.style.paddingLeft = folder ? '14px' : '6px';
        el.textContent = base;
        el.title = name;
        el.onclick = () => loadSprite(name);
        list.appendChild(el);
      });
    });
  }
  renderList();
}

function spriteUrl(name) {
  return '/api/sprites/' + name.split('/').map(encodeURIComponent).join('/');
}

async function loadSprite(name) {
  // switch to existing tab if already open
  const existing = tabs.findIndex(t => t.name === name);
  if (existing >= 0) { switchTab(existing); refreshSprites(); return; }
  const res = await fetch(spriteUrl(name));
  if (!res.ok) { alert('Failed to load ' + name); return; }
  const data = await res.json();
  openTab({ name, pixels: data.pixels, canvasW: data.width, canvasH: data.height, history: [], dirty: false });
  refreshSprites();
}

function duplicateSprite() {
  if (!currentSprite) return;
  const prevFolder = document.getElementById('prop-folder').value;
  const copiedPixels = pixels.map(row => row.map(px => px ? (Array.isArray(px) ? [...px] : {name: px.name, rgba: [...px.rgba]}) : null));
  openTab({ name: null, pixels: copiedPixels, canvasW, canvasH, history: [], dirty: true });
  refreshSprites(); renderSpriteProps();
  document.getElementById('prop-name').value = '';
  document.getElementById('prop-folder').value = prevFolder;
}

function getPropPath() {
  const folder = document.getElementById('prop-folder').value.trim();
  const name   = document.getElementById('prop-name').value.trim();
  if (!name) return null;
  return folder ? folder + '/' + name : name;
}

function newSprite() {
  const sz = getNewSize(); if (!sz) return;
  const [w, h] = sz;
  const blankPixels = Array.from({length: h}, () => Array(w).fill(null));
  const prevFolder = document.getElementById('prop-folder').value;
  openTab({ name: null, pixels: blankPixels, canvasW: w, canvasH: h, history: [], dirty: true });
  refreshSprites(); renderSpriteProps();
  document.getElementById('prop-name').value = '';
  document.getElementById('prop-folder').value = prevFolder;
}

async function saveSprite() {
  const newPath = getPropPath();
  if (!newPath) { alert('Enter a sprite name'); document.getElementById('prop-name').focus(); return; }
  const oldPath = currentSprite;
  const body = { width: canvasW, height: canvasH, pixels };
  if (oldPath && oldPath !== newPath) body._from = oldPath;
  const res = await fetch(spriteUrl(newPath), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (res.ok) {
    currentSprite = newPath;
    if (activeTab >= 0) { tabs[activeTab].name = newPath; tabs[activeTab].dirty = false; }
    renderTabs(); renderSpriteProps();
    setStatus(newPath + '  ' + canvasW + '×' + canvasH + '  — saved ✓');
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
  if ((e.ctrlKey || e.metaKey) && e.key === 'n') { e.preventDefault(); document.getElementById('prop-name').focus(); }
  if ((e.ctrlKey || e.metaKey) && e.key === '[') {
    e.preventDefault();
    if (selColor && typeof selColor === 'object') {
      const g = paletteGroups[selColor.group];
      if (g) { selColor = {...selColor, index: (selColor.index <= 0 ? g.colors.length : selColor.index) - 1}; renderPalette(); showColorDetail(selColor.group, selColor.index); }
    }
  }
  if ((e.ctrlKey || e.metaKey) && e.key === ']') {
    e.preventDefault();
    if (selColor && typeof selColor === 'object') {
      const g = paletteGroups[selColor.group];
      if (g) { selColor = {...selColor, index: (selColor.index + 1) % g.colors.length}; renderPalette(); showColorDetail(selColor.group, selColor.index); }
    }
  }
  if ((e.ctrlKey || e.metaKey) && e.key === ',') {
    e.preventDefault();
    if (selColor && typeof selColor === 'object') {
      const g = paletteGroups[selColor.group];
      if (g) { selColor = {...selColor, index: (selColor.index <= 0 ? g.colors.length : selColor.index) - 1}; renderPalette(); }
    }
  }
  if ((e.ctrlKey || e.metaKey) && e.key === '.') {
    e.preventDefault();
    if (selColor && typeof selColor === 'object') {
      const g = paletteGroups[selColor.group];
      if (g) { selColor = {...selColor, index: (selColor.index + 1) % g.colors.length}; renderPalette(); }
    }
  }
  if ((e.ctrlKey || e.metaKey) && (e.key === '-' || e.key === '_')) {
    e.preventDefault();
    const i = ZOOM_STEPS.indexOf(zoom);
    if (i > 0) setZoom(ZOOM_STEPS[i - 1]);
  }
  if ((e.ctrlKey || e.metaKey) && (e.key === '=' || e.key === '+')) {
    e.preventDefault();
    const i = ZOOM_STEPS.indexOf(zoom);
    if (i < ZOOM_STEPS.length - 1) setZoom(ZOOM_STEPS[i + 1]);
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
  const res = await fetch('/api/sprites/machines/h_condenser/h_cond_0');
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
initPixels(32, 32);
tabs = [{ name: null, pixels, canvasW, canvasH, history: [], dirty: false }];
activeTab = 0;
resizeCanvas();
render();
renderTabs();
renderSpriteProps();
ensureNoGroup();
renderPalette();
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
                    os.path.relpath(os.path.join(root, f), ASSETS_DIR)[:-4].replace(os.sep, "/")
                    for root, _, files in os.walk(ASSETS_DIR)
                    for f in files
                    if f.endswith(".png") and not f.endswith(".src.json")
                )
            else:
                names = []
            self.send_json(names)

        elif path.startswith("/api/sprites/"):
            name = path[len("/api/sprites/") :]
            # name may contain path separators; normalise and prevent traversal
            name = os.path.normpath(name).lstrip("/\\")
            json_path = os.path.join(ASSETS_DIR, name + ".src.json")
            png_path  = os.path.join(ASSETS_DIR, name + ".png")
            # prefer .src.json (preserves named color references)
            if os.path.exists(json_path):
                try:
                    with open(json_path) as f:
                        self.send_json(json.load(f))
                except Exception as ex:
                    self.send_json({"error": str(ex)}, 500)
            elif os.path.exists(png_path):
                try:
                    with open(png_path, "rb") as f:
                        pxs, w, h = png_decode(f.read())
                    self.send_json({"width": w, "height": h, "pixels": pxs})
                except Exception as ex:
                    self.send_json({"error": str(ex)}, 500)
            else:
                self.send_json({"error": "not found"}, 404)

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

        elif path == "/api/reexport":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            color_name = body.get("name", "")
            updated = reexport(only_name=color_name)
            self.send_json({"ok": True, "updated": updated})

        elif path.startswith("/api/sprites/"):
            name = path[len("/api/sprites/") :]
            name = os.path.normpath(name).lstrip("/\\")
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            old_name = body.pop("_from", None)
            pxs = body["pixels"]
            base = os.path.join(ASSETS_DIR, name)
            os.makedirs(os.path.dirname(base), exist_ok=True)
            # save .src.json — preserves named color references
            with open(base + ".src.json", "w") as f:
                json.dump(body, f)
            # save .png — resolve named pixels to their current rgba
            norm = [
                [
                    (px["rgba"] if isinstance(px, dict) else (px if px else [0, 0, 0, 0]))
                    for px in row
                ]
                for row in pxs
            ]
            with open(base + ".png", "wb") as f:
                f.write(png_encode(norm))
            # move: delete old files if path changed
            if old_name and old_name != name:
                old_base = os.path.join(ASSETS_DIR, os.path.normpath(old_name).lstrip("/\\"))
                for ext in (".png", ".src.json"):
                    try: os.remove(old_base + ext)
                    except FileNotFoundError: pass
            self.send_json({"ok": True})
        else:
            self.send_response(404)
            self.end_headers()


def hex_to_rgba(hex_str):
    h = hex_str.lstrip("#")
    n = int(h, 16)
    return [(n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF, 255]


def reexport(only_name=None):
    palette_path = os.path.join(ASSETS_DIR, "palette.json")
    if not os.path.exists(palette_path):
        print("No palette.json found.")
        return
    with open(palette_path) as f:
        groups = json.load(f)
    # build name → rgba lookup from current palette
    name_map = {}
    for group in groups:
        for entry in group.get("colors", []):
            if isinstance(entry, dict) and entry.get("name") and entry.get("hex"):
                name_map[entry["name"]] = hex_to_rgba(entry["hex"])

    if not name_map:
        if only_name is None:
            print("No named colors found in palette — nothing to re-export.")
        return 0
    if only_name:
        name_map = {k: v for k, v in name_map.items() if k == only_name}
        if not name_map:
            return 0
    print(f"Named colors: {list(name_map.keys())}")

    count = 0
    for root, _, files in os.walk(ASSETS_DIR):
        for fname in files:
            if not fname.endswith(".src.json"):
                continue
            src_path = os.path.join(root, fname)
            with open(src_path) as f:
                sprite = json.load(f)
            pixels = sprite["pixels"]
            changed = False
            norm = []
            for row in pixels:
                nr = []
                for px in row:
                    if isinstance(px, dict) and px.get("name"):
                        resolved = name_map.get(px["name"])
                        if resolved:
                            nr.append(resolved)
                            # also update stored rgba so it stays consistent
                            px["rgba"] = resolved
                            changed = True
                        else:
                            nr.append(px.get("rgba", [0, 0, 0, 0]))
                    elif px:
                        nr.append(px)
                    else:
                        nr.append([0, 0, 0, 0])
                norm.append(nr)
            png_path = src_path[: -len(".src.json")] + ".png"
            with open(png_path, "wb") as f:
                f.write(png_encode(norm))
            if changed:
                with open(src_path, "w") as f:
                    json.dump(sprite, f)
            rel = os.path.relpath(png_path, ASSETS_DIR)
            if only_name is None:
                print(f"  {'updated' if changed else 'unchanged':9s}  {rel}")
            count += 1
    if only_name is None:
        print(f"\nRe-exported {count} sprite(s).")
    return count


if __name__ == "__main__":
    import sys
    if "--reexport" in sys.argv:
        reexport()
        sys.exit(0)

    os.makedirs(ASSETS_DIR, exist_ok=True)
    url = f"http://localhost:{PORT}"
    print(f"Sprite editor  →  {url}")
    print(f"Sprites dir    →  {os.path.abspath(ASSETS_DIR)}")
    print("Ctrl+C to stop")
    # webbrowser.open(url)
    HTTPServer(("localhost", PORT), Handler).serve_forever()
