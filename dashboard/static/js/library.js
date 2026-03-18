/* ── Library View ──────────────────────────────────────── */

const Library = {
  runs: [],

  init() {
    this.refresh();
  },

  async refresh() {
    const res = await fetch('/api/runs');
    this.runs = await res.json();
    this.render();
  },

  render() {
    const container = document.getElementById('runs-list');
    if (this.runs.length === 0) {
      container.innerHTML = '<p style="color:#666; padding:20px;">No runs found. Record one or check that CSV files exist in Code/log/</p>';
      return;
    }

    container.innerHTML = this.runs.map(run => `
      <div class="run-card" data-id="${run.id}">
        <div class="run-name">
          <input value="${this.escHtml(run.name)}" onchange="Library.rename('${run.id}', this.value)" />
        </div>
        <div class="run-date">${formatDate(run.created)}</div>
        <div class="run-duration">${formatDuration(run.duration_ms)}</div>
        <div class="run-source ${run.source}">${this.sourceLabel(run.source)}</div>
        <div class="run-actions">
          <button class="btn-small" onclick="Library.openTimeline('${run.id}')">Timeline</button>
          <button class="btn-small" onclick="Library.replay('${run.id}')">Replay</button>
          <button class="btn-small" onclick="Library.duplicate('${run.id}')">Duplicate</button>
          <button class="btn-small" onclick="Library.exportCsv('${run.id}')">CSV</button>
          <button class="btn-small" onclick="Library.exportIno('${run.id}')">Arduino</button>
          <button class="btn-small btn-danger" onclick="Library.deleteRun('${run.id}')">Delete</button>
        </div>
      </div>
    `).join('');
  },

  sourceLabel(src) {
    const labels = { csv_import: 'Imported', recorded: 'Recorded', edited: 'Edited', manual: 'Manual' };
    return labels[src] || src;
  },

  escHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  },

  async rename(id, name) {
    await fetch(`/api/runs/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
  },

  async openTimeline(id) {
    const res = await fetch(`/api/runs/${id}`);
    const run = await res.json();
    App.switchView('timeline');
    // Small delay to let the view become visible so canvas can size itself
    requestAnimationFrame(() => Timeline.loadRun(run));
  },

  async replay(id) {
    if (!await App.ensureConnected()) return;
    // Open timeline first so user can see the playback
    await this.openTimeline(id);
    App.socket.emit('start_replay', { run_id: id });
  },

  async duplicate(id) {
    await fetch(`/api/runs/${id}/duplicate`, { method: 'POST' });
    this.refresh();
  },

  exportCsv(id) {
    window.open(`/api/runs/${id}/export/csv`, '_blank');
  },

  exportIno(id) {
    window.open(`/api/runs/${id}/export/ino`, '_blank');
  },

  async deleteRun(id) {
    if (!confirm('Delete this run?')) return;
    await fetch(`/api/runs/${id}`, { method: 'DELETE' });
    this.refresh();
  },
};
