#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>

// LED and Stepper motor pins - MAKE SURE THESE MATCH YOUR WIRING
#define LED_PIN 9  // LED connected to pin 9
#define COIL_A1 2  // Stepper motor coil A1
#define COIL_A2 5  // Stepper motor coil A2
#define COIL_B1 3  // Stepper motor coil B1
#define COIL_B2 4  // Stepper motor coil B2

// Service UUID and Characteristic UUID - must match the server exactly
static BLEUUID serviceUUID("5e581872-a389-465c-98cd-dbc5dc8e04c1");
static BLEUUID charUUID("144f76b9-5840-4455-b89f-c7589a1e6756");

// Stepper motor step sequence (full step mode)
const int stepSequence[4][4] = {
    {1, 0, 1, 0}, // Step 1
    {0, 1, 1, 0}, // Step 2
    {0, 1, 0, 1}, // Step 3
    {1, 0, 0, 1}  // Step 4
};

// Connection state variables
static boolean doConnect = false;
static boolean connected = false;
static boolean scanning = false;
static BLERemoteCharacteristic* pRemoteCharacteristic;
static BLEAdvertisedDevice* myDevice;
unsigned long lastConnectionAttempt = 0;
const int CONNECTION_RETRY_INTERVAL = 5000; // 5 seconds between connection attempts

// Variables to track heart rate and device state
int currentHeartRate = 0;
int previousHeartRate = 0;
bool highHeartRate = false;      // Track if heart rate is high
bool previousHighHeartRate = false;
unsigned long lastLedToggle = 0;
bool ledState = false;
int ledBlinkCount = 0;
bool motorMoving = false;        // Flag to indicate motor is currently moving
unsigned long lastMotorMove = 0;
unsigned long lastHeartRateUpdate = 0;

// Notification callback function to handle data from server
static void notifyCallback(
  BLERemoteCharacteristic* pBLERemoteCharacteristic,
  uint8_t* pData,
  size_t length,
  bool isNotify) {
    // Convert received data to string
    char heartRateStr[length + 1];
    memcpy(heartRateStr, pData, length);
    heartRateStr[length] = 0; // Null terminator
    
    // Parse the heart rate value
    previousHeartRate = currentHeartRate;
    currentHeartRate = atoi(heartRateStr);
    lastHeartRateUpdate = millis();
    
    Serial.print("Received heart rate: ");
    Serial.println(currentHeartRate);
    
    // Check heart rate threshold and update flags
    previousHighHeartRate = highHeartRate;
    highHeartRate = (currentHeartRate >= 70);
    
    if (highHeartRate && !previousHighHeartRate) {
        Serial.println("HIGH heart rate detected");
        ledBlinkCount = 0;  // Reset blink counter for new high heart rate event
    } 
    else if (!highHeartRate && previousHighHeartRate) {
        Serial.println("LOW heart rate detected");
        digitalWrite(LED_PIN, LOW); // Turn off LED immediately when heart rate drops
    }
}

// Function to control the stepper motor
void stepMotor(bool clockwise, int steps, int stepDelay) {
    if (motorMoving) return; // Prevent interrupting an ongoing movement
    
    Serial.print("Moving motor ");
    Serial.print(clockwise ? "clockwise" : "counterclockwise");
    Serial.print(" - Steps: ");
    Serial.println(steps);
    
    motorMoving = true;
    
    for (int i = 0; i < steps; i++) {
        for (int step = 0; step < 4; step++) {
            int s = clockwise ? step : (3 - step); // Direction control
            
            digitalWrite(COIL_A1, stepSequence[s][0] ? HIGH : LOW);
            digitalWrite(COIL_A2, stepSequence[s][1] ? HIGH : LOW);
            digitalWrite(COIL_B1, stepSequence[s][2] ? HIGH : LOW);
            digitalWrite(COIL_B2, stepSequence[s][3] ? HIGH : LOW);
            delay(stepDelay);
        }
    }
    
    // Turn off all coils to save power and reduce heat
    digitalWrite(COIL_A1, LOW);
    digitalWrite(COIL_A2, LOW);
    digitalWrite(COIL_B1, LOW);
    digitalWrite(COIL_B2, LOW);
    
    Serial.println("Motor movement complete");
    motorMoving = false;
    lastMotorMove = millis();
}

