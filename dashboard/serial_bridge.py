"""Serial communication bridge for the robot dashboard.

Handles: CSV/JSON conversion, serial port management, recording, replay.
Extracted from servo_control.py into a class-based interface for Flask.
"""

import csv
import json
import os
import threading
import time
from datetime import datetime

HOLD_CMDS = {'w', 's', 'a', 'd'}
STOP_FOR = {'w': 'r', 's': 'r', 'a': 'e', 'd': 'e'}
LOG_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'log'))
RUNS_DIR = os.path.join(os.path.dirname(__file__), 'runs')


class FakeSerial:
    """Stand-in when no Arduino is connected."""
    def write(self, data): pass
    def readline(self): return b''
    def close(self): pass
    @property
    def in_waiting(self): return 0


class SerialBridge:
    def __init__(self):
        self.ser = None
        self.connected = False
        self.dry_run = False
        self._lock = threading.Lock()

        # Recording state
        self.recording = False
        self._rec_events = []
        self._rec_t0 = 0
        self._rec_held = set()
        self._rec_prev_state = None
        self._rec_accel = []  # accel samples during recording

        # Replay state
        self.replaying = False
        self._replay_thread = None
        self._replay_stop = threading.Event()
        self._replay_run_id = None  # which run is being replayed
        self._replay_accel = []  # accel samples during replay
        self._replay_t0 = 0

        # Interrupt state
        self._replay_interrupted = threading.Event()
        self._interrupt_held = set()
        self._interrupt_hold_stop = threading.Event()

        # Serial reader
        self._reader_thread = None
        self._reader_stop = threading.Event()
        self._serial_callback = None
        self._accel_callback = None

    # ── Connection ──────────────────────────────────────────

    def connect(self, port='COM3', baud=9600, dry_run=False):
        with self._lock:
            # If already connected in the wrong mode, disconnect first
            if self.connected and self.dry_run != dry_run:
                self._disconnect_locked()
            if self.connected:
                return True
            self.dry_run = dry_run
            if dry_run:
                self.ser = FakeSerial()
                print(f'[SerialBridge] Connected in DRY-RUN mode (no serial)', flush=True)
            else:
                import serial
                try:
                    self.ser = serial.Serial(port, baud, timeout=0.1)
                    time.sleep(2)  # wait for Arduino reset
                    print(f'[SerialBridge] Connected to {port} at {baud} baud', flush=True)
                except Exception as e:
                    return f'Could not connect to Arduino on {port}. Is it plugged in? ({e})'
            self.connected = True
            # Start serial reader thread
            self._reader_stop.clear()
            self._reader_thread = threading.Thread(target=self._serial_read_loop, daemon=True)
            self._reader_thread.start()
            return True

    def disconnect(self):
        with self._lock:
            self._disconnect_locked()

    def _disconnect_locked(self):
        """Internal disconnect, must be called with self._lock held."""
        if not self.connected:
            return
        self._reader_stop.set()
        if self.ser:
            try:
                self.ser.write(b'x')
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.connected = False

    def _serial_read_loop(self):
        while not self._reader_stop.is_set():
            try:
                if self.ser and hasattr(self.ser, 'in_waiting') and self.ser.in_waiting:
                    line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                    if not line:
                        continue
                    if line.startswith('A:'):
                        if not hasattr(self, '_accel_seen'):
                            self._accel_seen = True
                            print(f'[SerialBridge] First accel data: {line}', flush=True)
                        self._handle_accel_line(line)
                    elif self._serial_callback:
                        self._serial_callback(line)
            except Exception:
                pass
            time.sleep(0.005)

    def _handle_accel_line(self, line):
        """Parse 'A:ax,ay,az' and store during recording/replay."""
        try:
            parts = line[2:].split(',')
            ax, ay, az = float(parts[0]), float(parts[1]), float(parts[2])
        except (ValueError, IndexError):
            return

        if self.recording and self._rec_t0:
            t = int((time.perf_counter() - self._rec_t0) * 1000)
            self._rec_accel.append({'t': t, 'x': ax, 'y': ay, 'z': az})

        if self.replaying and self._replay_t0:
            t = int((time.perf_counter() - self._replay_t0) * 1000)
            self._replay_accel.append({'t': t, 'x': ax, 'y': ay, 'z': az})

        if self._accel_callback:
            self._accel_callback(ax, ay, az)

    def set_serial_callback(self, cb):
        self._serial_callback = cb

    def set_accel_callback(self, cb):
        self._accel_callback = cb

    # ── Commands ────────────────────────────────────────────

    def send_command(self, char):
        if not self.ser:
            print(f'[SerialBridge] WARN: no serial port, dropping command: {char}')
            return
        data = char.encode() if isinstance(char, str) else char
        self.ser.write(data)

    def send_state(self, state_str, prev_holds=None):
        """Send commands to transition to a new state. Returns new hold set."""
        if prev_holds is None:
            prev_holds = set()
        cmds = set(state_str.split('+')) if state_str != 'stop' else set()
        holds = cmds & HOLD_CMDS
        one_shots = cmds - HOLD_CMDS

        # Stop holds no longer active
        for h in prev_holds - holds:
            self.send_command(STOP_FOR[h])
        # Send active holds
        for h in holds:
            self.send_command(h)
        # Send one-shots
        for cmd in one_shots:
            self.send_command(cmd)
        return holds

    # ── Recording ───────────────────────────────────────────

    def start_recording(self):
        self._rec_events = [{'t': 0, 'state': 'stop'}]
        self._rec_accel = []
        self._rec_held = set()
        self._rec_prev_state = 'stop'
        self._rec_t0 = time.perf_counter()
        self.recording = True
        # Start hold-resend loop (matches servo_control.py send_loop)
        self._rec_hold_stop = threading.Event()
        self._rec_hold_thread = threading.Thread(target=self._rec_hold_loop, daemon=True)
        self._rec_hold_thread.start()
        return True

    def _rec_hold_loop(self):
        """Continuously re-send held commands every 10ms, matching servo_control.py."""
        while not self._rec_hold_stop.is_set():
            held = self._get_rec_holds()
            for h in held:
                self.send_command(h)
            time.sleep(0.01)

    def record_key_down(self, key):
        if not self.recording:
            return None
        print(f'[SerialBridge] key_down: {key} (ser={type(self.ser).__name__})')
        if key in HOLD_CMDS:
            self._rec_held.add(key)
            self.send_command(key)
        elif key == 'q':
            self.send_command('q')
        elif key in ('1', '2', '3'):
            self.send_command(key)
        return self._log_rec_transition(one_shots=[key] if key not in HOLD_CMDS else None)

    def record_key_up(self, key):
        if not self.recording:
            return None
        if key in HOLD_CMDS:
            self._rec_held.discard(key)
            self.send_command(STOP_FOR[key])
            return self._log_rec_transition()
        return None

    def _get_rec_holds(self):
        h = set()
        if 'w' in self._rec_held: h.add('w')
        elif 's' in self._rec_held: h.add('s')
        if 'd' in self._rec_held: h.add('d')
        elif 'a' in self._rec_held: h.add('a')
        return h

    def _log_rec_transition(self, one_shots=None):
        cur = self._get_rec_holds()
        parts = sorted(cur)
        if one_shots:
            parts.extend(one_shots)
        state = '+'.join(parts) if parts else 'stop'
        if state == self._rec_prev_state and not one_shots:
            return None
        ms = int((time.perf_counter() - self._rec_t0) * 1000)
        event = {'t': ms, 'state': state}
        self._rec_events.append(event)
        self._rec_prev_state = state
        return event

    def stop_recording(self):
        if not self.recording:
            return None
        self.recording = False
        self._rec_hold_stop.set()
        self.send_command('x')
        # Ensure final stop event
        if self._rec_events and self._rec_events[-1]['state'] != 'stop':
            ms = int((time.perf_counter() - self._rec_t0) * 1000)
            self._rec_events.append({'t': ms, 'state': 'stop'})
        self._rec_held.clear()

        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        run = {
            'id': run_id,
            'name': f"Run {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            'notes': '',
            'created': datetime.now().isoformat(),
            'modified': datetime.now().isoformat(),
            'source': 'recorded',
            'duration_ms': self._rec_events[-1]['t'] if self._rec_events else 0,
            'events': self._rec_events,
        }
        save_run(run)
        # Also save CSV to Code/log/ for compatibility with servo_control.py
        os.makedirs(LOG_DIR, exist_ok=True)
        csv_path = os.path.join(LOG_DIR, f"{run_id}.csv")
        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['time_ms', 'command'])
            for ev in self._rec_events:
                if ev['t'] == 0 and ev['state'] == 'stop':
                    continue
                writer.writerow([ev['t'], ev['state']])

        # Save accel trace if we got any data
        if self._rec_accel:
            accel_file = f"accel_{run_id}.csv"
            save_accel_csv(accel_file, self._rec_accel)
            trace = {
                'type': 'recording',
                'replay_number': 0,
                'timestamp': datetime.now().isoformat(),
                'file': accel_file,
            }
            run['accel_traces'] = [trace]
            save_run(run)  # re-save with trace index

        return run

    # ── Replay ──────────────────────────────────────────────

    def start_replay(self, events, progress_cb=None, run_id=None):
        if self.replaying:
            return False
        print(f'[SerialBridge] Starting replay: {len(events)} events (ser={type(self.ser).__name__})')
        self.replaying = True
        self._replay_stop.clear()
        self._replay_accel = []
        self._replay_run_id = run_id
        self._replay_thread = threading.Thread(
            target=self._replay_loop, args=(events, progress_cb), daemon=True
        )
        self._replay_thread.start()
        return True

    def _replay_loop(self, events, progress_cb):
        prev_holds = set()
        start = time.perf_counter()
        self._replay_t0 = start

        for i, ev in enumerate(events):
            if self._replay_stop.is_set():
                break
            ms = ev['t']
            state_str = ev['state']

            # Wait until the right moment
            while (time.perf_counter() - start) * 1000 < ms:
                if self._replay_stop.is_set():
                    break
                time.sleep(0.001)
            if self._replay_stop.is_set():
                break

            if not self._replay_interrupted.is_set():
                prev_holds = self.send_state(state_str, prev_holds)
            else:
                # Track what state WOULD be so resume transitions correctly
                cmds = set(state_str.split('+')) if state_str != 'stop' else set()
                prev_holds = cmds & HOLD_CMDS

            if progress_cb:
                progress_cb(i, ms, state_str)

            # Keep sending hold commands until next event
            if i + 1 < len(events):
                next_ms = events[i + 1]['t']
                while (time.perf_counter() - start) * 1000 < next_ms - 5:
                    if self._replay_stop.is_set():
                        break
                    if not self._replay_interrupted.is_set():
                        for h in prev_holds:
                            self.send_command(h)
                    time.sleep(0.01)

        self.send_command('x')
        self.replaying = False
        self._replay_t0 = 0
        # Save replay accel trace if we got data
        if self._replay_accel and self._replay_run_id:
            self._save_replay_accel()
        if progress_cb:
            progress_cb(-1, -1, 'done')

    def _save_replay_accel(self):
        """Save accel data from a replay as a new trace on the run."""
        run = load_run(self._replay_run_id)
        if not run:
            return
        traces = run.get('accel_traces', [])
        # Count existing replays
        replay_num = sum(1 for t in traces if t['type'] == 'replay') + 1
        accel_file = f"accel_{self._replay_run_id}_replay_{replay_num}.csv"
        save_accel_csv(accel_file, self._replay_accel)
        traces.append({
            'type': 'replay',
            'replay_number': replay_num,
            'timestamp': datetime.now().isoformat(),
            'file': accel_file,
        })
        run['accel_traces'] = traces
        save_run(run)

    def stop_replay(self):
        if self._replay_interrupted.is_set():
            self._interrupt_hold_stop.set()
            self._interrupt_held.clear()
            self._replay_interrupted.clear()
        self._replay_stop.set()
        self.send_command('x')
        self.replaying = False
        self._replay_t0 = 0
        if self._replay_accel and self._replay_run_id:
            self._save_replay_accel()

    # ── Interrupt ────────────────────────────────────────────

    def interrupt_replay(self):
        """Enter interrupt: suppress replay commands, allow manual control."""
        if not self.replaying:
            return False
        self._replay_interrupted.set()
        self._interrupt_held = set()
        self.send_command('x')  # stop motors from replay's last command
        self._interrupt_hold_stop = threading.Event()
        threading.Thread(target=self._interrupt_hold_loop, daemon=True).start()
        return True

    def resume_replay(self):
        """Exit interrupt: stop manual commands, let replay resume."""
        if not self._replay_interrupted.is_set():
            return False
        self._interrupt_hold_stop.set()
        for h in list(self._interrupt_held):
            self.send_command(STOP_FOR[h])
        self._interrupt_held.clear()
        self._replay_interrupted.clear()
        return True

    def interrupt_key_down(self, key):
        if not self._replay_interrupted.is_set():
            return
        if key in HOLD_CMDS:
            self._interrupt_held.add(key)
        self.send_command(key)

    def interrupt_key_up(self, key):
        if not self._replay_interrupted.is_set():
            return
        if key in HOLD_CMDS:
            self._interrupt_held.discard(key)
            self.send_command(STOP_FOR[key])

    def _interrupt_hold_loop(self):
        while not self._interrupt_hold_stop.is_set():
            for h in list(self._interrupt_held):
                self.send_command(h)
            time.sleep(0.01)

    # ── Status ──────────────────────────────────────────────

    def get_status(self):
        return {
            'connected': self.connected,
            'dry_run': self.dry_run,
            'recording': self.recording,
            'replaying': self.replaying,
            'interrupted': self._replay_interrupted.is_set(),
        }


