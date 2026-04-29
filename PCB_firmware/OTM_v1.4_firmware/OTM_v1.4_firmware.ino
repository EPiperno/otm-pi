/*
 * OTM v1.3 Firmware for Teensy 4.1
 * Controls 4 TMC2209 Stepper Motor Drivers via Serial
 * Supports I2C pressure/depth and temperature sensors
 * 
 * Command format: <motor_number> <pause_us> <steps>
 * Example: "1 100 200" = Motor 1, 100us delay, 200 steps forward
 *          "1 100 -200" = Motor 1, 100us delay, 200 steps backward
 * Use positive steps for forward, negative steps for backward
 * Sensor command: "v" prints sensor values
 */

#include <Wire.h>
#include <KellerLD.h>
#include <TSYS01.h>

// ========== PIN CONFIGURATION ==========
// Motor 1 Pins
const int MOTOR1_DIR = 3;
const int MOTOR1_STEP = 2;
const int MOTOR1_PDN = 1;

// Motor 2 Pins
const int MOTOR2_DIR = 5;
const int MOTOR2_STEP = 4;
const int MOTOR2_PDN = 8;

// Motor 3 Pins
const int MOTOR3_DIR = 7;
const int MOTOR3_STEP = 6;
const int MOTOR3_PDN = 29;

// Motor 4 Pins
const int MOTOR4_DIR = 10;
const int MOTOR4_STEP = 9;
const int MOTOR4_PDN = 35;

// Pin arrays for easier management
int dirPins[4] = {MOTOR1_DIR, MOTOR2_DIR, MOTOR3_DIR, MOTOR4_DIR};
int stepPins[4] = {MOTOR1_STEP, MOTOR2_STEP, MOTOR3_STEP, MOTOR4_STEP};
int pdnPins[4] = {MOTOR1_PDN, MOTOR2_PDN, MOTOR3_PDN, MOTOR4_PDN};

// Ring LED PWM output
const int RING_PWM_PIN = 11;

// Set false to reduce motor/driver heat when the axis is idle.
const bool HOLD_MOTORS_AFTER_MOVE = false;

// Blue Robotics leak sensor digital output (HIGH when leak detected)
const int LEAK_SENSOR_PIN = 41;

// I2C sensors (SDA=18, SCL=19)
KellerLD pressureSensor;
TSYS01 tempSensor;

bool pressureSensorReady = false;
bool tempSensorReady = false;
bool leakDetected = false;
bool leakLedState = false;
unsigned long lastLeakBlinkMs = 0;

const unsigned long LEAK_BLINK_INTERVAL_MS = 200;

void updateLeakAlarm() {
  bool leakNow = (digitalRead(LEAK_SENSOR_PIN) == HIGH);

  if (leakNow && !leakDetected) {
    Serial.println("LEAK DETECTED");
  }

  leakDetected = leakNow;

  if (leakDetected) {
    unsigned long now = millis();
    if (now - lastLeakBlinkMs >= LEAK_BLINK_INTERVAL_MS) {
      lastLeakBlinkMs = now;
      leakLedState = !leakLedState;
      digitalWrite(LED_BUILTIN, leakLedState ? HIGH : LOW);
    }
  } else {
    leakLedState = false;
    digitalWrite(LED_BUILTIN, LOW);
  }
}

void setRingPwm(int dutyPercent) {
  dutyPercent = constrain(dutyPercent, 0, 100);
  int pwmValue = map(dutyPercent, 0, 100, 0, 255);
  analogWrite(RING_PWM_PIN, pwmValue);

  Serial.print("PWM duty set to ");
  Serial.print(dutyPercent);
  Serial.println("%");
}

void setMotorEnabled(int motorIndex, bool enabled) {
  digitalWrite(pdnPins[motorIndex], enabled ? HIGH : LOW);
}

void printSensorValues() {
  Serial.println("Sensor values:");

  if (pressureSensorReady) {
    pressureSensor.read();

    Serial.print("  Pressure (Bar): ");
    Serial.println(pressureSensor.pressure(KellerLD::bar), 4);

    Serial.print("  Depth (m): ");
    Serial.println(pressureSensor.depth(), 3);
  } else {
    Serial.println("  Pressure/Depth sensor: not detected");
  }

  if (tempSensorReady) {
    tempSensor.read();
    Serial.print("  Temperature (C): ");
    Serial.println(tempSensor.temperature(), 3);
  } else {
    Serial.println("  Temperature sensor: not detected");
  }

  if (pressureSensorReady) {
    Serial.print("  Pressure sensor internal temperature (C): ");
    Serial.println(pressureSensor.temperature(), 3);
  }
}

