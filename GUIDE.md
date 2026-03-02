# Code Guide 

**Tip:** Open the actual code files side by side while reading this. For both files, first skim through the code on its own to get a feel for the structure, then come back here for the detailed explanation.

## How the system works (big picture)

There are **two separate programs** that work together:

```
[Your keyboard] --> [Python on PC] --serial USB--> [Arduino .ino on the board] --> [Servos]
```

- **`servo_control.py`** (runs on your laptop) — Listens to your keyboard and sends single letters (like `w`, `a`, `d`, `1`, etc) over the USB cable to the Arduino.
- **`servo_control.ino`** (runs on the Arduino board) — Receives those letters and actually moves the servos.

**Why two programs?** The Arduino is a tiny microcontroller — it can't listen to your keyboard directly. It can only read bytes from the USB serial connection. So we need Python on the PC side to capture keypresses and forward them as serial bytes.

The Arduino code is already uploaded to the board. You only need to change it if you want to change how the servos behave. The Python code you run every time from your laptop.

---

## servo_control.ino — Line by line

This is written in C/C++ (Arduino language). It runs on the Arduino board in an infinite loop.

### Setup section

```cpp
#include <Servo.h>
```
Imports the Servo library — gives us the ability to control servos with simple commands like `.write(angle)`.

```cpp
Servo steerServo;   // positional on pin 7
Servo motorA;       // continuous on pin 6 (ring gear)
Servo motorB;       // continuous on pin 5 (sun gear)
```
Creates three servo objects. Think of these as "remote controls" — one for each physical servo. They don't do anything yet until we `.attach()` them to a pin.

```cpp
int angle = 90;
int direction = 0;
int gear = 1;
int driveDir = 0;
```
Variables that track the current state:
- `angle` — where the steering servo is pointing (0-180, starts at 90 = center)
- `direction` — how fast the steering is moving (-3 = turning left, 0 = stopped, 3 = turning right)
- `gear` — which gear ratio (1, 2, or 3)
- `driveDir` — drive direction (0 = stop, 1 = forward, -1 = backward)

### The drive function

```cpp
void updateDrive() {
```
This function sets the two drive motors to the right speeds based on the current gear and direction. It gets called every time you press w, s, or change gear.

```cpp
  if (driveDir == 0) {
    motorA.write(90);
    motorB.write(90);
    return;
  }
```
For continuous (360°) servos: `90` = stop, `180` = full speed one way, `0` = full speed the other way. So writing 90 to both motors stops them.

```cpp
  if (driveDir == 1) {  // forward
    switch (gear) {
      case 1: motorA.write(180); motorB.write(180); break;  // 1:1 both full forward
      case 2: motorA.write(180); motorB.write(90);  break;  // 1:3 A forward, B stopped
      case 3: motorA.write(180); motorB.write(0);   break;  // 1:5 A forward, B full reverse
    }
  }
```
This is the two-input planetary gearbox logic. By running Motor B at different speeds relative to Motor A, the planetary gears produce different output ratios. See SSA6 for the full explanation.

```cpp
  } else {              // backward - always 1:3 reversed
    motorA.write(0);
    motorB.write(90);
  }
```
Backward is just 1:3 in reverse — Motor A goes backward, Motor B stays still.

### setup() — runs once when Arduino powers on

```cpp
void setup() {
  steerServo.attach(7);   // connect steerServo object to physical pin 7
  motorA.attach(6);       // connect motorA to pin 6
  motorB.attach(5);       // connect motorB to pin 5
  steerServo.write(90);   // center steering
  motorA.write(90);       // stop motor A
  motorB.write(90);       // stop motor B
  Serial.begin(9600);     // open serial connection at 9600 baud (speed)
}
```
This runs once at startup. Connects each servo to its pin, sets everything to neutral, and opens the serial port so we can receive commands from Python.

### loop() — runs forever, over and over

```cpp
void loop() {
  while (Serial.available()) {
    char key = Serial.read();
```
Check if Python sent any bytes. Read them one at a time. Each byte is a single character like `'w'` or `'1'`.

```cpp
    if (key == 'd') direction = 3;
    else if (key == 'a') direction = -3;
```
When we receive `d`, set direction to +3 (steering moves right by 3 degrees each loop). `a` sets it to -3 (left).

```cpp
    else if (key == 'q') { direction = 0; angle = 90; }
```
`q` = center: stop steering movement AND jump angle back to 90 (center).

```cpp
    else if (key == 'e') direction = 0;
```
`e` = stop steering (but keep current angle). This is sent by Python when you release a/d.

```cpp
    else if (key == 'w') { driveDir = 1; updateDrive(); }
    else if (key == 's') { driveDir = -1; updateDrive(); }
    else if (key == 'r') { driveDir = 0; updateDrive(); }
```
`w` = forward, `s` = backward, `r` = stop driving. Each one updates the variable then calls `updateDrive()` to actually set the motor speeds.

```cpp
    else if (key == '1') { gear = 1; updateDrive(); }
    else if (key == '2') { gear = 2; updateDrive(); }
    else if (key == '3') { gear = 3; updateDrive(); }
```
Change gear. If already driving, motors update immediately to the new ratio.

```cpp
    else if (key == 'x') { direction = 0; driveDir = 0; updateDrive(); }
```
`x` = emergency stop everything (sent by Python on Esc).

