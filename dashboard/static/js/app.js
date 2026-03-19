/* ── App: Navigation, WebSocket, Connection ────────────── */

const App = {
  socket: null,
  connected: false,

  init() {
    // Navigation
    document.querySelectorAll('.nav-btn').forEach(btn => {
      btn.addEventListener('click', () => App.switchView(btn.dataset.view));
    });

    // WebSocket
    this.socket = io();
    this.socket.on('connect', () => console.log('WebSocket connected'));
    this.socket.on('error', data => alert(data.message));
    this.socket.on('serial_data', data => {
      // Could display steering angle, etc.
      console.log('Arduino:', data.line);
    });

    // Init views
    Library.init();
    Recorder.init();
    Timeline.init();

    // Check serial status
    this.refreshStatus();
  },

  switchView(name) {
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.querySelector(`[data-view="${name}"]`).classList.add('active');
    document.getElementById(`view-${name}`).classList.add('active');

    if (name === 'library') Library.refresh();
    if (name === 'timeline') Timeline.resize();
  },

  async toggleConnection() {
    if (this.connected) {
      await fetch('/api/serial/disconnect', { method: 'POST' });
      this.connected = false;
    } else {
      await this.doConnect();
    }
    this.updateStatusUI();
  },

  async doConnect(forceDryRun) {
    const dryRun = forceDryRun || document.getElementById('chk-dry-run').checked;
    const btn = document.getElementById('btn-connect');
    btn.textContent = 'Connecting...';
    btn.disabled = true;
    try {
      const res = await fetch('/api/serial/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dry_run: dryRun }),
      });
      const data = await res.json();
      if (data.ok) {
        this.connected = true;
        this.updateStatusUI();
        return true;
      } else {
        alert(data.error || 'Connection failed');
        btn.disabled = false;
        this.updateStatusUI();
        return false;
      }
    } catch (e) {
      alert('Connection failed: ' + e.message);
      btn.disabled = false;
      this.updateStatusUI();
      return false;
    }
  },

  /** Ensure connected before an action. Tries real Arduino if dry-run is unchecked. */
  async ensureConnected() {
    if (this.connected) return true;
    const dryRun = document.getElementById('chk-dry-run').checked;
    if (dryRun) {
      return await this.doConnect(true);
    }
    // Try real Arduino first
    const ok = await this.doConnect(false);
    if (ok) return true;
    // Failed — ask if they want dry-run instead
    if (confirm('Arduino not found. Start in dry-run mode instead?\n\n(Check "Dry run" to skip this next time)')) {
      document.getElementById('chk-dry-run').checked = true;
      return await this.doConnect(true);
    }
    return false;
  },

  async refreshStatus() {
    const res = await fetch('/api/serial/status');
    const data = await res.json();
    this.connected = data.connected;
    this.updateStatusUI();
  },

  updateStatusUI() {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    const btn = document.getElementById('btn-connect');
    const isDryRun = document.getElementById('chk-dry-run').checked;
    if (this.connected) {
      dot.className = 'dot connected';
      text.textContent = isDryRun ? 'Dry Run' : 'Connected';
      btn.textContent = 'Disconnect';
      btn.disabled = false;
    } else {
      dot.className = 'dot disconnected';
      text.textContent = 'Disconnected';
      btn.textContent = 'Connect';
      btn.disabled = false;
    }
  },
};

// Helpers
function formatDuration(ms) {
  if (!ms) return '0.0s';
  const s = ms / 1000;
  if (s < 60) return s.toFixed(1) + 's';
  const m = Math.floor(s / 60);
  const rem = (s % 60).toFixed(1);
  return `${m}m ${rem}s`;
}

function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

document.addEventListener('DOMContentLoaded', () => App.init());
