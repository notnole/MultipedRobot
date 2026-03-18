"""Robot Commander Dashboard — Flask application.

Start: python app.py
Opens browser to http://localhost:5000
"""

import os
import json
import copy
import webbrowser
import threading
from datetime import datetime
from flask import Flask, render_template, jsonify, request, Response
from flask_socketio import SocketIO, emit

from serial_bridge import (
    SerialBridge, list_runs, load_run, save_run, delete_run,
    run_to_csv, run_to_ino, load_accel_csv,
)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'robot-commander'
socketio = SocketIO(app, cors_allowed_origins='*')

bridge = SerialBridge()


# ── Pages ───────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


# ── REST API: Runs ──────────────────────────────────────────

@app.route('/api/runs')
def api_list_runs():
    return jsonify(list_runs())


@app.route('/api/runs/<run_id>')
def api_get_run(run_id):
    run = load_run(run_id)
    if not run:
        return jsonify({'error': 'Run not found'}), 404
    return jsonify(run)


@app.route('/api/runs', methods=['POST'])
def api_create_run():
    data = request.json
    run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run = {
        'id': run_id,
        'name': data.get('name', f"Run {datetime.now().strftime('%Y-%m-%d %H:%M')}"),
        'notes': data.get('notes', ''),
        'created': datetime.now().isoformat(),
        'modified': datetime.now().isoformat(),
        'source': 'manual',
        'duration_ms': 0,
        'events': data.get('events', [{'t': 0, 'state': 'stop'}]),
    }
    if run['events']:
        run['duration_ms'] = run['events'][-1]['t']
    save_run(run)
    return jsonify(run), 201


@app.route('/api/runs/<run_id>', methods=['PUT'])
def api_update_run(run_id):
    run = load_run(run_id)
    if not run:
        return jsonify({'error': 'Run not found'}), 404
    data = request.json
    if 'name' in data:
        run['name'] = data['name']
    if 'notes' in data:
        run['notes'] = data['notes']
    if 'events' in data:
        run['events'] = data['events']
        run['duration_ms'] = run['events'][-1]['t'] if run['events'] else 0
    run['modified'] = datetime.now().isoformat()
    save_run(run)
    return jsonify(run)


@app.route('/api/runs/<run_id>', methods=['DELETE'])
def api_delete_run(run_id):
    if delete_run(run_id):
        return jsonify({'ok': True})
    return jsonify({'error': 'Run not found'}), 404


@app.route('/api/runs/<run_id>/duplicate', methods=['POST'])
def api_duplicate_run(run_id):
    run = load_run(run_id)
    if not run:
        return jsonify({'error': 'Run not found'}), 404
    new_run = copy.deepcopy(run)
    new_run['id'] = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    new_run['name'] = f"{run['name']} (copy)"
    new_run['created'] = datetime.now().isoformat()
    new_run['modified'] = datetime.now().isoformat()
    new_run['source'] = 'edited'
    save_run(new_run)
    return jsonify(new_run), 201


@app.route('/api/runs/<run_id>/export/csv')
def api_export_csv(run_id):
    run = load_run(run_id)
    if not run:
        return jsonify({'error': 'Run not found'}), 404
    csv_content = run_to_csv(run)
    return Response(
        csv_content,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={run_id}.csv'},
    )


@app.route('/api/runs/<run_id>/export/ino')
def api_export_ino(run_id):
    run = load_run(run_id)
    if not run:
        return jsonify({'error': 'Run not found'}), 404
    ino_content = run_to_ino(run)
    return Response(
        ino_content,
        mimetype='text/plain',
        headers={'Content-Disposition': f'attachment; filename={run_id}.ino'},
    )


# ── REST API: Acceleration ──────────────────────────────────

@app.route('/api/runs/<run_id>/accel')
def api_get_accel_traces(run_id):
    """Get trace index for a run (without the actual data)."""
    run = load_run(run_id)
    if not run:
        return jsonify({'error': 'Run not found'}), 404
    return jsonify(run.get('accel_traces', []))


