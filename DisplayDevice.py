#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>

// Pin definitions - DOUBLE CHECK THESE MATCH YOUR WIRING
#define LED_PIN 10  // LED connected to pin 9
#define COIL_A1 21  // Stepper motor coil A1
#define COIL_A2 5  // Stepper motor coil A2
#define COIL_B1 3  // Stepper motor coil B1
#define COIL_B2 4  // Stepper motor coil B2
#define TOUCH_PIN 2 // Capacitive touch sensor pin

// Service UUID and Characteristic UUID - must match the server exactly
static BLEUUID serviceUUID("5e581872-a389-465c-98cd-dbc5dc8e04c1");
static BLEUUID charUUID("144f76b9-5840-4455-b89f-c7589a1e6756");

// Connection state variables
static boolean doConnect = false;
static boolean connected = false;
static boolean scanning = false;
static BLERemoteCharacteristic* pRemoteCharacteristic;
static BLEAdvertisedDevice* myDevice;
unsigned long lastConnectionAttempt = 0;
const int CONNECTION_RETRY_INTERVAL = 5000; // 5 seconds between connection attempts

// Variables to track sensor states
int serverHeartRate = 0;
int serverTouchState = 0;
int serverMotorPosition = 0;
int localTouchState = 0;
bool sensorTriggered = false;
bool lastSensorTriggered = false;
unsigned long lastTouchRead = 0;
unsigned long lastStatusPrint = 0;

// Motor state tracking
bool motorAtForwardPosition = false;
unsigned long lastMotorMove = 0;
bool motorBusy = false;

// SIMPLIFIED MOTOR CONTROL - Direct approach
void moveMotorForward() {
    if (motorAtForwardPosition) {
        Serial.println("Motor already at forward position");
        return;
    }
  
    Serial.println("Moving motor FORWARD");
    motorBusy = true;
    
    // Step sequence to move forward
    for (int i = 0; i < 200; i++) { // Adjust steps as needed (200 is example)
        // Step 1
        digitalWrite(COIL_A1, HIGH);
        digitalWrite(COIL_A2, LOW);
        digitalWrite(COIL_B1, HIGH);
        digitalWrite(COIL_B2, LOW);
        delay(10);
        
        // Step 2
        digitalWrite(COIL_A1, LOW);
        digitalWrite(COIL_A2, HIGH);
        digitalWrite(COIL_B1, HIGH);
        digitalWrite(COIL_B2, LOW);
        delay(10);
        
        // Step 3
        digitalWrite(COIL_A1, LOW);
        digitalWrite(COIL_A2, HIGH);
        digitalWrite(COIL_B1, LOW);
        digitalWrite(COIL_B2, HIGH);
        delay(10);
        
        // Step 4
        digitalWrite(COIL_A1, HIGH);
        digitalWrite(COIL_A2, LOW);
        digitalWrite(COIL_B1, LOW);
        digitalWrite(COIL_B2, HIGH);
        delay(10);
    }
    
    // Turn off all coils to save power and reduce heat
    digitalWrite(COIL_A1, LOW);
    digitalWrite(COIL_A2, LOW);
    digitalWrite(COIL_B1, LOW);
    digitalWrite(COIL_B2, LOW);
    
    motorAtForwardPosition = true;
    motorBusy = false;
    lastMotorMove = millis();
    Serial.println("Motor is now at FORWARD position");
}

void moveMotorBackward() {
    if (!motorAtForwardPosition) {
        Serial.println("Motor already at backward position");
        return;
    }
  
    Serial.println("Moving motor BACKWARD");
    motorBusy = true;
    
    // Step sequence to move backward
    for (int i = 0; i < 200; i++) { // Adjust steps as needed (200 is example)
        // Step 4
        digitalWrite(COIL_A1, HIGH);
        digitalWrite(COIL_A2, LOW);
        digitalWrite(COIL_B1, LOW);
        digitalWrite(COIL_B2, HIGH);
        delay(10);
        
        // Step 3
        digitalWrite(COIL_A1, LOW);
        digitalWrite(COIL_A2, HIGH);
        digitalWrite(COIL_B1, LOW);
        digitalWrite(COIL_B2, HIGH);
        delay(10);
        
        // Step 2
        digitalWrite(COIL_A1, LOW);
        digitalWrite(COIL_A2, HIGH);
        digitalWrite(COIL_B1, HIGH);
        digitalWrite(COIL_B2, LOW);
        delay(10);
        
        // Step 1
        digitalWrite(COIL_A1, HIGH);
        digitalWrite(COIL_A2, LOW);
        digitalWrite(COIL_B1, HIGH);
        digitalWrite(COIL_B2, LOW);
        delay(10);
    }
    
    // Turn off all coils to save power and reduce heat
    digitalWrite(COIL_A1, LOW);
    digitalWrite(COIL_A2, LOW);
    digitalWrite(COIL_B1, LOW);
    digitalWrite(COIL_B2, LOW);
    
    motorAtForwardPosition = false;
    motorBusy = false;
    lastMotorMove = millis();
    Serial.println("Motor is now at BACKWARD position");
}

// Test motor function
void testMotor() {
    Serial.println("TESTING MOTOR - FORWARD");
    moveMotorForward();
    
    delay(1000);
    
    Serial.println("TESTING MOTOR - BACKWARD");
    moveMotorBackward();
    
    Serial.println("Motor test complete!");
}

// Check if any sensor is triggered
bool checkSensorsTrigger() {
    return (serverTouchState == 1 || localTouchState == HIGH || 
            serverMotorPosition == 1);
}