class MyClientCallback : public BLEClientCallbacks {
  void onConnect(BLEClient* pclient) {
    connected = true;
    Serial.println("Connected to heart rate server");
  }

  void onDisconnect(BLEClient* pclient) {
    connected = false;
    Serial.println("Disconnected from server");
    // Turn off LED when disconnected
    digitalWrite(LED_PIN, LOW);
    // Reset heart rate values
    currentHeartRate = 0;
    previousHeartRate = 0;
    highHeartRate = false;
    previousHighHeartRate = false;
  }
};

bool connectToServer() {
    if (myDevice == nullptr) {
        Serial.println("No device to connect to");
        return false;
    }
    
    Serial.print("Connecting to ");
    Serial.println(myDevice->getAddress().toString().c_str());

    BLEClient* pClient = BLEDevice::createClient();
    Serial.println("Created client");

    pClient->setClientCallbacks(new MyClientCallback());

    // Connect to the remote BLE Server with timeout
    if (!pClient->connect(myDevice)) {
        Serial.println("Connection failed");
        return false;
    }
    
    Serial.println("Connected to server");
    pClient->setMTU(517); // Set client to request maximum MTU from server

    // Obtain a reference to the service we are after in the remote BLE server
    BLERemoteService* pRemoteService = pClient->getService(serviceUUID);
    if (pRemoteService == nullptr) {
      Serial.print("Failed to find our service UUID: ");
      Serial.println(serviceUUID.toString().c_str());
      pClient->disconnect();
      return false;
    }
    Serial.println("Found our service");

    // Obtain a reference to the characteristic in the service of the remote BLE server
    pRemoteCharacteristic = pRemoteService->getCharacteristic(charUUID);
    if (pRemoteCharacteristic == nullptr) {
      Serial.print("Failed to find our characteristic UUID: ");
      Serial.println(charUUID.toString().c_str());
      pClient->disconnect();
      return false;
    }
    Serial.println("Found our characteristic");

    // Read the value of the characteristic
    if(pRemoteCharacteristic->canRead()) {
      String value = pRemoteCharacteristic->readValue();
      Serial.print("Initial characteristic value: ");
      Serial.println(value.c_str());
      
      // Parse initial heart rate
      currentHeartRate = value.toInt();
      previousHeartRate = currentHeartRate;
      highHeartRate = (currentHeartRate >= 70);
      previousHighHeartRate = highHeartRate;
      lastHeartRateUpdate = millis();
    }

    if(pRemoteCharacteristic->canNotify()) {
      pRemoteCharacteristic->registerForNotify(notifyCallback);
      Serial.println("Registered for notifications");
    }

    return true;
}

// Scan for BLE servers
class MyAdvertisedDeviceCallbacks: public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice advertisedDevice) {
    Serial.print("BLE Device found: ");
    Serial.println(advertisedDevice.toString().c_str());

    // Check if this is the device we're looking for
    if (advertisedDevice.haveServiceUUID() && advertisedDevice.isAdvertisingService(serviceUUID)) {
      BLEDevice::getScan()->stop();
      scanning = false;
      
      // Save device for connection
      if (myDevice != nullptr) {
        delete myDevice;
      }
      myDevice = new BLEAdvertisedDevice(advertisedDevice);
      doConnect = true;
      
      Serial.println("Found HeartRate-ESP32 device. Will attempt to connect.");
    }
  }
};