# ── Accel I/O ───────────────────────────────────────────────

def save_accel_csv(filename, data):
    """Save accel data list to CSV in LOG_DIR."""
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, filename)
    with open(path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['time_ms', 'ax', 'ay', 'az'])
        for sample in data:
            writer.writerow([sample['t'], sample['x'], sample['y'], sample['z']])
    return path


def load_accel_csv(filename):
    """Load accel data from CSV. Returns list of {t, x, y, z}."""
    path = os.path.join(LOG_DIR, filename)
    if not os.path.exists(path):
        return []
    data = []
    with open(path, newline='') as f:
        reader = csv.reader(f)
        try:
            next(reader)  # skip header
        except StopIteration:
            return []
        for row in reader:
            if len(row) >= 4:
                try:
                    data.append({
                        't': int(row[0]),
                        'x': float(row[1]),
                        'y': float(row[2]),
                        'z': float(row[3]),
                    })
                except ValueError:
                    continue
    return data


# ── File I/O ────────────────────────────────────────────────

def csv_to_run(csv_path):
    """Convert a CSV log file to a run dict."""
    basename = os.path.splitext(os.path.basename(csv_path))[0]
    events = []
    with open(csv_path, newline='') as f:
        reader = csv.reader(f)
        try:
            next(reader)  # skip header
        except StopIteration:
            pass  # empty file
        for row in reader:
            if len(row) >= 2:
                try:
                    events.append({'t': int(row[0]), 'state': row[1].strip()})
                except ValueError:
                    continue

    if not events:
        events = [{'t': 0, 'state': 'stop'}]
    else:
        # Ensure starts with stop at t=0 if first event is later
        if events[0]['t'] > 0:
            events.insert(0, {'t': 0, 'state': 'stop'})
        # Ensure ends with stop
        if events[-1]['state'] != 'stop':
            events.append({'t': events[-1]['t'], 'state': 'stop'})

    # Parse date from filename
    try:
        date_str = basename.replace('run_', '')
        created = datetime.strptime(date_str, '%Y%m%d_%H%M%S').isoformat()
        name = f"Run {datetime.strptime(date_str, '%Y%m%d_%H%M%S').strftime('%Y-%m-%d %H:%M')}"
    except ValueError:
        created = datetime.now().isoformat()
        name = basename

    return {
        'id': basename,
        'name': name,
        'notes': '',
        'created': created,
        'modified': created,
        'source': 'csv_import',
        'duration_ms': events[-1]['t'] if events else 0,
        'events': events,
    }


