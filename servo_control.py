# Servo keyboard control
# a/d = steer, q = center
# Hold w = drive forward, hold s = drive backward, release = stop
# 1 = 1:1 gear, 2 = 1:3 gear, 3 = 1:5 gear (numpad works too)
# Esc = quit
#
# Logging: every serial command is saved to a timestamped CSV in log/.
#   Simultaneous commands (e.g. steer + drive) are grouped as "w+d".
# Replay: python servo_control.py --replay log/<file.csv>
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

# ── Replay mode ──────────────────────────────────────────────
if '--replay' in sys.argv:
    csv_path = sys.argv[sys.argv.index('--replay') + 1]
    ser = serial.Serial(PORT, BAUD)
    time.sleep(2)  # wait for Arduino reset
    print(f"Replaying {csv_path} ...")

    with open(csv_path, newline='') as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        commands = [(int(row[0]), row[1]) for row in reader]

    start = time.perf_counter()
    for ms, cmds in commands:
        # wait until the right moment
        while (time.perf_counter() - start) * 1000 < ms:
            time.sleep(0.001)
        # send each command in the group (e.g. "w+d" -> 'w', 'd')
        for cmd in cmds.split('+'):
            ser.write(cmd.encode())

    print("Replay done.")
    ser.write(b'x')
    ser.close()
    sys.exit(0)

# ── Normal (live) mode ───────────────────────────────────────
from pynput import keyboard

ser = serial.Serial(PORT, BAUD)

os.makedirs(LOG_DIR, exist_ok=True)
log_name = os.path.join(LOG_DIR, f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
log_file = open(log_name, 'w', newline='')
log_writer = csv.writer(log_file)
log_writer.writerow(['time_ms', 'command'])
t0 = time.perf_counter()

def log_send(cmd: bytes):
    """Send a command over serial and log it with a millisecond timestamp."""
    ser.write(cmd)
    ms = int((time.perf_counter() - t0) * 1000)
    log_writer.writerow([ms, cmd.decode()])

def log_send_batch(cmds: list[bytes]):
    """Send multiple commands and log them as one row (e.g. 'w+d')."""
    for cmd in cmds:
        ser.write(cmd)
    ms = int((time.perf_counter() - t0) * 1000)
    combined = '+'.join(cmd.decode() for cmd in cmds)
    log_writer.writerow([ms, combined])

print(f"Connected. Logging to {log_name}")
print("  a/d = steer, q = center")
print("  Hold w = forward, hold s = backward, release = stop")
print("  1/2/3 = gear (numpad works too)")
print("  Esc = quit")

held = set()
running = True

# Map numpad keys to their values
NUMPAD_MAP = {
    96: '0', 97: '1', 98: '2', 99: '3', 100: '4',
    101: '5', 102: '6', 103: '7', 104: '8', 105: '9',
}

def send_loop():
    while running:
        batch = []
        if 'd' in held:
            batch.append(b'd')
        elif 'a' in held:
            batch.append(b'a')
        if 'w' in held:
            batch.append(b'w')
        elif 's' in held:
            batch.append(b's')
        if batch:
            log_send_batch(batch)
        time.sleep(0.02)

thread = threading.Thread(target=send_loop, daemon=True)
thread.start()

def get_char(key):
    """Get character from key, handling numpad."""
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
    elif char == 'q':
        log_send(b'q')
    elif char in ('1', '2', '3'):
        log_send(char.encode())
    elif key == keyboard.Key.esc:
        global running
        running = False
        log_send(b'x')
        log_file.close()
        ser.close()
        print(f"Saved {log_name}")
        return False

def on_release(key):
    char = get_char(key)
    if char in ('a', 'd'):
        held.discard(char)
        log_send(b'e')
    elif char in ('w', 's'):
        held.discard(char)
        log_send(b'r')

with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
    listener.join()
