/*
 * OTM v1.1 Firmware for Teensy 4.1
 * Controls 4 TMC2209 Stepper Motor Drivers via Serial
 * 
 * Command format: <motor_number> <pause_us> <steps>
 * Example: "1 100 200" = Motor 1, 100us delay, 200 steps forward
 *          "1 100 -200" = Motor 1, 100us delay, 200 steps backward
 * Use positive steps for forward, negative steps for backward
 */

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
  
  Serial.println("OTM v1.1 Firmware - Teensy 4.1");
  Serial.println("Initializing TMC2209 drivers...");
  
  // Configure all motor pins
  for (int motor = 0; motor < 4; motor++) {
    pinMode(dirPins[motor], OUTPUT);
    pinMode(stepPins[motor], OUTPUT);
    pinMode(pdnPins[motor], OUTPUT);
    
    // Set initial states
    digitalWrite(dirPins[motor], LOW);
    digitalWrite(stepPins[motor], LOW);
    digitalWrite(pdnPins[motor], HIGH);  // HIGH = driver enabled, LOW = power down
    
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
}

void loop() {
  // Check if serial data is available
  if (Serial.available() > 0) {
    // Read the incoming command
    int motorNum = Serial.parseInt();
    int pauseUs = Serial.parseInt();
    int steps = Serial.parseInt();
    
    // Wait for newline to complete the command
    while (Serial.available() > 0) {
      Serial.read();
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
    
    // Execute the steps
    Serial.print("Stepping motor ");
    Serial.print(motorNum);
    Serial.print(", pause=");
    Serial.print(pauseUs);
    Serial.print("us, steps=");
    Serial.print(absSteps);
    Serial.print(", direction=");
    Serial.println(forward ? "forward" : "backward");
    
    // Turn on LED for motor 1
    if (motorNum == 1) {
      digitalWrite(LED_BUILTIN, HIGH);
    }
    
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
    
    // Turn off LED for motor 1
    if (motorNum == 1) {
      delay(1000);  // Keep LED on for 1 second
      digitalWrite(LED_BUILTIN, LOW);
    }
    
    Serial.println("OK");
  }
}
