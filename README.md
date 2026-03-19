# Multiped Robot Control

Keyboard control and web dashboard for the multiped robot's drivetrain, steering, and accelerometer.

## Setup

### 1. Install Python dependencies

```
pip install -r requirements.txt
```

Or manually: `pip install flask flask-socketio pyserial pynput`

### 2. Upload Arduino sketch

Open `servo_control.ino` in Arduino IDE and upload to the Arduino UNO.

### 3. Connect Arduino via USB (default port: COM3)

**Close any Serial Monitor** (Arduino IDE / PlatformIO) — only one program can use the port.

## Run

### Dashboard (recommended)

```
cd Code/dashboard
python app.py
```

Or double-click `start.bat`. Opens at http://localhost:5000.

Features:
- **Library** — view, rename, duplicate, delete runs; export as CSV or Arduino sketch
- **Record** — capture keyboard input with live accelerometer graph
- **Timeline** — visual editor for run timing with drag/resize blocks
- **Replay** — play back runs with real-time cursor
- **Interrupt** — press any key during replay for manual override; "End Override" to resume
- **Acceleration** — X/Y/Z accel graphs synced with timeline zoom/pan

### Terminal control

```
python servo_control.py
```

## Controls

| Key | Action |
|-----|--------|
| **Hold w** | Drive forward (current gear) |
| **Hold s** | Drive backward |
| **a / d** | Steer left / right |
| **q** | Center steering |
| **1** | Gear 1 (slow) |
| **2** | Gear 2 (mid) |
| **3** | Gear 3 (fast) |
| **Esc** | Quit (terminal mode) |

Numpad 1/2/3 also work for gear selection.

## Wiring

- **Pin 7** — Steering servo (MG996R, 180°)
- **Pin 6** — Motor A / ring gear (360° continuous)
- **Pin 5** — Motor B / sun gear (360° continuous)
- **MPU6050** — SDA → A4, SCL → A5, VCC → 5V, GND → GND
- All servo power from external 5V 7A supply (never from Arduino 5V pin)
- Arduino GND and power supply GND must be connected together
