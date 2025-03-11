#include <Wire.h>
#include "MAX30105.h"
#include "heartRate.h"
#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// Pin definitions - DOUBLE CHECK THESE MATCH YOUR WIRING
#define LED_PIN 10       // LED connected to pin 9
#define COIL_A1 21       // Stepper motor coil A1
#define COIL_A2 5       // Stepper motor coil A2
#define COIL_B1 3       // Stepper motor coil B1
#define COIL_B2 4       // Stepper motor coil B2
#define TOUCH_PIN 2    // Capacitive touch sensor connected to GPIO20

MAX30105 particleSensor;

// BLE Server
BLEServer* pServer = NULL;
BLECharacteristic* pCharacteristic = NULL;
bool deviceConnected = false;

// Service and Characteristic UUIDs
#define SERVICE_UUID        "5e581872-a389-465c-98cd-dbc5dc8e04c1"
#define CHARACTERISTIC_UUID "144f76b9-5840-4455-b89f-c7589a1e6756"

// Heart rate variables
int beatAvg = 0;
unsigned long lastBLENotification = 0;

// Sensor state tracking
bool sensorTriggered = false;
bool lastSensorTriggered = false;

// Capacitive touch variables
int touchState = 0;
int lastTouchState = 0;
unsigned long lastTouchRead = 0;

// Motor state tracking
bool motorAtForwardPosition = false;
unsigned long lastMotorMove = 0;
bool motorBusy = false;

// BLE Server Callbacks
class MyServerCallbacks : public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) {
        deviceConnected = true;
        Serial.println("Client connected");
    };

    void onDisconnect(BLEServer* pServer) {
        deviceConnected = false;
        Serial.println("Client disconnected");
    }
};

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

// Function to check if sensors are triggered
bool checkSensorsTrigger() {
    // Check if capacitive touch sensor is touched
    bool touchDetected = (touchState == HIGH);
    
    // Check if finger is detected on heart rate sensor (IR value > 50000)
    long irValue = particleSensor.getIR();
    bool fingerDetected = (irValue > 50000);
    
    // Return true if either sensor is triggered
    return touchDetected || fingerDetected;
}

// Function to send BLE notification with sensor status
void sendSensorStatus() {
    if (deviceConnected && (millis() - lastBLENotification > 1000)) {
        String statusStr = String(beatAvg) + "," + String(touchState) + "," + String(motorAtForwardPosition ? 1 : 0);
        pCharacteristic->setValue(statusStr.c_str());
        pCharacteristic->notify();
        lastBLENotification = millis();
        Serial.print("Sent status: ");
        Serial.println(statusStr);
    }
}

void setup() {
    Serial.begin(115200);
    Serial.println("Initializing Heart Rate Monitor, Touch Sensor, and Motor...");

    // Configure pins
    pinMode(LED_PIN, OUTPUT);
    pinMode(COIL_A1, OUTPUT);
    pinMode(COIL_A2, OUTPUT);
    pinMode(COIL_B1, OUTPUT);
    pinMode(COIL_B2, OUTPUT);
    pinMode(TOUCH_PIN, INPUT);
    
    // Turn all pins LOW initially
    digitalWrite(LED_PIN, LOW);
    digitalWrite(COIL_A1, LOW);
    digitalWrite(COIL_A2, LOW);
    digitalWrite(COIL_B1, LOW);
    digitalWrite(COIL_B2, LOW);

    // IMPORTANT: Test motor function first to ensure it's working
    testMotor();
    
    // Initialize heart rate sensor with retry
    int sensorInitAttempts = 0;
    while (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
        Serial.println("MAX30105 not found. Retrying...");
        sensorInitAttempts++;
        delay(1000);
        
        if (sensorInitAttempts >= 5) {
            Serial.println("MAX30105 initialization failed. Check wiring/power and reset the device.");
            // Blink LED to indicate error
            for (int i = 0; i < 5; i++) {
                digitalWrite(LED_PIN, HIGH);
                delay(200);
                digitalWrite(LED_PIN, LOW);
                delay(200);
            }
            break;  // Continue anyway, motor might still work
        }
    }
    
    if (sensorInitAttempts < 5) {
        Serial.println("MAX30105 found and initialized!");
        // Configure sensor with better settings for reliability
        particleSensor.setup();
        particleSensor.setPulseAmplitudeRed(0x1F);  // Increased power for better readings
        particleSensor.setPulseAmplitudeGreen(0);
    }
    
    Serial.println("Place your finger on the sensor or touch the capacitive sensor.");

    // Initialize BLE
    BLEDevice::init("HeartRate-ESP32");
    pServer = BLEDevice::createServer();
    pServer->setCallbacks(new MyServerCallbacks());

    BLEService *pService = pServer->createService(SERVICE_UUID);
    pCharacteristic = pService->createCharacteristic(
        CHARACTERISTIC_UUID,
        BLECharacteristic::PROPERTY_READ |
        BLECharacteristic::PROPERTY_WRITE |
        BLECharacteristic::PROPERTY_NOTIFY
    );

    pCharacteristic->addDescriptor(new BLE2902());
    pCharacteristic->setValue("0,0,0");  // Format: "heartRate,touchState,motorPosition"

    pService->start();

    BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
    pAdvertising->addServiceUUID(SERVICE_UUID);
    pAdvertising->setScanResponse(true);
    pAdvertising->setMinPreferred(0x06);
    BLEDevice::startAdvertising();

    Serial.println("BLE server ready. Waiting for connections...");
}

void loop() {
    // Read capacitive touch sensor (with debounce)
    if (millis() - lastTouchRead > 50) {  // Read every 50ms
        touchState = digitalRead(TOUCH_PIN);
        if (touchState != lastTouchState) {
            Serial.print("Touch sensor state changed to: ");
            Serial.println(touchState == HIGH ? "TOUCHED" : "NOT TOUCHED");
            lastTouchState = touchState;
        }
        lastTouchRead = millis();
    }

    // Check if sensors are triggered
    sensorTriggered = checkSensorsTrigger();
    
    // Handle sensor trigger state change
    if (sensorTriggered != lastSensorTriggered) {
        if (sensorTriggered) {
            // Sensor triggered - turn ON LED and move motor forward
            Serial.println("Sensor triggered! Activating outputs");
            digitalWrite(LED_PIN, HIGH);
            
            // Only move motor if not already busy and time since last move > 1 second
            if (!motorBusy && (millis() - lastMotorMove > 1000)) {
                moveMotorForward();
            }
        } else {
            // Sensor not triggered - turn OFF LED and move motor backward
            Serial.println("Sensor not triggered! Deactivating outputs");
            digitalWrite(LED_PIN, LOW);
            
            // Only move motor if not already busy and time since last move > 1 second
            if (!motorBusy && (millis() - lastMotorMove > 1000)) {
                moveMotorBackward();
            }
        }
        
        // Update last state
        lastSensorTriggered = sensorTriggered;
        
        // Send status update over BLE
        sendSensorStatus();
    }
    
    // Also send periodic updates over BLE
    if (millis() - lastBLENotification > 2000) {
        sendSensorStatus();
    }

    // Small delay for stability
    delay(20);
}