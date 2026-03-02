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

int angle = 90;
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
    switch (gear) {
      case 1: motorA.write(180); motorB.write(180); break;
      case 2: motorA.write(180); motorB.write(90);  break;
      case 3: motorA.write(180); motorB.write(0);   break;
    }
  } else {              // backward - always 1:3 reversed
    motorA.write(0);
    motorB.write(90);
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

  angle += direction;
  if (angle > 180) angle = 180;
  if (angle < 0) angle = 0;
  steerServo.write(angle);
  delay(10);
}
