// Servo control - three servos + MPU6050 accelerometer
// Steering: MG996R (positional) on pin 7: a=left, d=right, q=center
// Motor A: 360 on pin 6
// Motor B: 360 on pin 5
// Both motors drive in sync (same direction)
// Gears = speed: 1=slow, 2=medium, 3=fast
// MPU6050: SDA=A4, SCL=A5 — sends accel every 10ms
// IMPORTANT: power servos from external 5V supply, NOT from Arduino

#include <Servo.h>
#include <Wire.h>

const int MPU_ADDR = 0x68;

Servo steerServo;   // positional on pin 7
Servo motorA;       // continuous on pin 6
Servo motorB;       // continuous on pin 5

int angle = 90;
int direction = 0;
int gear = 3;       // speed: 1=slow, 2=medium, 3=fast
int driveDir = 0;   // 0=stop, 1=forward, -1=backward

void updateDrive() {
  if (driveDir == 0) {
    motorA.write(90);
    motorB.write(90);
    return;
  }
  // Both motors in sync, gear sets speed
  int speed;
  switch (gear) {
    case 1: speed = 30;  break;  // slow
    case 2: speed = 60;  break;  // medium
    case 3: speed = 90;  break;  // fast (full)
    default: speed = 90; break;
  }
  if (driveDir == 1) {  // forward
    motorA.write(90 + speed);
    motorB.write(90 + speed);
  } else {              // backward
    motorA.write(90 - speed);
    motorB.write(90 - speed);
  }
}

void setup() {
  steerServo.attach(7);
  motorA.attach(6);
  motorB.attach(5);
  steerServo.write(90);
  motorA.write(90);
  motorB.write(90);
  Serial.begin(115200);

  // Init MPU6050
  Wire.begin();
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B);  // PWR_MGMT_1
  Wire.write(0);     // wake up
  Wire.endTransmission(true);
}

void loop() {
  while (Serial.available()) {
    char key = Serial.read();
    if (key == 'd') direction = -3;
    else if (key == 'a') direction = 3;
    else if (key == 'q') { direction = 0; angle = 90; }
    else if (key == 'e') direction = 0;
    else if (key == 'w') { driveDir = 1; updateDrive(); }
    else if (key == 's') { driveDir = -1; updateDrive(); }
    else if (key == 'r') { driveDir = 0; updateDrive(); }
    else if (key == '1') { gear = 1; updateDrive(); }
    else if (key == '2') { gear = 2; updateDrive(); }
    else if (key == '3') { gear = 3; updateDrive(); }
    else if (key == 'x') { direction = 0; driveDir = 0; updateDrive(); }
  }

  angle += direction;
  if (angle > 110) angle = 110;  // max 20° right
  if (angle < 70) angle = 70;    // max 20° left
  steerServo.write(angle);

  // Read and send accelerometer data
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU_ADDR, 6, true);

  int16_t ax = Wire.read() << 8 | Wire.read();
  int16_t ay = Wire.read() << 8 | Wire.read();
  int16_t az = Wire.read() << 8 | Wire.read();

  // Send as "A:ax,ay,az" (raw counts, Python converts to g)
  Serial.print("A:");
  Serial.print(ax); Serial.print(',');
  Serial.print(ay); Serial.print(',');
  Serial.println(az);

  delay(10);
}