def run_to_csv(run):
    """Convert a run dict to CSV string."""
    lines = ['time_ms,command']
    for ev in run['events']:
        if ev['t'] == 0 and ev['state'] == 'stop':
            continue  # skip the synthetic initial stop
        lines.append(f"{ev['t']},{ev['state']}")
    return '\n'.join(lines) + '\n'


def run_to_ino(run):
    """Generate an Arduino .ino sketch that replays the run standalone."""
    # Expand state snapshots into individual serial commands
    commands = []
    prev_holds = set()

    for ev in run['events']:
        state_str = ev['state']
        cmds = set(state_str.split('+')) if state_str != 'stop' else set()
        holds = cmds & HOLD_CMDS
        one_shots = cmds - HOLD_CMDS

        # Stop holds no longer active
        for h in sorted(prev_holds - holds):
            commands.append((ev['t'], STOP_FOR[h]))
        # Send active holds
        for h in sorted(holds):
            commands.append((ev['t'], h))
        # Send one-shots
        for cmd in sorted(one_shots):
            commands.append((ev['t'], cmd))

        prev_holds = holds

    events_array = ',\n  '.join(f'{{{t}, \'{c}\'}}' for t, c in commands)

    return f'''// Auto-generated by Robot Commander Dashboard
// Run: {run.get("name", run["id"])}
// Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

#include <Servo.h>

Servo steer, motorA, motorB;

const int PIN_STEER = 7;
const int PIN_MOTOR_A = 6;
const int PIN_MOTOR_B = 5;

int steerAngle = 79;
int driveDir = 0;   // -1=backward, 0=stop, 1=forward
int gear = 1;        // 1=slow(1:5), 2=mid(1:3), 3=fast(1:1)

struct Event {{ unsigned long t; char cmd; }};

Event events[] = {{
  {events_array}
}};
const int NUM_EVENTS = sizeof(events) / sizeof(events[0]);

void updateDrive() {{
  if (driveDir == 0) {{
    motorA.write(90);
    motorB.write(90);
  }} else {{
    int dir = (driveDir == 1) ? 1 : -1;
    if (gear == 1) {{       // slow (1:5) - A fwd, B reverse
      motorA.write(90 + dir * 90);
      motorB.write(90 - dir * 90);
    }} else if (gear == 2) {{ // mid (1:3) - A fwd, B stop
      motorA.write(90 + dir * 90);
      motorB.write(90);
    }} else {{               // fast (1:1) - both fwd
      motorA.write(90 + dir * 90);
      motorB.write(90 + dir * 90);
    }}
  }}
}}

void processCommand(char c) {{
  switch (c) {{
    case 'a': steerAngle = max(20, steerAngle - 3); steer.write(steerAngle); break;
    case 'd': steerAngle = min(145, steerAngle + 3); steer.write(steerAngle); break;
    case 'q': steerAngle = 79; steer.write(steerAngle); break;
    case 'e': break; // stop steering (just stop sending a/d)
    case 'w': driveDir = 1; updateDrive(); break;
    case 's': driveDir = -1; updateDrive(); break;
    case 'r': driveDir = 0; updateDrive(); break;
    case '1': gear = 1; updateDrive(); break;
    case '2': gear = 2; updateDrive(); break;
    case '3': gear = 3; updateDrive(); break;
    case 'x': driveDir = 0; updateDrive(); steerAngle = 79; steer.write(79); break;
  }}
}}

void setup() {{
  steer.attach(PIN_STEER);
  motorA.attach(PIN_MOTOR_A);
  motorB.attach(PIN_MOTOR_B);
  steer.write(79);
  motorA.write(90);
  motorB.write(90);
  delay(1000);

  unsigned long start = millis();
  for (int i = 0; i < NUM_EVENTS; i++) {{
    while (millis() - start < events[i].t) {{}}
    processCommand(events[i].cmd);
  }}

  // Emergency stop at end
  processCommand('x');
}}

void loop() {{
  // Nothing — single run
}}
'''


