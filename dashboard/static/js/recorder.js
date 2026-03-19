/* ── Recorder View ─────────────────────────────────────── */

const Recorder = {
  recording: false,
  activeKeys: new Set(),
  events: [],

  // Live accel graph
  _accelBuf: [],          // rolling buffer of {x, y, z}
  _accelMaxSamples: 200,  // ~4 seconds at 50Hz
  _accelAnimFrame: null,

  init() {
    // Keyboard capture
    document.addEventListener('keydown', e => this.onKeyDown(e));
    document.addEventListener('keyup', e => this.onKeyUp(e));

    // Focus detection
    document.addEventListener('visibilitychange', () => {
      if (document.hidden && this.recording) {
        document.getElementById('focus-warning').classList.remove('hidden');
        // Send stop commands for all held keys
        this.activeKeys.forEach(k => {
          App.socket.emit('key_up', { key: k });
        });
        this.activeKeys.clear();
        this.updateActiveKeysUI();
      } else {
        document.getElementById('focus-warning').classList.add('hidden');
      }
    });

    // WebSocket events
    App.socket.on('recording_started', () => {
      this.recording = true;
      this.events = [];
      document.getElementById('btn-start-rec').disabled = true;
      document.getElementById('btn-stop-rec').disabled = false;
      document.getElementById('rec-status').textContent = 'RECORDING';
      document.getElementById('rec-status').className = 'rec-status recording';
      document.getElementById('rec-events-list').innerHTML = '';
      document.getElementById('status-dot').className = 'dot recording';
    });

    App.socket.on('recording_stopped', data => {
      this.recording = false;
      this.activeKeys.clear();
      this.updateActiveKeysUI();
      document.getElementById('btn-start-rec').disabled = false;
      document.getElementById('btn-stop-rec').disabled = true;
      document.getElementById('rec-status').className = 'rec-status';
      App.updateStatusUI();

      if (data.run_id) {
        // Show rename popup
        this.showSavePopup(data.run_id, data.name, data.duration_ms, data.event_count);
      } else {
        document.getElementById('rec-status').textContent = 'Stopped (no data)';
      }
    });

    App.socket.on('recording_event', ev => {
      this.events.push(ev);
      const list = document.getElementById('rec-events-list');
      const div = document.createElement('div');
      div.className = 'event-line active';
      div.textContent = `${(ev.t / 1000).toFixed(2)}s  ${ev.state}`;
      // Remove active from previous
      const prev = list.querySelector('.active');
      if (prev) prev.classList.remove('active');
      list.appendChild(div);
      div.scrollIntoView({ behavior: 'smooth' });
    });

    // Live accelerometer
    App.socket.on('accel_live', data => {
      this._accelBuf.push(data);
      if (this._accelBuf.length > this._accelMaxSamples) this._accelBuf.shift();
      if (!this._accelAnimFrame) this._startAccelDraw();
    });
  },

  // ── Live Accel Graph ─────────────────────────────────

  _startAccelDraw() {
    const loop = () => {
      if (!document.getElementById('view-record').classList.contains('active')) {
        this._accelAnimFrame = null;
        return;
      }
      this._drawAccelGraph();
      this._accelAnimFrame = requestAnimationFrame(loop);
    };
    this._accelAnimFrame = requestAnimationFrame(loop);
  },

  _drawAccelGraph() {
    const canvas = document.getElementById('live-accel-canvas');
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.parentElement.clientWidth - 32;
    const h = 200;
    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = w + 'px';
      canvas.style.height = h + 'px';
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const buf = this._accelBuf;
    const n = buf.length;

    // Background
    ctx.fillStyle = '#08080e';
    ctx.fillRect(0, 0, w, h);

    if (n < 2) {
      ctx.fillStyle = '#666';
      ctx.font = '13px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Waiting for accelerometer data...', w / 2, h / 2);
      return;
    }

    // Auto-range
    let minVal = -0.5, maxVal = 0.5;
    for (const s of buf) {
      for (const k of ['x', 'y', 'z']) {
        if (s[k] < minVal) minVal = s[k];
        if (s[k] > maxVal) maxVal = s[k];
      }
    }
    const pad = (maxVal - minVal) * 0.1 || 0.1;
    minVal -= pad;
    maxVal += pad;

    // Zero line
    const zeroY = h - ((0 - minVal) / (maxVal - minVal)) * h;
    ctx.strokeStyle = 'rgba(255,255,255,0.1)';
    ctx.beginPath();
    ctx.moveTo(0, zeroY);
    ctx.lineTo(w, zeroY);
    ctx.stroke();

    // Scale labels
    ctx.fillStyle = 'rgba(255,255,255,0.15)';
    ctx.font = '10px monospace';
    ctx.textAlign = 'right';
    ctx.fillText(maxVal.toFixed(1) + 'g', w - 4, 12);
    ctx.fillText(minVal.toFixed(1) + 'g', w - 4, h - 4);

    // Draw 3 axes
    const axes = [
      { key: 'x', color: '#ef4444', label: 'X' },
      { key: 'y', color: '#22d3a0', label: 'Y' },
      { key: 'z', color: '#60a5fa', label: 'Z' },
    ];

    for (const axis of axes) {
      ctx.strokeStyle = axis.color;
      ctx.lineWidth = 1.5;
      ctx.globalAlpha = 0.8;
      ctx.beginPath();
      for (let i = 0; i < n; i++) {
        const x = (i / (this._accelMaxSamples - 1)) * w;
        const y = h - ((buf[i][axis.key] - minVal) / (maxVal - minVal)) * h;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    // Legend
    ctx.font = 'bold 11px sans-serif';
    ctx.textAlign = 'left';
    let lx = 8;
    for (const axis of axes) {
      ctx.fillStyle = axis.color;
      const val = buf[n - 1][axis.key].toFixed(2);
      const text = `${axis.label}: ${val}g`;
      ctx.fillText(text, lx, 14);
      lx += ctx.measureText(text).width + 16;
    }
  },

  onKeyDown(e) {
    if (!this.recording) return;
    // Only capture when record view is active
    if (!document.getElementById('view-record').classList.contains('active')) return;

    const key = this.mapKey(e);
    if (!key) return;
    e.preventDefault();

    if (this.activeKeys.has(key)) return; // already held
    this.activeKeys.add(key);
    this.updateActiveKeysUI();
    App.socket.emit('key_down', { key });
  },

  onKeyUp(e) {
    if (!this.recording) return;
    if (!document.getElementById('view-record').classList.contains('active')) return;

    const key = this.mapKey(e);
    if (!key) return;
    e.preventDefault();

    this.activeKeys.delete(key);
    this.updateActiveKeysUI();
    App.socket.emit('key_up', { key });
  },

  mapKey(e) {
    const k = e.key.toLowerCase();
    if (['w', 'a', 's', 'd', 'q', '1', '2', '3'].includes(k)) return k;
    return null;
  },

  updateActiveKeysUI() {
    const container = document.getElementById('rec-active-keys');
    const labels = {
      w: 'FWD', s: 'BWD', a: 'LEFT', d: 'RIGHT',
      q: 'CENTER', '1': 'SLOW', '2': 'MID', '3': 'FAST',
    };
    container.innerHTML = Array.from(this.activeKeys)
      .map(k => `<span class="active-key">${labels[k] || k}</span>`)
      .join('');
  },

  async start() {
    if (!await App.ensureConnected()) return;
    App.socket.emit('start_recording');
  },

  stop() {
    App.socket.emit('stop_recording');
  },

  showSavePopup(runId, defaultName, durationMs, eventCount) {
    const overlay = document.createElement('div');
    overlay.className = 'popup-overlay';
    overlay.innerHTML = `
      <div class="popup">
        <h3>Run Saved</h3>
        <p style="color:#aaa; margin-bottom:12px;">${eventCount} events, ${formatDuration(durationMs)}</p>
        <label>Name:</label>
        <input type="text" id="popup-run-name" value="${defaultName}" autofocus>
        <label>Notes (optional):</label>
        <input type="text" id="popup-run-notes" placeholder="e.g. wider turn, slower gear on incline">
        <div class="popup-buttons">
          <button class="btn-secondary" onclick="this.closest('.popup-overlay').remove(); Library.refresh();">Skip</button>
          <button class="btn-primary" id="popup-save-name">Save</button>
          <button class="btn-primary" id="popup-save-open">Save & Open Timeline</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    // Focus the name input and select all text
    const nameInput = document.getElementById('popup-run-name');
    nameInput.focus();
    nameInput.select();

    const doSave = async (openTimeline) => {
      const name = nameInput.value.trim() || defaultName;
      const notes = document.getElementById('popup-run-notes').value.trim();
      await fetch('/api/runs/' + runId, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, notes }),
      });
      overlay.remove();
      document.getElementById('rec-status').textContent = 'Saved: ' + name;
      Library.refresh();
      if (openTimeline) {
        Library.openTimeline(runId);
      }
    };

    document.getElementById('popup-save-name').onclick = () => doSave(false);
    document.getElementById('popup-save-open').onclick = () => doSave(true);
    nameInput.addEventListener('keydown', e => {
      if (e.key === 'Enter') doSave(false);
    });
  },
};