@app.route('/api/runs/<run_id>/accel/<int:trace_idx>')
def api_get_accel_data(run_id, trace_idx):
    """Get actual accel data for a specific trace."""
    run = load_run(run_id)
    if not run:
        return jsonify({'error': 'Run not found'}), 404
    traces = run.get('accel_traces', [])
    if trace_idx < 0 or trace_idx >= len(traces):
        return jsonify({'error': 'Trace not found'}), 404
    trace = traces[trace_idx]
    data = load_accel_csv(trace['file'])
    return jsonify({'trace': trace, 'data': data})


@app.route('/api/accel/compare')
def api_compare_accel():
    """Load accel data for cross-run comparison. Query: ?traces=run_id:idx,run_id:idx"""
    specs = request.args.get('traces', '')
    results = []
    for spec in specs.split(','):
        if ':' not in spec:
            continue
        rid, idx_str = spec.split(':', 1)
        try:
            idx = int(idx_str)
        except ValueError:
            continue
        run = load_run(rid)
        if not run:
            continue
        traces = run.get('accel_traces', [])
        if 0 <= idx < len(traces):
            trace = traces[idx]
            data = load_accel_csv(trace['file'])
            results.append({
                'run_id': rid,
                'run_name': run.get('name', rid),
                'trace': trace,
                'data': data,
            })
    return jsonify(results)


# ── REST API: Serial ────────────────────────────────────────

@app.route('/api/serial/status')
def api_serial_status():
    return jsonify(bridge.get_status())


@app.route('/api/serial/connect', methods=['POST'])
def api_serial_connect():
    data = request.json or {}
    port = data.get('port', 'COM3')
    baud = data.get('baud', 9600)
    dry_run = data.get('dry_run', False)
    result = bridge.connect(port, baud, dry_run)
    if result is True:
        bridge.set_serial_callback(lambda line: socketio.emit('serial_data', {'line': line}))
        return jsonify({'ok': True, 'status': bridge.get_status()})
    return jsonify({'error': str(result)}), 500


@app.route('/api/serial/disconnect', methods=['POST'])
def api_serial_disconnect():
    bridge.disconnect()
    return jsonify({'ok': True})


# ── WebSocket: Recording ────────────────────────────────────

@socketio.on('start_recording')
def ws_start_recording():
    if not bridge.connected:
        emit('error', {'message': 'Not connected to Arduino. Connect first or use dry-run mode.'})
        return
    bridge.start_recording()
    emit('recording_started', {})


@socketio.on('stop_recording')
def ws_stop_recording():
    run = bridge.stop_recording()
    if run:
        emit('recording_stopped', {
            'run_id': run['id'],
            'name': run['name'],
            'duration_ms': run['duration_ms'],
            'event_count': len(run['events']),
        })
    else:
        emit('recording_stopped', {'run_id': None})


@socketio.on('key_down')
def ws_key_down(data):
    key = data.get('key', '')
    event = bridge.record_key_down(key)
    if event:
        emit('recording_event', event)


@socketio.on('key_up')
def ws_key_up(data):
    key = data.get('key', '')
    event = bridge.record_key_up(key)
    if event:
        emit('recording_event', event)


# ── WebSocket: Replay ───────────────────────────────────────

@socketio.on('start_replay')
def ws_start_replay(data):
    run_id = data.get('run_id')
    events = data.get('events')  # allow replaying edited (unsaved) events

    if not bridge.connected:
        emit('error', {'message': 'Not connected to Arduino. Connect first or use dry-run mode.'})
        return

    if events is None:
        run = load_run(run_id)
        if not run:
            emit('error', {'message': 'Run not found'})
            return
        events = run['events']

    def on_progress(index, t, state):
        if index == -1:
            socketio.emit('replay_done', {})
        else:
            socketio.emit('replay_progress', {'index': index, 't': t, 'state': state})

    bridge.start_replay(events, on_progress, run_id=run_id)
    emit('replay_started', {})


@socketio.on('stop_replay')
def ws_stop_replay():
    bridge.stop_replay()
    emit('replay_stopped', {})


# ── Main ────────────────────────────────────────────────────

if __name__ == '__main__':
    # Open browser after a short delay
    threading.Timer(1.5, lambda: webbrowser.open('http://localhost:5000')).start()
    print('Robot Commander Dashboard starting on http://localhost:5000')
    socketio.run(app, host='127.0.0.1', port=5000, debug=False, allow_unsafe_werkzeug=True)
