# Servo keyboard control
# a/d = steer, q = center
# Hold w = drive forward, hold s = drive backward, release = stop
# 1 = 1:1 gear, 2 = 1:3 gear, 3 = 1:5 gear (numpad works too)
# Esc = quit
# Requires: pip install pyserial pynput

import serial
import threading
import time
from pynput import keyboard

ser = serial.Serial('COM3', 9600)
print("Connected.")
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
        if 'd' in held:
            ser.write(b'd')
        elif 'a' in held:
            ser.write(b'a')
        if 'w' in held:
            ser.write(b'w')
        elif 's' in held:
            ser.write(b's')
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
        ser.write(b'q')
    elif char in ('1', '2', '3'):
        ser.write(char.encode())
    elif key == keyboard.Key.esc:
        global running
        running = False
        ser.write(b'x')
        ser.close()
        return False

def on_release(key):
    char = get_char(key)
    if char in ('a', 'd'):
        held.discard(char)
        ser.write(b'e')
    elif char in ('w', 's'):
        held.discard(char)
        ser.write(b'r')

with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
    listener.join()
