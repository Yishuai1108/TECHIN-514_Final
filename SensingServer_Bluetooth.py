#include "MAX30105.h"
#include "heartRate.h"
#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// Pin definitions
#define LED_PIN 9  // LED connected to pin 9
#define COIL_A1 2 // GPIO14 for stepper motor
#define COIL_A2 5 // GPIO13 for stepper motor
#define COIL_B1 3 // GPIO27 for stepper motor
#define COIL_B2 4 // GPIO12 for stepper motor

MAX30105 particleSensor;

// BLE Server
BLEServer* pServer = NULL;
BLECharacteristic* pCharacteristic = NULL;
bool deviceConnected = false;
bool oldDeviceConnected = false;

// Service and Characteristic UUIDs
#define SERVICE_UUID        "5e581872-a389-465c-98cd-dbc5dc8e04c1"
#define CHARACTERISTIC_UUID "144f76b9-5840-4455-b89f-c7589a1e6756"

// Heart rate buffer
const byte RATE_SIZE = 8;  // Increased buffer size for more stable averages
byte rates[RATE_SIZE]; 
byte rateSpot = 0;
long lastBeat = 0; 

float beatsPerMinute;
int beatAvg;
int lastBeatAvg = 0;
unsigned long lastBLENotification = 0;
unsigned long lastMotorMove = 0;
bool motorActive = false;

// Stepper motor step sequence
const int stepSequence[4][4] = {
    {1, 0, 1, 0}, // Step 1
    {0, 1, 1, 0}, // Step 2
    {0, 1, 0, 1}, // Step 3
    {1, 0, 0, 1}  // Step 4
};

void stepMotor(bool clockwise, int steps, int stepDelay) {
    Serial.print("Moving motor ");
    Serial.print(clockwise ? "clockwise" : "counterclockwise");
    Serial.print(" - Steps: ");
    Serial.println(steps);
    
    motorActive = true;
    
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
    motorActive = false;
    lastMotorMove = millis();
}

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

void setup() {
    Serial.begin(115200);
    Serial.println("Initializing Heart Rate Monitor...");

    // Configure pins
    pinMode(LED_PIN, OUTPUT);
    pinMode(COIL_A1, OUTPUT);
    pinMode(COIL_A2, OUTPUT);
    pinMode(COIL_B1, OUTPUT);
    pinMode(COIL_B2, OUTPUT);
    
    // Turn all pins LOW initially
    digitalWrite(LED_PIN, LOW);
    digitalWrite(COIL_A1, LOW);
    digitalWrite(COIL_A2, LOW);
    digitalWrite(COIL_B1, LOW);
    digitalWrite(COIL_B2, LOW);

    // Initialize heart rate sensor with retry
    int sensorInitAttempts = 0;
    while (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
        Serial.println("MAX30105 not found. Retrying...");
        sensorInitAttempts++;
        delay(1000);
        
        if (sensorInitAttempts >= 5) {
            Serial.println("MAX30105 initialization failed. Check wiring/power and reset the device.");
            digitalWrite(LED_PIN, HIGH);  // Turn on LED to indicate error
            delay(500);
            digitalWrite(LED_PIN, LOW);
            delay(500);
        }
    }
    
    Serial.println("MAX30105 found and initialized!");
    Serial.println("Place your finger on the sensor.");

    // Configure sensor with better settings for reliability
    particleSensor.setup();
    particleSensor.setPulseAmplitudeRed(0x1F);  // Increased power for better readings
    particleSensor.setPulseAmplitudeGreen(0);

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
    pCharacteristic->setValue("0");

    pService->start();

    BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
    pAdvertising->addServiceUUID(SERVICE_UUID);
    pAdvertising->setScanResponse(true);
    pAdvertising->setMinPreferred(0x06);  // Helps with iPhone connections
    pAdvertising->setMinPreferred(0x12);
    BLEDevice::startAdvertising();

    Serial.println("BLE server ready. Waiting for connections...");
}

void loop() {
    long irValue = particleSensor.getIR();
    boolean validReading = false;

    // Check for a heartbeat
    if (irValue > 50000 && checkForBeat(irValue)) {
        long delta = millis() - lastBeat;
        lastBeat = millis();

        beatsPerMinute = 60 / (delta / 1000.0);

        // Validate BPM is in reasonable range
        if (beatsPerMinute < 220 && beatsPerMinute > 30) {
            rates[rateSpot++] = (byte)beatsPerMinute;
            rateSpot %= RATE_SIZE;

            // Calculate average BPM
            beatAvg = 0;
            for (byte x = 0; x < RATE_SIZE; x++)
                beatAvg += rates[x];
            beatAvg /= RATE_SIZE;
            
            validReading = true;
        }
    }

    // Print sensor values at a reasonable rate (not every loop)
    static unsigned long lastPrint = 0;
    if (millis() - lastPrint > 1000) {
        Serial.print("IR=");
        Serial.print(irValue);
        Serial.print(", BPM=");
        Serial.print(beatsPerMinute);
        Serial.print(", Avg BPM=");
        Serial.print(beatAvg);

        if (irValue < 50000) {
            Serial.println(" No finger detected");
            digitalWrite(LED_PIN, LOW);
        } else {
            Serial.println(" Reading valid");
        }
        
        lastPrint = millis();
    }

    // Handle BPM threshold actions with debouncing
    if (validReading && beatAvg > 70 && beatAvg != lastBeatAvg) {
        digitalWrite(LED_PIN, HIGH);
        
        // Only move motor if not already active and time since last move > 5 seconds
        if (!motorActive && (millis() - lastMotorMove > 5000)) {
            stepMotor(true, 20, 15);  // clockwise, 20 steps, 15ms delay
        }
        
        // Send heart rate over BLE with rate limiting
        if (deviceConnected && (millis() - lastBLENotification > 2000)) {
            char heartRateStr[10];
            sprintf(heartRateStr, "%d", beatAvg);
            pCharacteristic->setValue(heartRateStr);
            pCharacteristic->notify();
            lastBLENotification = millis();
            Serial.print("Sent heart rate: ");
            Serial.println(heartRateStr);
        }
    } 
    else if (validReading && beatAvg <= 70 && beatAvg != lastBeatAvg) {
        digitalWrite(LED_PIN, LOW);
        
        // Only move motor if not already active and time since last move > 5 seconds
        if (!motorActive && (millis() - lastMotorMove > 5000)) {
            stepMotor(false, 20, 15);  // counter-clockwise, 20 steps, 15ms delay
        }
        
        // Send heart rate over BLE with rate limiting
        if (deviceConnected && (millis() - lastBLENotification > 2000)) {
            char heartRateStr[10];
            sprintf(heartRateStr, "%d", beatAvg);
            pCharacteristic->setValue(heartRateStr);
            pCharacteristic->notify();
            lastBLENotification = millis();
            Serial.print("Sent heart rate: ");
            Serial.println(heartRateStr);
        }
    }
    
    // Save last BPM average for change detection
    if (validReading) {
        lastBeatAvg = beatAvg;
    }

    // Disconnection handling - restart advertising if client disconnected
    if (!deviceConnected && oldDeviceConnected) {
        delay(500); // Give the bluetooth stack time to get ready
        pServer->startAdvertising(); // Restart advertising
        Serial.println("Restarting advertising");
        oldDeviceConnected = deviceConnected;
    }
    
    // Connection handling
    if (deviceConnected && !oldDeviceConnected) {
        oldDeviceConnected = deviceConnected;
    }

    delay(20); // Short delay for stability
}