// Notification callback function to handle data from server
static void notifyCallback(
  BLERemoteCharacteristic* pBLERemoteCharacteristic,
  uint8_t* pData,
  size_t length,
  bool isNotify) {
    // Convert received data to string
    char dataStr[length + 1];
    memcpy(dataStr, pData, length);
    dataStr[length] = 0; // Null terminator
    
    // Parse the data (format: "heartRate,touchState,motorPosition")
    String data = String(dataStr);
    int commaIndex1 = data.indexOf(',');
    
    if (commaIndex1 > 0) {
        // Get heart rate
        String heartRateStr = data.substring(0, commaIndex1);
        serverHeartRate = heartRateStr.toInt();
        
        // Get touch state from server
        int commaIndex2 = data.indexOf(',', commaIndex1 + 1);
        String touchStateStr = data.substring(commaIndex1 + 1, commaIndex2);
        serverTouchState = touchStateStr.toInt();
        
        // Get motor position from server
        if (commaIndex2 > 0) {
            String positionStr = data.substring(commaIndex2 + 1);
            serverMotorPosition = positionStr.toInt();
        }
        
        Serial.print("Received: HR=");
        Serial.print(serverHeartRate);
        Serial.print(", Server Touch=");
        Serial.print(serverTouchState == 1 ? "DETECTED" : "NOT DETECTED");
        Serial.print(", Server Motor=");
        Serial.println(serverMotorPosition == 1 ? "FORWARD" : "BACKWARD");
        
        // Update the triggered status based on server data
        lastSensorTriggered = sensorTriggered;
        sensorTriggered = checkSensorsTrigger();
        
        // Handle trigger state change
        if (sensorTriggered != lastSensorTriggered) {
            Serial.print("SENSOR TRIGGER STATE CHANGED TO: ");
            Serial.println(sensorTriggered ? "TRIGGERED" : "NOT TRIGGERED");
            
            // Update LED immediately based on sensor state
            digitalWrite(LED_PIN, sensorTriggered ? HIGH : LOW);
            
            // Move motor based on trigger state
            if (sensorTriggered) {
                if (!motorBusy && !motorAtForwardPosition) {
                    moveMotorForward();
                }
            } else {
                if (!motorBusy && motorAtForwardPosition) {
                    moveMotorBackward();
                }
            }
        }
    }
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
    // Reset sensor values
    serverHeartRate = 0;
    serverTouchState = 0;
    serverMotorPosition = 0;
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

    // Connect to the remote BLE Server
    if (!pClient->connect(myDevice)) {
        Serial.println("Connection failed");
        return false;
    }
    
    Serial.println("Connected to server");
    pClient->setMTU(517); // Request maximum MTU

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

void setup() {
  Serial.begin(115200);
  Serial.println("\n\n--- BLE Heart Rate Client Starting ---");
  
  // Initialize IO pins
  pinMode(LED_PIN, OUTPUT);
  pinMode(COIL_A1, OUTPUT);
  pinMode(COIL_A2, OUTPUT);
  pinMode(COIL_B1, OUTPUT);
  pinMode(COIL_B2, OUTPUT);
  pinMode(TOUCH_PIN, INPUT);
  
  // Turn off LED and stepper motor pins initially
  digitalWrite(LED_PIN, LOW);
  digitalWrite(COIL_A1, LOW);
  digitalWrite(COIL_A2, LOW);
  digitalWrite(COIL_B1, LOW);
  digitalWrite(COIL_B2, LOW);
  
  // IMPORTANT: Test motor function first to ensure it's working
  testMotor();
  
  // Initialize BLE client
  BLEDevice::init("HeartRateClient");
  
  // Start scan for heart rate server
  BLEScan* pBLEScan = BLEDevice::getScan();
  pBLEScan->setAdvertisedDeviceCallbacks(new MyAdvertisedDeviceCallbacks());
  pBLEScan->setInterval(1349);
  pBLEScan->setWindow(449);
  pBLEScan->setActiveScan(true);
  
  Serial.println("Starting BLE scan...");
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

  // Read local touch sensor
  if (millis() - lastTouchRead > 50) {  // Read every 50ms
      int newTouchState = digitalRead(TOUCH_PIN);
      if (localTouchState != newTouchState) {
          localTouchState = newTouchState;
          Serial.print("Local touch sensor state changed to: ");
          Serial.println(localTouchState == HIGH ? "TOUCHED" : "NOT TOUCHED");
          
          // Update sensor triggered state with local sensor
          lastSensorTriggered = sensorTriggered;
          sensorTriggered = checkSensorsTrigger();
          
          // Handle trigger state change
          if (sensorTriggered != lastSensorTriggered) {
              Serial.print("SENSOR TRIGGER STATE CHANGED TO: ");
              Serial.println(sensorTriggered ? "TRIGGERED" : "NOT TRIGGERED");
              
              // Update LED immediately based on sensor state
              digitalWrite(LED_PIN, sensorTriggered ? HIGH : LOW);
              
              // Move motor based on trigger state
              if (sensorTriggered) {
                  if (!motorBusy && !motorAtForwardPosition) {
                      moveMotorForward();
                  }
              } else {
                  if (!motorBusy && motorAtForwardPosition) {
                      moveMotorBackward();
                  }
              }
          }
      }
      lastTouchRead = millis();
  }

  // Print status periodically
  if (connected && millis() - lastStatusPrint > 5000) {
    Serial.print("Status: Heart Rate=");
    Serial.print(serverHeartRate);
    Serial.print(", Server Touch=");
    Serial.print(serverTouchState == 1 ? "DETECTED" : "NOT DETECTED");
    Serial.print(", Local Touch=");
    Serial.print(localTouchState == HIGH ? "DETECTED" : "NOT DETECTED");
    Serial.print(", Motor=");
    Serial.println(motorAtForwardPosition ? "FORWARD" : "BACKWARD");
    lastStatusPrint = millis();
  }

  // Small delay for stability
  delay(20);
}