```cpp
  angle += direction;
  if (angle > 180) angle = 180;
  if (angle < 0) angle = 0;
  steerServo.write(angle);
  delay(10);
```
After processing all serial commands, move the steering angle by `direction` (could be -3, 0, or +3). Clamp it to 0-180 so we don't go out of range. Write to the servo. Wait 10ms then loop again. This means steering moves 3 degrees every 10ms when held.

---

## servo_control.py — Line by line

This is Python. It runs on your laptop and sends keypresses to the Arduino.

### Imports and connection

```python
import serial          # talk to Arduino over USB
import threading       # run things in parallel
import time            # for sleep/delays
from pynput import keyboard  # listen to keyboard without needing focus
```

```python
ser = serial.Serial('COM3', 9600)
```
Open a serial connection to the Arduino on port COM3 at 9600 baud. This must match the `Serial.begin(9600)` in the Arduino code. **Only one program can use COM3 at a time** — close Serial Monitor first.

### Tracking held keys

```python
held = set()
running = True
```
`held` is a set (like a bag) of currently pressed keys. When you press `w`, `'w'` gets added. When you release, it gets removed. This is how we know what's being held right now.

### Numpad support

```python
NUMPAD_MAP = {
    96: '0', 97: '1', 98: '2', 99: '3', ...
}
```
Numpad keys have different internal codes than the regular number keys. This dictionary translates them. `97` (numpad 1) becomes `'1'`.

### The send loop (runs in background)

```python
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
```
This runs in a separate thread (background task) every 20ms. It checks what keys are held and keeps sending the corresponding byte to the Arduino. This is why holding a key gives continuous movement — it doesn't rely on the OS key repeat.

Note: steering (`a`/`d`) and drive (`w`/`s`) are checked independently (first `if` block + second `if` block), so you can steer and drive at the same time.

```python
thread = threading.Thread(target=send_loop, daemon=True)
thread.start()
```
Start the send loop in the background. `daemon=True` means it dies when the main program exits.

### Key press handler

```python
def on_press(key):
    char = get_char(key)
    if char in ('a', 'd', 'w', 's'):
        held.add(char)
```
When a key is pressed, add it to the `held` set. The send loop will pick it up.

```python
    elif char == 'q':
        ser.write(b'q')
```
`q` is a one-shot command (center steering), not a hold — send it immediately.

```python
    elif char in ('1', '2', '3'):
        ser.write(char.encode())
```
Gear changes are also one-shot. `.encode()` converts the string `'1'` to bytes `b'1'`.

### Key release handler

```python
def on_release(key):
    char = get_char(key)
    if char in ('a', 'd'):
        held.discard(char)
        ser.write(b'e')       # tell Arduino to stop steering
    elif char in ('w', 's'):
        held.discard(char)
        ser.write(b'r')       # tell Arduino to stop driving
```
When you release a key, remove it from `held` (so the send loop stops sending it) AND send a stop command to the Arduino. `e` = stop steering, `r` = stop drive. These are separate so releasing `w` doesn't stop the steering.

---

## Letter protocol (what gets sent over USB)

| Byte | Meaning | Who sends it |
|------|---------|-------------|
| `a` | Steer left | send_loop (while held) |
| `d` | Steer right | send_loop (while held) |
| `e` | Stop steering | on_release |
| `q` | Center steering | on_press |
| `w` | Drive forward | send_loop (while held) |
| `s` | Drive backward | send_loop (while held) |
| `r` | Stop driving | on_release |
| `1` | Gear 1:1 | on_press |
| `2` | Gear 1:3 | on_press |
| `3` | Gear 1:5 | on_press |
| `x` | Stop everything | on Esc |

---

## Task 1: Serial dashboard

**Goal:** Print the current state (gear, steering angle, drive direction) to the Serial Monitor so we can see what the robot is doing.

**Hints:**
- In the Arduino code, you can send text back to the PC with `Serial.println("text")` or `Serial.print(variable)`
- Add prints inside `loop()` after updating the angle — something like: `Serial.print("Gear:"); Serial.print(gear); Serial.print(" Angle:"); Serial.println(angle);`
- Problem: if you print every loop (every 10ms) it will flood the monitor. Use a counter or `millis()` to only print every 200-500ms
- You don't need to change the Python code at all — just open a second terminal and use `python -m serial.tools.miniterm COM3 9600` to read the output, OR add a read loop in Python

**Stretch:** Format it nicely, e.g. `[Gear 1:1] [Steer: 90°] [Drive: FWD]`

## Task 2: Run recorder and replay

**Goal:** Record a manual drive as a sequence of (timestamp, command) pairs, save to a file, then replay it automatically.

**Hints — Recording (Python side):**
- In `servo_control.py`, every time `ser.write()` is called, also save `(time.time(), command)` to a list
- When done (Esc), write the list to a file, e.g. `run_log.txt` with lines like `0.00,w` and `1.52,2` and `3.10,r`
- `time.time()` gives current time in seconds — subtract the start time to get relative timestamps

**Hints — Replay (Python side):**
- New script `replay.py`: read the file, open serial, then loop through commands
- For each line: wait until the right timestamp (use `time.sleep(next_time - current_time)`), then `ser.write(command)`
- The Arduino code doesn't need to change at all — it just receives the same bytes, doesn't care if a human or a script sent them

**Stretch:** Add a key (like `F1`) in servo_control.py to start/stop recording without restarting the program.
