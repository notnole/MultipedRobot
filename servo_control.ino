// Servo control - three servos
// Steering: MG996R (positional) on pin 7: a=left, d=right, q=center
// Motor A (ring):  360 on pin 6
// Motor B (sun):   360 on pin 5
// Gear ratios: 1=1:1, 2=1:3, 3=1:5
// MPU6050: SDA=A4, SCL=A5 (standard I2C)
// IMPORTANT: power servos from external 5V supply, NOT from Arduino

#include <Servo.h>
#include <Wire.h>

Servo steerServo;   // positional on pin 7
Servo motorA;       // continuous on pin 6 (ring gear)
Servo motorB;       // continuous on pin 5 (sun gear)

int angle = 90;
int direction = 0;
int gear = 3;       // current gear mode (1, 2, or 3)
int driveDir = 0;   // 0=stop, 1=forward, -1=backward

// MPU6050
const int MPU_ADDR = 0x68;
unsigned long lastAccelSend = 0;
const unsigned long ACCEL_INTERVAL = 20; // ms between accel readings

void updateDrive() {
  if (driveDir == 0) {
    motorA.write(90);
    motorB.write(90);
    return;
  }
  if (driveDir == 1) {  // forward
    switch (gear) {
      case 1: motorA.write(100); motorB.write(100); break;
      case 2: motorA.write(150); motorB.write(150);  break;
      case 3: motorA.write(180); motorB.write(180);   break;
    }
  } else {              // backward - always 1:3 reversed
    motorA.write(0);
    motorB.write(0);
  }
}

void setup() {
  steerServo.attach(7);
  motorA.attach(6);
  motorB.attach(5);
  steerServo.write(90);
  motorA.write(90);
  motorB.write(90);
  Serial.begin(9600);

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
    if (key == 'd') direction = 3;
    else if (key == 'a') direction = -3;
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

  int prevAngle = angle;
  angle += direction;
  if (angle > 130) angle = 132;
  if (angle < 36) angle = 34;
  steerServo.write(angle);
  if (angle != prevAngle) {
    Serial.print("S:");
    Serial.println(angle);
  }
  // Send accelerometer data every 20ms
  unsigned long now = millis();
  if (now - lastAccelSend >= ACCEL_INTERVAL) {
    lastAccelSend = now;
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(0x3B);
    Wire.endTransmission(false);
    Wire.requestFrom(MPU_ADDR, 6, true);

    int16_t ax = Wire.read() << 8 | Wire.read();
    int16_t ay = Wire.read() << 8 | Wire.read();
    int16_t az = Wire.read() << 8 | Wire.read();

    // A:ax,ay,az in g (±2g range, 16384 LSB/g)
    Serial.print("A:");
    Serial.print(ax / 16384.0, 3);
    Serial.print(",");
    Serial.print(ay / 16384.0, 3);
    Serial.print(",");
    Serial.println(az / 16384.0, 3);
  }

  delay(10);
}