# Servo keyboard control
# a/d = steer, q = center
# Hold w = drive forward, hold s = drive backward, release = stop
# 1 = 1:1 gear, 2 = 1:3 gear, 3 = 1:5 gear (numpad works too)
# Esc = quit
#
# Logging: state transitions saved to timestamped CSV in log/.
#   Each row is a full snapshot of active commands (e.g. "w+d", "w+2").
#   Only changes are logged. Edit the CSV to fine-tune timing.
# Replay: python servo_control.py --replay log/<file.csv>
# Dry run: python servo_control.py --dry-run  (no Arduino needed)
#
# Requires: pip install pyserial pynput

import serial
import sys
import os
import csv
import threading
import time
from datetime import datetime

PORT = 'COM3'
BAUD = 9600
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'log')
DRY_RUN = '--dry-run' in sys.argv

HOLD_CMDS = {'w', 's', 'a', 'd'}
# Arduino command to send when a hold stops
STOP_FOR = {'w': 'r', 's': 'r', 'a': 'e', 'd': 'e'}

class FakeSerial:
    """Stand-in for serial.Serial when no Arduino is connected."""
    def write(self, data): pass
    def close(self): pass

# ── Replay mode ──────────────────────────────────────────────
if '--replay' in sys.argv:
    csv_path = sys.argv[sys.argv.index('--replay') + 1]
    ser = FakeSerial() if DRY_RUN else serial.Serial(PORT, BAUD)
    if not DRY_RUN:
        time.sleep(2)  # wait for Arduino reset
    print(f"Replaying {csv_path} {'(dry run)' if DRY_RUN else ''}...")

    with open(csv_path, newline='') as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        events = [(int(row[0]), row[1]) for row in reader]

    prev_holds = set()
    start = time.perf_counter()

    for i, (ms, state_str) in enumerate(events):
        # wait until the right moment
        while (time.perf_counter() - start) * 1000 < ms:
            time.sleep(0.001)

        cmds = set(state_str.split('+')) if state_str != 'stop' else set()
        holds = cmds & HOLD_CMDS
        one_shots = cmds - HOLD_CMDS

        # Send stop commands for holds no longer active
        for h in prev_holds - holds:
            ser.write(STOP_FOR[h].encode())

        # Send hold commands
        for h in holds:
            ser.write(h.encode())

        # Send one-shot commands (gear, center)
        for cmd in one_shots:
            ser.write(cmd.encode())

        if DRY_RUN:
            print(f"  {ms:>6}ms  {state_str}")
        prev_holds = holds

        # Keep sending hold commands until next event
        if i + 1 < len(events):
            next_ms = events[i + 1][0]
            while (time.perf_counter() - start) * 1000 < next_ms - 5:
                for h in holds:
                    ser.write(h.encode())
                time.sleep(0.01)

    ser.write(b'x')
    print("Replay done.")
    ser.close()
    sys.exit(0)

# ── Normal (live) mode ───────────────────────────────────────
from pynput import keyboard

ser = FakeSerial() if DRY_RUN else serial.Serial(PORT, BAUD)

os.makedirs(LOG_DIR, exist_ok=True)
log_name = os.path.join(LOG_DIR, f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
log_file = open(log_name, 'w', newline='')
log_writer = csv.writer(log_file)
log_writer.writerow(['time_ms', 'command'])
t0 = time.perf_counter()

print(f"Connected. Logging to {log_name}")
print("  a/d = steer, q = center")
print("  Hold w = forward, hold s = backward, release = stop")
print("  1/2/3 = gear (numpad works too)")
print("  Esc = quit")

held = set()
prev_logged = set()  # last logged hold state
running = True

NUMPAD_MAP = {
    96: '0', 97: '1', 98: '2', 99: '3', 100: '4',
    101: '5', 102: '6', 103: '7', 104: '8', 105: '9',
}

def get_holds():
    """Current hold state as a set."""
    h = set()
    if 'w' in held: h.add('w')
    elif 's' in held: h.add('s')
    if 'd' in held: h.add('d')
    elif 'a' in held: h.add('a')
    return h

def log_transition(one_shots=None):
    """Log a CSV row if state changed or a one-shot was fired."""
    global prev_logged
    cur = get_holds()
    if cur == prev_logged and not one_shots:
        return
    parts = sorted(cur)
    if one_shots:
        parts.extend(one_shots)
    state = '+'.join(parts) if parts else 'stop'
    ms = int((time.perf_counter() - t0) * 1000)
    log_writer.writerow([ms, state])
    if DRY_RUN:
        print(f"  {ms:>6}ms  {state}")
    prev_logged = cur

def send_loop():
    """Send held commands to Arduino every 20ms."""
    while running:
        if 'd' in held:
            ser.write(b'd')
        elif 'a' in held:
            ser.write(b'a')
        if 'w' in held:
            ser.write(b'w')
        elif 's' in held:
            ser.write(b's')
        time.sleep(0.01)

def serial_read_loop():
    """Read lines from Arduino and print steering angle."""
    while running:
        try:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line.startswith('S:'):
                print(f"  Steering: {line[2:]}°")
        except Exception:
            pass

threading.Thread(target=send_loop, daemon=True).start()
threading.Thread(target=serial_read_loop, daemon=True).start()

def get_char(key):
    try:
        return key.char
    except AttributeError:
        if hasattr(key, 'vk') and key.vk in NUMPAD_MAP:
            return NUMPAD_MAP[key.vk]
        return None

def on_press(key):
    char = get_char(key)
    if char in ('a', 'd', 'w', 's'):
        held.add(char)
        log_transition()
    elif char == 'q':
        ser.write(b'q')
        log_transition(one_shots=['q'])
    elif char in ('1', '2', '3'):
        ser.write(char.encode())
        log_transition(one_shots=[char])
    elif key == keyboard.Key.esc:
        global running
        running = False
        if prev_logged:
            ms = int((time.perf_counter() - t0) * 1000)
            log_writer.writerow([ms, 'stop'])
        log_file.close()
        ser.write(b'x')
        ser.close()
        print(f"Saved {log_name}")
        return False

def on_release(key):
    char = get_char(key)
    if char in ('a', 'd'):
        held.discard(char)
        ser.write(b'e')
        log_transition()
    elif char in ('w', 's'):
        held.discard(char)
        ser.write(b'r')
        log_transition()

with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
    listener.join()
