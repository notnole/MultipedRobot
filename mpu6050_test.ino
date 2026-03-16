// MPU6050 accelerometer test
// Wiring: SDA=A4, SCL=A5, VCC=5V, GND=GND
// Prints acceleration (g) every 0.5s over Serial

#include <Wire.h>

const int MPU_ADDR = 0x68;

void setup() {
  Serial.begin(115200);
  Wire.begin();

  // Wake up MPU6050 (it starts in sleep mode)
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B);  // PWR_MGMT_1 register
  Wire.write(0);     // wake up
  Wire.endTransmission(true);

  Serial.println("MPU6050 ready");
  Serial.println("ax(g)\tay(g)\taz(g)");
}

void loop() {
  // Request 6 bytes of accel data starting at register 0x3B
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU_ADDR, 6, true);

  int16_t ax = Wire.read() << 8 | Wire.read();
  int16_t ay = Wire.read() << 8 | Wire.read();
  int16_t az = Wire.read() << 8 | Wire.read();

  // Default range is ±2g, sensitivity = 16384 LSB/g
  Serial.print(ax / 16384.0, 2); Serial.print('\t');
  Serial.print(ay / 16384.0, 2); Serial.print('\t');
  Serial.println(az / 16384.0, 2);

  delay(500);
}
