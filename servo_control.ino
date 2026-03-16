// Servo control - three servos
// Steering: MG996R (positional) on pin 7: a=left, d=right, q=center
// Motor A (ring):  360 on pin 6
// Motor B (sun):   360 on pin 5
// Gear ratios: 1=1:1, 2=1:3, 3=1:5
// IMPORTANT: power servos from external 5V supply, NOT from Arduino

#include <Servo.h>

Servo steerServo;   // positional on pin 7
Servo motorA;       // continuous on pin 6 (ring gear)
Servo motorB;       // continuous on pin 5 (sun gear)

int angle = 79;
int direction = 0;
int gear = 1;       // current gear mode (1, 2, or 3)
int driveDir = 0;   // 0=stop, 1=forward, -1=backward

void updateDrive() {
  if (driveDir == 0) {
    motorA.write(90);
    motorB.write(90);
    return;
  }
  if (driveDir == 1) {  // forward
    motorA.write(180);
    motorB.write(180);
  } else {              // backward
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
}

void loop() {
  while (Serial.available()) {
    char key = Serial.read();
    if (key == 'd') direction = 1;
    else if (key == 'a') direction = -1;
    else if (key == 'q') { direction = 0; angle = 79; }
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
  if (angle > 145) angle = 145;  // max right
  if (angle < 20) angle = 20;    // max left
  steerServo.write(angle);
  if (angle != prevAngle) {
    Serial.print("S:");
    Serial.println(angle);
  }
  delay(10);
}
