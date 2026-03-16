# MPU6050 accelerometer test reader
# Reads Serial output from mpu6050_test.ino and prints to terminal
# Usage: python mpu6050_test.py
# Requires: pip install pyserial

import serial
import sys

PORT = 'COM3'
BAUD = 115200

try:
    ser = serial.Serial(PORT, BAUD, timeout=2)
except serial.SerialException:
    print(f"Could not open {PORT}. Check connection.")
    sys.exit(1)

print(f"Listening on {PORT}... (Ctrl+C to quit)\n")

try:
    while True:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line:
            print(line)
except KeyboardInterrupt:
    print("\nDone.")
finally:
    ser.close()
