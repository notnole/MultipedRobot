// Simple blink test - verifies Arduino connection is working
// Built-in LED is on pin 13 for Arduino UNO

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
}

void loop() {
  // 3 quick flashes
  for (int i = 0; i < 3; i++) {
    digitalWrite(LED_BUILTIN, HIGH);
    delay(100);
    digitalWrite(LED_BUILTIN, LOW);
    delay(100);
  }
  // pause
  delay(800);
}