void setup() {
  // Initialize serial communication
  Serial.begin(115200);
  delay(1000);
  
  // Flash onboard LED 3 times to indicate successful upload
  pinMode(LED_BUILTIN, OUTPUT);
  for (int i = 0; i < 3; i++) {
    digitalWrite(LED_BUILTIN, HIGH);
    delay(200);
    digitalWrite(LED_BUILTIN, LOW);
    delay(200);
  }
  
  Serial.println("OTM v1.3 Firmware - Teensy 4.1");
  Serial.println("Initializing TMC2209 drivers...");

  // Configure ring LED PWM output
  pinMode(RING_PWM_PIN, OUTPUT);
  analogWriteFrequency(RING_PWM_PIN, 1000);
  analogWriteResolution(8);
  setRingPwm(0);

  // Configure leak sensor input
  pinMode(LEAK_SENSOR_PIN, INPUT_PULLDOWN);

  // Initialize I2C bus for Teensy 4.1 pins (SDA=18, SCL=19)
  Wire.setSDA(18);
  Wire.setSCL(19);
  Wire.begin();

  // Initialize pressure/depth sensor (Blue Robotics Bar 10XT via Keller library)
  pressureSensor.init();
  pressureSensor.setFluidDensity(997.0f);  // Freshwater density, kg/m^3
  pressureSensorReady = pressureSensor.isInitialized();

  // Initialize fast-response Celsius I2C temperature sensor (TSYS01)
  tempSensorReady = tempSensor.init();

  Serial.print("Pressure/Depth sensor status: ");
  Serial.println(pressureSensorReady ? "connected" : "not detected");
  Serial.print("Temperature sensor status: ");
  Serial.println(tempSensorReady ? "connected" : "not detected");
  
  // Configure all motor pins
  for (int motor = 0; motor < 4; motor++) {
    pinMode(dirPins[motor], OUTPUT);
    pinMode(stepPins[motor], OUTPUT);
    pinMode(pdnPins[motor], OUTPUT);
    
    // Set initial states
    digitalWrite(dirPins[motor], LOW);
    digitalWrite(stepPins[motor], LOW);
    setMotorEnabled(motor, HOLD_MOTORS_AFTER_MOVE);
    
    Serial.print("Motor ");
    Serial.print(motor + 1);
    Serial.print(" initialized - DIR:");
    Serial.print(dirPins[motor]);
    Serial.print(" STEP:");
    Serial.print(stepPins[motor]);
    Serial.print(" PDN:");
    Serial.println(pdnPins[motor]);
  }
  
  Serial.println("Ready! Send commands: <motor> <pause_us> <steps>");
  Serial.println("Example: 1 100 200 (forward) or 1 100 -200 (backward)");
  Serial.println("Sensor command: v");
  Serial.println("PWM command: p XX (XX = 0-100 duty percent)");
  Serial.print("Motor hold after move: ");
  Serial.println(HOLD_MOTORS_AFTER_MOVE ? "enabled" : "disabled");
  Serial.println("Leak sensor enabled on pin 41");
}

void loop() {
  // Continuously monitor leak sensor
  updateLeakAlarm();

  // Check if serial data is available
  if (Serial.available() > 0) {
    // Read one command line
    String command = Serial.readStringUntil('\n');
    command.trim();

    if (command.length() == 0) {
      return;
    }

    // Sensor command
    if (command.equalsIgnoreCase("v")) {
      printSensorValues();
      return;
    }

    if (command.length() > 0 && (command[0] == 'p' || command[0] == 'P')) {
      int dutyPercent = 0;
      int parsed = sscanf(command.c_str(), "%*c %d", &dutyPercent);

      if (parsed != 1) {
        Serial.println("ERROR: Invalid PWM command format");
        Serial.println("Use: p XX where XX is 0-100");
        return;
      }

      if (dutyPercent < 0 || dutyPercent > 100) {
        Serial.println("ERROR: PWM duty must be 0-100");
        return;
      }

      setRingPwm(dutyPercent);
      return;
    }

    // Parse motor command: <motor> <pause_us> <steps>
    int motorNum = 0;
    int pauseUs = 0;
    int steps = 0;
    int parsed = sscanf(command.c_str(), "%d %d %d", &motorNum, &pauseUs, &steps);

    if (parsed != 3) {
      Serial.println("ERROR: Invalid command format");
      Serial.println("Use: <motor> <pause_us> <steps>, v, or p XX");
      return;
    }
    
    // Validate motor number
    if (motorNum < 1 || motorNum > 4) {
      Serial.println("ERROR: Motor must be 1-4");
      return;
    }
    
    // Validate parameters
    if (pauseUs <= 0 || steps == 0) {
      Serial.println("ERROR: Invalid parameters");
      return;
    }
    
    // Determine direction from sign of steps
    bool forward = (steps > 0);
    int absSteps = abs(steps);
    
    // Convert to 0-indexed
    int motor = motorNum - 1;

    // Keep the driver enabled only while the move is in progress unless holding is requested.
    setMotorEnabled(motor, true);
    
    // Execute the steps
    Serial.print("Stepping motor ");
    Serial.print(motorNum);
    Serial.print(", pause=");
    Serial.print(pauseUs);
    Serial.print("us, steps=");
    Serial.print(absSteps);
    Serial.print(", direction=");
    Serial.println(forward ? "forward" : "backward");
    
    // Set direction
    digitalWrite(dirPins[motor], forward ? HIGH : LOW);
    delayMicroseconds(50);  // Increased direction setup time
    
    // Execute steps with minimum pulse width for TMC2209
    for (int i = 0; i < absSteps; i++) {
      digitalWrite(stepPins[motor], HIGH);
      delayMicroseconds(max(pauseUs, 5));  // Minimum 5us HIGH pulse
      digitalWrite(stepPins[motor], LOW);
      delayMicroseconds(max(pauseUs, 5));  // Minimum 5us LOW pulse
    }

    if (!HOLD_MOTORS_AFTER_MOVE) {
      setMotorEnabled(motor, false);
    }
    
    Serial.println("OK");
  }
}