def save_run(run):
    """Save a run dict as JSON."""
    os.makedirs(RUNS_DIR, exist_ok=True)
    path = os.path.join(RUNS_DIR, f"{run['id']}.json")
    with open(path, 'w') as f:
        json.dump(run, f, indent=2)
    return path


def load_run(run_id):
    """Load a run by ID. Checks JSON dir first, then tries CSV import."""
    json_path = os.path.join(RUNS_DIR, f"{run_id}.json")
    if os.path.exists(json_path):
        with open(json_path) as f:
            return json.load(f)
    # Try CSV
    csv_path = os.path.join(LOG_DIR, f"{run_id}.csv")
    if os.path.exists(csv_path):
        run = csv_to_run(csv_path)
        save_run(run)  # cache as JSON
        return run
    return None


def list_runs():
    """List all available runs (JSON + unimported CSVs)."""
    runs = {}

    # Load JSON runs
    os.makedirs(RUNS_DIR, exist_ok=True)
    for fname in os.listdir(RUNS_DIR):
        if fname.endswith('.json'):
            path = os.path.join(RUNS_DIR, fname)
            with open(path) as f:
                run = json.load(f)
            # Return without events for listing (save bandwidth)
            runs[run['id']] = {
                'id': run['id'],
                'name': run.get('name', run['id']),
                'notes': run.get('notes', ''),
                'created': run.get('created', ''),
                'modified': run.get('modified', ''),
                'source': run.get('source', 'unknown'),
                'duration_ms': run.get('duration_ms', 0),
            }

    # Scan CSV dir for unimported runs
    if os.path.isdir(LOG_DIR):
        for fname in os.listdir(LOG_DIR):
            if fname.startswith('run_') and fname.endswith('.csv'):
                run_id = os.path.splitext(fname)[0]
                if run_id not in runs:
                    # Auto-import
                    csv_path = os.path.join(LOG_DIR, fname)
                    run = csv_to_run(csv_path)
                    save_run(run)
                    runs[run_id] = {
                        'id': run['id'],
                        'name': run['name'],
                        'notes': '',
                        'created': run['created'],
                        'modified': run['modified'],
                        'source': 'csv_import',
                        'duration_ms': run['duration_ms'],
                    }

    # Sort by created date descending
    return sorted(runs.values(), key=lambda r: r.get('created', ''), reverse=True)


def delete_run(run_id):
    """Delete a run JSON file."""
    path = os.path.join(RUNS_DIR, f"{run_id}.json")
    if os.path.exists(path):
        os.remove(path)
        return True
    return False