// Debug function to check all pins
void testPins() {
    Serial.println("Testing stepper motor pins...");
    
    // Test each pin individually
    for (int pin : {COIL_A1, COIL_A2, COIL_B1, COIL_B2}) {
        Serial.print("Testing pin ");
        Serial.println(pin);
        digitalWrite(pin, HIGH);
        delay(300);
        digitalWrite(pin, LOW);
        delay(100);
    }
    
    // Test LED
    Serial.println("Testing LED");
    digitalWrite(LED_PIN, HIGH);
    delay(500);
    digitalWrite(LED_PIN, LOW);
    
    Serial.println("Pin test complete");
}

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 3000); // Short wait for serial to initialize
  
  Serial.println("\n\n--- BLE Heart Rate Client Starting ---");
  
  // Initialize IO pins
  pinMode(LED_PIN, OUTPUT);
  pinMode(COIL_A1, OUTPUT);
  pinMode(COIL_A2, OUTPUT);
  pinMode(COIL_B1, OUTPUT);
  pinMode(COIL_B2, OUTPUT);
  
  // Turn off LED and stepper motor pins initially
  digitalWrite(LED_PIN, LOW);
  digitalWrite(COIL_A1, LOW);
  digitalWrite(COIL_A2, LOW);
  digitalWrite(COIL_B1, LOW);
  digitalWrite(COIL_B2, LOW);
  
  // Test pins
  testPins();
  
  // Initialize BLE client
  BLEDevice::init("HeartRateClient");
  
  // Start scan for heart rate server
  BLEScan* pBLEScan = BLEDevice::getScan();
  pBLEScan->setAdvertisedDeviceCallbacks(new MyAdvertisedDeviceCallbacks());
  pBLEScan->setInterval(1349);
  pBLEScan->setWindow(449);
  pBLEScan->setActiveScan(true);
  
  Serial.println("Starting initial BLE scan...");
  scanning = true;
  pBLEScan->start(10, false); // 10-second initial scan
}

void loop() {
  // Attempt connection if device found
  if (doConnect) {
    if (connectToServer()) {
      Serial.println("Connected to the BLE Server successfully");
      doConnect = false;
      lastConnectionAttempt = millis();
    } else {
      Serial.println("Failed to connect to the server");
      doConnect = false;
      lastConnectionAttempt = millis();
      // Wait a bit before trying to scan again
      delay(1000);
      scanning = false;
    }
  }

  // If not connected and not scanning, start scan after delay
  if (!connected && !scanning && (millis() - lastConnectionAttempt > CONNECTION_RETRY_INTERVAL)) {
    Serial.println("Starting new BLE scan...");
    BLEDevice::getScan()->start(5, false);
    scanning = true;
    lastConnectionAttempt = millis();
  }

  // Handle heart rate data and control outputs
  if (connected) {
    unsigned long currentMillis = millis();
    
    // No need to disconnect if no heart rate updates were received for 10 seconds
    // Simply skip the disconnect logic and keep the connection alive
    if (currentMillis - lastHeartRateUpdate > 10000) {
      Serial.println("No heart rate updates received for 10 seconds, but staying connected...");
    }
    
    // Handle high heart rate condition
    if (highHeartRate) {
      // Blink LED twice when heart rate first becomes high
      if (ledBlinkCount < 4 && (currentMillis - lastLedToggle >= 250)) { // 250ms toggle rate
        lastLedToggle = currentMillis;
        ledState = !ledState;
        digitalWrite(LED_PIN, ledState);
        ledBlinkCount++;
        
        // After completing 2 blinks (4 toggles), keep LED on
        if (ledBlinkCount >= 4) {
          digitalWrite(LED_PIN, HIGH);
        }
      }
      
      // Move motor clockwise when heart rate first becomes high
      if (highHeartRate != previousHighHeartRate && !motorMoving && (currentMillis - lastMotorMove > 2000)) {
        Serial.println("Moving motor CLOCKWISE for HIGH heart rate");
        stepMotor(true, 50, 15); // Clockwise, 50 steps, 15ms delay
      }
    } 
    // Handle low heart rate condition
    else {
      // Turn off LED when heart rate is low
      digitalWrite(LED_PIN, LOW);
      
      // Move motor counter-clockwise when heart rate first becomes low
      if (highHeartRate != previousHighHeartRate && !motorMoving && (currentMillis - lastMotorMove > 2000)) {
        Serial.println("Moving motor COUNTERCLOCKWISE for LOW heart rate");
        stepMotor(false, 50, 15); // Counter-clockwise, 50 steps, 15ms delay
      }
    }
  }

  delay(50); // Short delay for stability
}

