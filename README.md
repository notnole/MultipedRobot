# Multiped Robot Control

Keyboard control for the multiped robot's drivetrain and steering.

## Setup

The Arduino UNO should already have `servo_test.ino` uploaded. You only need to run the Python controller.

### Requirements

```
pip install pyserial pynput
```

### Run

1. Connect the Arduino via USB (default port: COM3)
2. **Close any Serial Monitor** (Arduino IDE / PlatformIO) — only one program can use the port
3. Run the controller:

```
python servo_control.py
```

## Controls

| Key | Action |
|-----|--------|
| **Hold w** | Drive forward (current gear) |
| **Hold s** | Drive backward (1:3 reverse) |
| **a / d** | Steer left / right |
| **q** | Center steering |
| **1** | Gear 1:1 (both motors full forward) |
| **2** | Gear 1:3 (Motor A forward, Motor B stopped) |
| **3** | Gear 1:5 (Motor A forward, Motor B full reverse) |
| **Esc** | Quit |

Numpad 1/2/3 also work for gear selection.

## Wiring

- **Pin 7** — Steering servo (MG996R, 180°)
- **Pin 6** — Motor A / ring gear (360° continuous)
- **Pin 5** — Motor B / sun gear (360° continuous)
- All servo power from external 5V 7A supply (never from Arduino 5V pin)
- Arduino GND and power supply GND must be connected together
