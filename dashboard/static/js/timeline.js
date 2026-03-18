/* ── Timeline Editor (Canvas-based) ────────────────────── */

const Timeline = {
  canvas: null,
  ctx: null,
  run: null,           // current run data
  originalEvents: null, // for revert
  blocks: [],          // derived visual blocks
  dirty: false,

  // View transform
  zoom: 1,             // pixels per ms
  panX: 0,             // offset in ms
  canvasW: 0,
  canvasH: 0,

  // Track layout
  HEADER_H: 30,
  TRACK_H: 50,
  TRACK_GAP: 4,
  LABEL_W: 70,
  tracks: [
    { name: 'Drive',   keys: ['w', 's'],    colors: { w: '#22d3a0', s: '#ef4444' }, labels: { w: 'FWD', s: 'BWD' } },
    { name: 'Steer',   keys: ['a', 'd'],    colors: { a: '#60a5fa', d: '#fbbf24' }, labels: { a: 'LEFT', d: 'RIGHT' } },
    { name: 'Gear',    keys: ['1', '2', '3'], colors: { '1': '#a855f7', '2': '#22d3a0', '3': '#ec4899' }, labels: { '1': 'SLOW', '2': 'MID', '3': 'FAST' } },
  ],

  // Interaction
  dragging: null,
  hoveredBlock: null,
  isPanning: false,
  panStartX: 0,
  panStartPanX: 0,

  // Playback
  playing: false,
  playbackMs: 0,
  _lastServerMs: 0,
  _lastServerTime: 0,
  _animFrame: null,
  _currentState: 'stop',

  init() {
    this.canvas = document.getElementById('timeline-canvas');
    this.ctx = this.canvas.getContext('2d');

    // Mouse events
    this.canvas.addEventListener('mousedown', e => this.onMouseDown(e));
    this.canvas.addEventListener('mousemove', e => this.onMouseMove(e));
    this.canvas.addEventListener('mouseup', e => this.onMouseUp(e));
    this.canvas.addEventListener('mouseleave', e => this.onMouseUp(e));
    this.canvas.addEventListener('wheel', e => this.onWheel(e), { passive: false });
    this.canvas.addEventListener('dblclick', e => this.onDblClick(e));
    this.canvas.addEventListener('contextmenu', e => this.onContextMenu(e));

    // Replay progress — smooth interpolation
    App.socket.on('replay_progress', data => {
      this._lastServerMs = data.t;
      this._lastServerTime = performance.now();
      this._currentState = data.state;
      this.updateStateIndicator(data.state);
      if (!this._animFrame) this._startAnimLoop();
    });
    App.socket.on('replay_done', () => {
      this.playing = false;
      this._stopAnimLoop();
      this.playbackMs = 0;
      document.getElementById('btn-play').disabled = false;
      document.getElementById('btn-stop-playback').disabled = true;
      document.getElementById('playback-state').textContent = 'Done';
      this.updateStateIndicator('stop');
      this.draw();
    });
    App.socket.on('replay_started', () => {
      this.playing = true;
      this._lastServerMs = 0;
      this._lastServerTime = performance.now();
      this.playbackMs = 0;
      document.getElementById('btn-play').disabled = true;
      document.getElementById('btn-stop-playback').disabled = false;
      this._startAnimLoop();
    });
    App.socket.on('replay_stopped', () => {
      this.playing = false;
      this._stopAnimLoop();
      document.getElementById('btn-play').disabled = false;
      document.getElementById('btn-stop-playback').disabled = true;
      this.updateStateIndicator('stop');
    });

    window.addEventListener('resize', () => this.resize());
  },

  // ── Smooth Playback Animation ───────────────────────

  _startAnimLoop() {
    if (this._animFrame) return;
    const loop = () => {
      if (!this.playing) { this._animFrame = null; return; }
      // Interpolate cursor position between server updates
      const elapsed = performance.now() - this._lastServerTime;
      this.playbackMs = this._lastServerMs + elapsed;
      if (this.run) this.playbackMs = Math.min(this.playbackMs, this.run.duration_ms);
      document.getElementById('playback-time').textContent = (this.playbackMs / 1000).toFixed(1) + 's';
      // Determine current state from events for the indicator
      if (this.run) {
        let state = 'stop';
        for (let i = this.run.events.length - 1; i >= 0; i--) {
          if (this.run.events[i].t <= this.playbackMs) {
            state = this.run.events[i].state;
            break;
          }
        }
        this.updateStateIndicator(state);
      }
      this.draw();
      // Also update accel graphs if visible
      if (document.getElementById('panel-accel')?.classList.contains('active') && this._accelTraces.length) {
        this._drawAccelGraphs();
      }
      this._animFrame = requestAnimationFrame(loop);
    };
    this._animFrame = requestAnimationFrame(loop);
  },

  _stopAnimLoop() {
    if (this._animFrame) {
      cancelAnimationFrame(this._animFrame);
      this._animFrame = null;
    }
  },

  // ── State Indicator ─────────────────────────────────

  updateStateIndicator(stateStr) {
    const cmds = stateStr === 'stop' ? [] : stateStr.split('+');
    const allKeys = ['w', 'a', 's', 'd', 'q', '1', '2', '3'];
    for (const k of allKeys) {
      const el = document.getElementById(`ind-${k}`);
      if (el) el.classList.toggle('active', cmds.includes(k));
    }
    document.getElementById('playback-state').textContent = stateStr === 'stop' ? '' : stateStr;
  },

  /** Also update indicator when hovering over blocks (without playing) */
  updateIndicatorFromTime(ms) {
    if (!this.run || this.playing) return;
    let state = 'stop';
    for (let i = this.run.events.length - 1; i >= 0; i--) {
      if (this.run.events[i].t <= ms) {
        state = this.run.events[i].state;
        break;
      }
    }
    this.updateStateIndicator(state);
  },

  loadRun(run) {
    this.run = run;
    this.originalEvents = JSON.parse(JSON.stringify(run.events));
    this.dirty = false;
    this.playbackMs = 0;
    this._currentState = 'stop';

    document.getElementById('timeline-title').textContent = run.name;
    document.getElementById('btn-save-timeline').disabled = true;
    document.getElementById('btn-revert').disabled = true;
    document.getElementById('btn-play').disabled = false;
    document.getElementById('playback-time').textContent = '0.0s';
    document.getElementById('playback-state').textContent = '';
    this.updateStateIndicator('stop');

    // Auto-zoom to fit
    const dur = run.duration_ms || 1000;
    this.resize();
    this.zoom = Math.max(0.02, (this.canvasW - this.LABEL_W - 40) / dur);
    this.panX = 0;

    this.deriveBlocks();
    this.draw();
  },

  resize() {
    const container = this.canvas.parentElement;
    const dpr = window.devicePixelRatio || 1;
    const w = container.clientWidth;
    const h = this.HEADER_H + (this.TRACK_H + this.TRACK_GAP) * this.tracks.length + 20;
    this.canvas.width = w * dpr;
    this.canvas.height = h * dpr;
    this.canvas.style.width = w + 'px';
    this.canvas.style.height = h + 'px';
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.canvasW = w;
    this.canvasH = h;
    this.draw();
  },

  // ── Block Derivation ────────────────────────────────

  deriveBlocks() {
    if (!this.run) return;
    this.blocks = [];
    const events = this.run.events;

    for (let ti = 0; ti < this.tracks.length; ti++) {
      const track = this.tracks[ti];
      let activeKey = null;
      let blockStart = 0;

      for (let i = 0; i < events.length; i++) {
        const ev = events[i];
        const state = ev.state;
        const cmds = state === 'stop' ? [] : state.split('+');

        let curKey = null;
        for (const k of track.keys) {
          if (cmds.includes(k)) { curKey = k; break; }
        }

        // Gear track: one-shot, stays active until another gear
        if (ti === 2) {
          if (curKey) {
            if (activeKey && activeKey !== curKey) {
              this.blocks.push({ track: ti, key: activeKey, start: blockStart, end: ev.t });
            }
            activeKey = curKey;
            blockStart = ev.t;
          }
          continue;
        }

        // Drive and steer tracks
        if (curKey !== activeKey) {
          if (activeKey) {
            this.blocks.push({ track: ti, key: activeKey, start: blockStart, end: ev.t });
          }
          activeKey = curKey;
          blockStart = ev.t;
        }
      }

      // Close final block
      if (activeKey) {
        const endTime = events.length > 0 ? events[events.length - 1].t : 0;
        this.blocks.push({ track: ti, key: activeKey, start: blockStart, end: endTime });
      }
    }
  },

  // ── Rendering ───────────────────────────────────────

  msToX(ms) {
    return this.LABEL_W + (ms - this.panX) * this.zoom;
  },

  xToMs(x) {
    return (x - this.LABEL_W) / this.zoom + this.panX;
  },

  draw() {
    const ctx = this.ctx;
    const w = this.canvasW;
    const h = this.canvasH;
    ctx.clearRect(0, 0, w, h);

    if (!this.run) {
      ctx.fillStyle = '#666';
      ctx.font = '14px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Select a run from the Library', w / 2, h / 2);
      return;
    }

    // ── Time ruler ──
    ctx.fillStyle = '#08080e';
    ctx.fillRect(0, 0, w, this.HEADER_H);

    const pxPerMs = this.zoom;
    let tickMs;
    if (pxPerMs > 2) tickMs = 10;
    else if (pxPerMs > 0.5) tickMs = 50;
    else if (pxPerMs > 0.2) tickMs = 100;
    else if (pxPerMs > 0.05) tickMs = 500;
    else if (pxPerMs > 0.02) tickMs = 1000;
    else if (pxPerMs > 0.005) tickMs = 5000;
    else tickMs = 10000;

    const startMs = Math.max(0, Math.floor(this.panX / tickMs) * tickMs);
    const endMs = this.xToMs(w);

    ctx.strokeStyle = '#2a3a5c';
    ctx.fillStyle = '#888';
    ctx.font = '11px monospace';
    ctx.textAlign = 'center';

    for (let ms = startMs; ms <= endMs; ms += tickMs) {
      const x = this.msToX(ms);
      if (x < this.LABEL_W) continue;

      // Major vs minor ticks
      const isMajor = ms % (tickMs * 5) === 0 || tickMs >= 1000;
      ctx.strokeStyle = isMajor ? 'rgba(139,92,246,0.12)' : 'rgba(139,92,246,0.05)';
      ctx.beginPath();
      ctx.moveTo(x, this.HEADER_H - (isMajor ? 8 : 4));
      ctx.lineTo(x, h);
      ctx.stroke();

      if (isMajor) {
        ctx.fillStyle = '#6b6b80';
        const label = ms >= 1000 ? (ms / 1000).toFixed(ms % 1000 === 0 ? 0 : 1) + 's' : ms + 'ms';
        ctx.fillText(label, x, this.HEADER_H - 12);
      }
    }

    // ── Track labels and backgrounds ──
    for (let ti = 0; ti < this.tracks.length; ti++) {
      const y = this.HEADER_H + ti * (this.TRACK_H + this.TRACK_GAP);
      ctx.fillStyle = ti % 2 === 0 ? '#0a0a10' : '#08080e';
      ctx.fillRect(0, y, w, this.TRACK_H);

      ctx.fillStyle = '#3a3a4a';
      ctx.font = '12px sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText(this.tracks[ti].name, this.LABEL_W - 10, y + this.TRACK_H / 2 + 4);
    }

    // ── Blocks ──
    for (const block of this.blocks) {
      const track = this.tracks[block.track];
      const y = this.HEADER_H + block.track * (this.TRACK_H + this.TRACK_GAP) + 6;
      const bh = this.TRACK_H - 12;
      let x1 = this.msToX(block.start);
      let x2 = this.msToX(block.end);

      if (x2 < this.LABEL_W || x1 > w) continue;
      x1 = Math.max(x1, this.LABEL_W);
      const bw = Math.max(x2 - x1, 2);

      // Color — highlight if playback cursor is inside this block
      const isPlaying = this.playing && this.playbackMs >= block.start && this.playbackMs < block.end;
      ctx.fillStyle = track.colors[block.key] || '#555';
      if (isPlaying) {
        ctx.globalAlpha = 1;
        ctx.shadowColor = track.colors[block.key];
        ctx.shadowBlur = 8;
      } else if (block === this.hoveredBlock) {
        ctx.globalAlpha = 0.85;
      }

      // Rounded rect
      const r = Math.min(4, bw / 2);
      ctx.beginPath();
      ctx.moveTo(x1 + r, y);
      ctx.lineTo(x1 + bw - r, y);
      ctx.quadraticCurveTo(x1 + bw, y, x1 + bw, y + r);
      ctx.lineTo(x1 + bw, y + bh - r);
      ctx.quadraticCurveTo(x1 + bw, y + bh, x1 + bw - r, y + bh);
      ctx.lineTo(x1 + r, y + bh);
      ctx.quadraticCurveTo(x1, y + bh, x1, y + bh - r);
      ctx.lineTo(x1, y + r);
      ctx.quadraticCurveTo(x1, y, x1 + r, y);
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.shadowBlur = 0;

      // Label
      if (bw > 30) {
        ctx.fillStyle = '#fff';
        ctx.font = 'bold 11px sans-serif';
        ctx.textAlign = 'center';
        const label = track.labels[block.key] || block.key;
        ctx.fillText(label, x1 + bw / 2, y + bh / 2 + 4);
      }

      // Duration label in ms
      if (bw > 50) {
        const durMs = block.end - block.start;
        ctx.fillStyle = 'rgba(255,255,255,0.6)';
        ctx.font = '9px monospace';
        ctx.fillText(durMs + 'ms', x1 + bw / 2, y + bh - 3);
      }

      // Edge handles on hover
      if (block === this.hoveredBlock) {
        ctx.fillStyle = '#fff';
        ctx.fillRect(x1, y, 3, bh);
        ctx.fillRect(x1 + bw - 3, y, 3, bh);
      }
    }

    // ── Playback cursor ──
    if (this.playbackMs > 0 || this.playing) {
      const cx = this.msToX(this.playbackMs);
      if (cx >= this.LABEL_W && cx <= w) {
        ctx.strokeStyle = '#8b5cf6';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(cx, 0);
        ctx.lineTo(cx, h);
        ctx.stroke();
        ctx.lineWidth = 1;

        // Triangle at top
        ctx.fillStyle = '#8b5cf6';
        ctx.beginPath();
        ctx.moveTo(cx - 6, 0);
        ctx.lineTo(cx + 6, 0);
        ctx.lineTo(cx, 8);
        ctx.fill();

        // Time label on cursor
        ctx.fillStyle = '#8b5cf6';
        ctx.font = 'bold 10px monospace';
        ctx.textAlign = 'center';
        ctx.fillText((this.playbackMs / 1000).toFixed(1) + 's', cx, h - 2);
      }
    }
  },

  // ── Hit Testing ──────────────────────────────────────

  hitTest(mx, my) {
    for (const block of this.blocks) {
      const y = this.HEADER_H + block.track * (this.TRACK_H + this.TRACK_GAP) + 6;
      const bh = this.TRACK_H - 12;
      const x1 = this.msToX(block.start);
      const x2 = this.msToX(block.end);

      if (my >= y && my <= y + bh && mx >= x1 - 4 && mx <= x2 + 4) {
        let edge = 'body';
        if (Math.abs(mx - x1) < 6) edge = 'start';
        else if (Math.abs(mx - x2) < 6) edge = 'end';
        return { block, edge };
      }
    }
    return null;
  },

  // ── Mouse Handlers ──────────────────────────────────

  onMouseDown(e) {
    const rect = this.canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    if (e.button === 1 || (e.button === 0 && mx < this.LABEL_W)) {
      this.isPanning = true;
      this.panStartX = e.clientX;
      this.panStartPanX = this.panX;
      return;
    }

    const hit = this.hitTest(mx, my);
    if (hit && e.button === 0) {
      this.dragging = {
        block: hit.block,
        edge: hit.edge,
        offsetMs: this.xToMs(mx) - hit.block.start,
        origStart: hit.block.start,
        origEnd: hit.block.end,
      };
      this.canvas.style.cursor = hit.edge === 'body' ? 'grabbing' : 'col-resize';
    } else if (!hit && e.button === 0 && mx > this.LABEL_W) {
      this.isPanning = true;
      this.panStartX = e.clientX;
      this.panStartPanX = this.panX;
    }
  },

  onMouseMove(e) {
    const rect = this.canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    if (this.isPanning) {
      const dx = e.clientX - this.panStartX;
      this.panX = this.panStartPanX - dx / this.zoom;
      this.panX = Math.max(0, this.panX);
      this.draw();
      return;
    }

    if (this.dragging) {
      const ms = Math.max(0, this.xToMs(mx));
      const block = this.dragging.block;
      const snap = 10;

      if (this.dragging.edge === 'body') {
        const dur = this.dragging.origEnd - this.dragging.origStart;
        let newStart = Math.round((ms - this.dragging.offsetMs) / snap) * snap;
        newStart = Math.max(0, newStart);
        block.start = newStart;
        block.end = newStart + dur;
      } else if (this.dragging.edge === 'start') {
        block.start = Math.min(Math.round(ms / snap) * snap, block.end - snap);
        block.start = Math.max(0, block.start);
      } else if (this.dragging.edge === 'end') {
        block.end = Math.max(Math.round(ms / snap) * snap, block.start + snap);
      }
      this.draw();
      return;
    }

    // Hover
    const hit = this.hitTest(mx, my);
    const prevHover = this.hoveredBlock;
    this.hoveredBlock = hit ? hit.block : null;
    if (hit) {
      this.canvas.style.cursor = hit.edge === 'body' ? 'grab' : 'col-resize';
    } else {
      this.canvas.style.cursor = 'default';
    }
    if (this.hoveredBlock !== prevHover) this.draw();

    // Update keyboard indicator based on mouse time position
    if (mx > this.LABEL_W && !this.playing) {
      this.updateIndicatorFromTime(this.xToMs(mx));
    }
  },

  onMouseUp(e) {
    if (this.dragging) {
      this.resolveOverlaps(this.dragging.block);
      this.reconstructEvents();
      this.markDirty();
      this.dragging = null;
      this.canvas.style.cursor = 'default';
    }
    this.isPanning = false;
  },

  /** Remove or clip any blocks on the same track that overlap with the given block. */
  resolveOverlaps(movedBlock) {
    const newBlocks = [];
    for (const b of this.blocks) {
      if (b === movedBlock || b.track !== movedBlock.track) {
        newBlocks.push(b);
        continue;
      }
      // Same track — check overlap
      if (b.end <= movedBlock.start || b.start >= movedBlock.end) {
        // No overlap
        newBlocks.push(b);
      } else if (b.start < movedBlock.start && b.end > movedBlock.end) {
        // Existing block fully contains moved block — split into two
        newBlocks.push({ track: b.track, key: b.key, start: b.start, end: movedBlock.start });
        newBlocks.push({ track: b.track, key: b.key, start: movedBlock.end, end: b.end });
      } else if (b.start < movedBlock.start) {
        // Overlaps on the left — clip its end
        b.end = movedBlock.start;
        if (b.end > b.start) newBlocks.push(b);
      } else if (b.end > movedBlock.end) {
        // Overlaps on the right — clip its start
        b.start = movedBlock.end;
        if (b.end > b.start) newBlocks.push(b);
      }
      // else: fully covered by moved block — drop it
    }
    this.blocks = newBlocks;
  },

  onWheel(e) {
    e.preventDefault();
    const rect = this.canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const msAtMouse = this.xToMs(mx);

    const factor = e.deltaY > 0 ? 0.85 : 1.18;
    this.zoom = Math.max(0.001, Math.min(10, this.zoom * factor));

    this.panX = msAtMouse - (mx - this.LABEL_W) / this.zoom;
    this.panX = Math.max(0, this.panX);
    this.draw();
  },

  onDblClick(e) {
    const rect = this.canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    const hit = this.hitTest(mx, my);
    if (hit) {
      this.showEditPopup(hit.block);
    } else if (mx > this.LABEL_W) {
      const trackIdx = this.getTrackAtY(my);
      if (trackIdx >= 0) {
        const ms = Math.max(0, Math.round(this.xToMs(mx)));
        this.showAddPopup(trackIdx, ms);
      }
    }
  },

  onContextMenu(e) {
    e.preventDefault();
    const rect = this.canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    const hit = this.hitTest(mx, my);
    if (hit) {
      this.blocks = this.blocks.filter(b => b !== hit.block);
      this.reconstructEvents();
      this.markDirty();
      this.draw();
    }
  },

  getTrackAtY(y) {
    for (let i = 0; i < this.tracks.length; i++) {
      const ty = this.HEADER_H + i * (this.TRACK_H + this.TRACK_GAP);
      if (y >= ty && y <= ty + this.TRACK_H) return i;
    }
    return -1;
  },

  // ── Popups ──────────────────────────────────────────

  showEditPopup(block) {
    const track = this.tracks[block.track];
    const overlay = document.createElement('div');
    overlay.className = 'popup-overlay';
    overlay.innerHTML = `
      <div class="popup">
        <h3>Edit Block</h3>
        <label>Type: <strong>${track.labels[block.key]}</strong></label>
        <label>Start (ms):</label>
        <input type="number" id="popup-start" value="${block.start}" step="10">
        <label>End (ms):</label>
        <input type="number" id="popup-end" value="${block.end}" step="10">
        <label>Shift entire block (ms):</label>
        <div class="shift-buttons">
          <button onclick="document.getElementById('popup-start').value = parseInt(document.getElementById('popup-start').value) - 100; document.getElementById('popup-end').value = parseInt(document.getElementById('popup-end').value) - 100;">-100</button>
          <button onclick="document.getElementById('popup-start').value = parseInt(document.getElementById('popup-start').value) - 50; document.getElementById('popup-end').value = parseInt(document.getElementById('popup-end').value) - 50;">-50</button>
          <button onclick="document.getElementById('popup-start').value = parseInt(document.getElementById('popup-start').value) - 10; document.getElementById('popup-end').value = parseInt(document.getElementById('popup-end').value) - 10;">-10</button>
          <button onclick="document.getElementById('popup-start').value = parseInt(document.getElementById('popup-start').value) + 10; document.getElementById('popup-end').value = parseInt(document.getElementById('popup-end').value) + 10;">+10</button>
          <button onclick="document.getElementById('popup-start').value = parseInt(document.getElementById('popup-start').value) + 50; document.getElementById('popup-end').value = parseInt(document.getElementById('popup-end').value) + 50;">+50</button>
          <button onclick="document.getElementById('popup-start').value = parseInt(document.getElementById('popup-start').value) + 100; document.getElementById('popup-end').value = parseInt(document.getElementById('popup-end').value) + 100;">+100</button>
        </div>
        <div class="popup-buttons">
          <button onclick="this.closest('.popup-overlay').remove()">Cancel</button>
          <button class="btn-primary" id="popup-apply">Apply</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });

    document.getElementById('popup-apply').onclick = () => {
      block.start = Math.max(0, parseInt(document.getElementById('popup-start').value) || 0);
      block.end = Math.max(block.start + 10, parseInt(document.getElementById('popup-end').value) || 0);
      this.resolveOverlaps(block);
      overlay.remove();
      this.reconstructEvents();
      this.markDirty();
      this.draw();
    };
  },

  showAddPopup(trackIdx, ms) {
    const track = this.tracks[trackIdx];
    const overlay = document.createElement('div');
    overlay.className = 'popup-overlay';

    const options = track.keys.map(k =>
      `<option value="${k}">${track.labels[k]}</option>`
    ).join('');

    overlay.innerHTML = `
      <div class="popup">
        <h3>Add ${track.name} Block</h3>
        <label>Type:</label>
        <select id="popup-type">${options}</select>
        <label>Start (ms):</label>
        <input type="number" id="popup-start" value="${ms}" step="10">
        <label>Duration (ms):</label>
        <input type="number" id="popup-dur" value="500" step="10">
        <div class="popup-buttons">
          <button onclick="this.closest('.popup-overlay').remove()">Cancel</button>
          <button class="btn-primary" id="popup-add">Add</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });

    document.getElementById('popup-add').onclick = () => {
      const key = document.getElementById('popup-type').value;
      const start = Math.max(0, parseInt(document.getElementById('popup-start').value) || 0);
      const dur = Math.max(10, parseInt(document.getElementById('popup-dur').value) || 500);
      const newBlock = { track: trackIdx, key, start, end: start + dur };
      this.blocks.push(newBlock);
      this.resolveOverlaps(newBlock);
      overlay.remove();
      this.reconstructEvents();
      this.markDirty();
      this.draw();
    };
  },

  // ── Block → Event Reconstruction ────────────────────

  reconstructEvents() {
    const times = new Set([0]);
    for (const b of this.blocks) {
      times.add(b.start);
      times.add(b.end);
    }
    const sortedTimes = Array.from(times).sort((a, b) => a - b);

    const events = [];
    let prevState = '';

    for (const t of sortedTimes) {
      const active = [];
      for (const b of this.blocks) {
        if (t >= b.start && t < b.end) {
          active.push(b.key);
        }
      }
      const state = active.length > 0 ? active.sort().join('+') : 'stop';
      if (state !== prevState) {
        events.push({ t, state });
        prevState = state;
      }
    }

    const maxEnd = Math.max(...this.blocks.map(b => b.end), 0);
    if (events.length === 0 || events[events.length - 1].state !== 'stop') {
      events.push({ t: maxEnd, state: 'stop' });
    }

    this.run.events = events;
    this.run.duration_ms = events[events.length - 1].t;
  },

  // ── Dirty State ─────────────────────────────────────

  markDirty() {
    this.dirty = true;
    document.getElementById('btn-save-timeline').disabled = false;
    document.getElementById('btn-revert').disabled = false;
  },

  // ── Save / Revert ───────────────────────────────────

  async save() {
    if (!this.run) return;
    await fetch(`/api/runs/${this.run.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ events: this.run.events }),
    });
    this.originalEvents = JSON.parse(JSON.stringify(this.run.events));
    this.dirty = false;
    document.getElementById('btn-save-timeline').disabled = true;
    document.getElementById('btn-revert').disabled = true;
  },

  revert() {
    if (!this.run || !this.originalEvents) return;
    this.run.events = JSON.parse(JSON.stringify(this.originalEvents));
    this.run.duration_ms = this.run.events[this.run.events.length - 1]?.t || 0;
    this.dirty = false;
    document.getElementById('btn-save-timeline').disabled = true;
    document.getElementById('btn-revert').disabled = true;
    this.deriveBlocks();
    this.draw();
  },

  // ── Playback ────────────────────────────────────────

  async play() {
    if (!this.run) return;
    if (!await App.ensureConnected()) return;
    App.socket.emit('start_replay', {
      run_id: this.run.id,
      events: this.dirty ? this.run.events : undefined,
    });
  },

  stop() {
    App.socket.emit('stop_replay');
  },

  // ── Panel Toggle (Keyboard / Acceleration) ──────────

  togglePanel(panel) {
    document.querySelectorAll('.toggle-btn').forEach(b => b.classList.toggle('active', b.dataset.panel === panel));
    document.querySelectorAll('.bottom-panel').forEach(p => p.classList.remove('active'));
    document.getElementById(`panel-${panel}`).classList.add('active');
    if (panel === 'accel') this.initAccelPanel();
  },

  // ── Acceleration Graphs ─────────────────────────────

  _accelTraces: [],       // loaded trace data [{label, color, data:[{t,x,y,z}]}]

  initAccelPanel() {
    if (!this.run) return;
    // Populate cross-run dropdown
    this._populateCrossRunDropdown();
    this.loadAccelData();
  },

  async _populateCrossRunDropdown() {
    const res = await fetch('/api/runs');
    const runs = await res.json();
    const sel = document.getElementById('accel-cross-run');
    sel.innerHTML = runs
      .filter(r => r.id !== this.run.id)
      .map(r => `<option value="${r.id}">${r.name}</option>`)
      .join('');
  },

  onAccelModeChange() {
    const mode = document.getElementById('accel-overlay-mode').value;
    document.getElementById('accel-cross-run').classList.toggle('hidden', mode !== 'cross');
    this.loadAccelData();
  },

  async loadAccelData() {
    if (!this.run) return;
    this._accelTraces = [];
    const mode = document.getElementById('accel-overlay-mode').value;

    // Colors for traces
    const traceColors = [
      '#8b5cf6', '#22d3a0', '#60a5fa', '#fbbf24', '#ec4899',
      '#a855f7', '#34d399', '#93c5fd', '#f59e0b', '#f472b6',
    ];

    if (mode === 'self') {
      // Load all traces for this run (recording + replays)
      const res = await fetch(`/api/runs/${this.run.id}/accel`);
      const traces = await res.json();
      if (!traces.length) {
        this._showNoAccelData();
        return;
      }
      for (let i = 0; i < traces.length; i++) {
        const dataRes = await fetch(`/api/runs/${this.run.id}/accel/${i}`);
        const { trace, data } = await dataRes.json();
        const label = trace.type === 'recording'
          ? 'Original recording'
          : `Replay #${trace.replay_number}`;
        this._accelTraces.push({ label, color: traceColors[i % traceColors.length], data });
      }
    } else {
      // Cross-run: load this run's recording + other run's recording
      const otherRunId = document.getElementById('accel-cross-run').value;
      if (!otherRunId) return;
      const spec = `${this.run.id}:0,${otherRunId}:0`;
      const res = await fetch(`/api/accel/compare?traces=${spec}`);
      const results = await res.json();
      results.forEach((r, i) => {
        this._accelTraces.push({
          label: r.run_name,
          color: traceColors[i % traceColors.length],
          data: r.data,
        });
      });
      if (!this._accelTraces.length) {
        this._showNoAccelData();
        return;
      }
    }

    this._renderAccelLegend();
    this._drawAccelGraphs();
  },

  _showNoAccelData() {
    const container = document.querySelector('.accel-graphs');
    container.innerHTML = '<div class="accel-no-data">No acceleration data recorded yet.<br>Connect the MPU6050 and record or replay a run.</div>';
    document.getElementById('accel-legend').innerHTML = '';
  },

  _renderAccelLegend() {
    const legend = document.getElementById('accel-legend');
    legend.innerHTML = this._accelTraces.map(t =>
      `<div class="accel-legend-item"><div class="accel-legend-swatch" style="background:${t.color}"></div>${t.label}</div>`
    ).join('');
  },

  _drawAccelGraphs() {
    // Make sure the canvases exist (they might have been replaced by no-data message)
    const container = document.querySelector('.accel-graphs');
    if (!container.querySelector('canvas')) {
      container.innerHTML = `
        <canvas id="accel-canvas-x" class="accel-canvas"></canvas>
        <canvas id="accel-canvas-y" class="accel-canvas"></canvas>
        <canvas id="accel-canvas-z" class="accel-canvas"></canvas>
      `;
    }

    const axes = [
      { id: 'accel-canvas-x', key: 'x', label: 'X (forward/back)', color: '#ef4444' },
      { id: 'accel-canvas-y', key: 'y', label: 'Y (left/right)', color: '#22d3a0' },
      { id: 'accel-canvas-z', key: 'z', label: 'Z (up/down)', color: '#60a5fa' },
    ];

    for (const axis of axes) {
      const canvas = document.getElementById(axis.id);
      if (!canvas) continue;
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.parentElement.clientWidth - 16;
      const h = 120;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = w + 'px';
      canvas.style.height = h + 'px';
      const ctx = canvas.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      // Find data range
      let minVal = -0.5, maxVal = 0.5;
      let maxT = this.run.duration_ms || 1000;
      for (const trace of this._accelTraces) {
        for (const s of trace.data) {
          const v = s[axis.key];
          if (v < minVal) minVal = v;
          if (v > maxVal) maxVal = v;
          if (s.t > maxT) maxT = s.t;
        }
      }
      const range = maxVal - minVal || 1;
      const pad = range * 0.1;
      minVal -= pad;
      maxVal += pad;

      // Background
      ctx.fillStyle = '#08080e';
      ctx.fillRect(0, 0, w, h);

      // Grid
      ctx.strokeStyle = 'rgba(139,92,246,0.08)';
      ctx.lineWidth = 0.5;
      // Zero line
      const zeroY = h - ((0 - minVal) / (maxVal - minVal)) * h;
      ctx.strokeStyle = 'rgba(255,255,255,0.1)';
      ctx.beginPath();
      ctx.moveTo(0, zeroY);
      ctx.lineTo(w, zeroY);
      ctx.stroke();

      // Axis label
      ctx.fillStyle = 'rgba(255,255,255,0.3)';
      ctx.font = '10px "JetBrains Mono", monospace';
      ctx.textAlign = 'left';
      ctx.fillText(axis.label, 6, 14);

      // Y scale labels
      ctx.textAlign = 'right';
      ctx.fillStyle = 'rgba(255,255,255,0.15)';
      ctx.fillText(maxVal.toFixed(1) + 'g', w - 4, 12);
      ctx.fillText(minVal.toFixed(1) + 'g', w - 4, h - 4);

      // Draw traces
      for (const trace of this._accelTraces) {
        if (!trace.data.length) continue;
        ctx.strokeStyle = trace.color;
        ctx.lineWidth = 1.2;
        ctx.globalAlpha = 0.8;
        ctx.beginPath();
        let first = true;
        for (const s of trace.data) {
          const x = (s.t / maxT) * w;
          const y = h - ((s[axis.key] - minVal) / (maxVal - minVal)) * h;
          if (first) { ctx.moveTo(x, y); first = false; }
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
        ctx.globalAlpha = 1;
      }

      // Playback cursor
      if (this.playbackMs > 0 || this.playing) {
        const cx = (this.playbackMs / maxT) * w;
        ctx.strokeStyle = '#8b5cf6';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(cx, 0);
        ctx.lineTo(cx, h);
        ctx.stroke();
      }
    }
  },
};
