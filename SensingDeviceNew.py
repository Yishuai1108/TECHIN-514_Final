/*
  BLE Heart Rate & Hydration Monitor Server
  Reads heart rate data from MAX30102 sensor and hydration status from capacitive touch sensor
  Sends both data points to a client via BLE
  
  Hardware:
  - ESP32 XIAO
  - MAX30102 Heart Rate Sensor
  - TTP223B Capacitive Touch Sensor (connected to GPIO2)
  
  Connections:
  - MAX30102 SDA to ESP32 SDA
  - MAX30102 SCL to ESP32 SCL
  - MAX30102 VIN to ESP32 3.3V
  - MAX30102 GND to ESP32 GND
  - TTP223B SIG to ESP32 GPIO2
  - TTP223B VCC to ESP32 3.3V
  - TTP223B GND to ESP32 GND
*/

#include <Arduino.h>
#include <Wire.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include "MAX30105.h"
#include "heartRate.h"

// Define touch sensor pin
#define TOUCH_PIN 2  // TTP223B SIG connected to GPIO2

// BLE Server Variables
BLEServer* pServer = NULL;
BLECharacteristic* pCharacteristic = NULL;
bool deviceConnected = false;
bool oldDeviceConnected = false;

// UUIDs - MUST match the client
#define SERVICE_UUID "153d58a2-6e5d-46b3-8df2-7288b3ef3c4e"
#define CHARACTERISTIC_UUID "537a9060-3f8a-4cd9-86ce-a9cd306bc3cb"

// MAX30102 Sensor
MAX30105 particleSensor;

// Heart Rate Variables
const byte RATE_SIZE = 4; // Increase for more averaging. 4 is good
byte rates[RATE_SIZE]; // Array of heart rates
byte rateSpot = 0;
long lastBeat = 0; // Time at which the last beat occurred
float beatsPerMinute;
int beatAvg;

// Hydration Variables
bool isHydrated = false;

// Timing Variables
unsigned long previousMillis = 0;
const long UPDATE_INTERVAL = 100; // Send data every 100ms

// BLE Server Callbacks
class MyServerCallbacks: public BLEServerCallbacks {
  void onConnect(BLEServer* pServer) {
    deviceConnected = true;
    Serial.println("Device Connected!");
  };

  void onDisconnect(BLEServer* pServer) {
    deviceConnected = false;
    Serial.println("Device Disconnected! Restarting advertisement...");
    // Restart advertising when client disconnects
    BLEDevice::startAdvertising();
  }
};

void setup() {
  Serial.begin(115200);
  Serial.println("Initializing Heart Rate & Hydration Monitor Server...");

  // Initialize touch sensor pin
  pinMode(TOUCH_PIN, INPUT);
  Serial.println("Touch sensor initialized");

  // Initialize MAX30102 sensor
  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("MAX30105 was not found. Please check wiring/power.");
    while (1);
  }
  Serial.println("MAX30105 sensor initialized");

  // Configure MAX30102 with default settings
  particleSensor.setup(); 
  particleSensor.setPulseAmplitudeRed(0x0A); // Turn Red LED to low to indicate sensor is running
  particleSensor.setPulseAmplitudeGreen(0); // Turn off Green LED
  
  // Initialize BLE Device
  BLEDevice::init("HR_Monitor");
  
  // Create BLE Server
  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new MyServerCallbacks());
  
  // Create BLE Service
  BLEService *pService = pServer->createService(SERVICE_UUID);
  
  // Create BLE Characteristic
  pCharacteristic = pService->createCharacteristic(
                      CHARACTERISTIC_UUID,
                      BLECharacteristic::PROPERTY_READ |
                      BLECharacteristic::PROPERTY_WRITE |
                      BLECharacteristic::PROPERTY_NOTIFY
                    );
  
  // Create a BLE Descriptor
  pCharacteristic->addDescriptor(new BLE2902());
  
  // Start the service
  pService->start();
  
  // Start advertising
  BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(SERVICE_UUID);
  pAdvertising->setScanResponse(true);
  pAdvertising->setMinPreferred(0x06);  // functions that help with iPhone connections
  pAdvertising->setMinPreferred(0x12);
  BLEDevice::startAdvertising();
  
  Serial.println("BLE Heart Rate & Hydration Monitor Server Ready");
  Serial.println("Place your finger on the sensor with steady pressure.");
}

void loop() {
  // Read heart rate from the sensor
  long irValue = particleSensor.getIR();
  
  // Check if a heartbeat is detected
  if (checkForBeat(irValue) == true) {
    // We sensed a beat!
    long delta = millis() - lastBeat;
    lastBeat = millis();
    
    beatsPerMinute = 60 / (delta / 1000.0);
    
    if (beatsPerMinute < 255 && beatsPerMinute > 20) {
      rates[rateSpot++] = (byte)beatsPerMinute; // Store this reading in the array
      rateSpot %= RATE_SIZE; // Wrap variable
      
      // Take average of readings
      beatAvg = 0;
      for (byte x = 0; x < RATE_SIZE; x++)
        beatAvg += rates[x];
      beatAvg /= RATE_SIZE;
    }
  }
  
  // Read from the touch sensor
  int touchState = digitalRead(TOUCH_PIN);
  isHydrated = (touchState == HIGH);
  
  // Create message to send via BLE
  String message;
  
  // Check if we have a valid heart rate reading
  int currentHR = 0;
  if (irValue < 50000) {
    currentHR = 0; // No finger detected
    Serial.println("No finger detected");
  } else {
    currentHR = beatAvg > 0 ? beatAvg : (int)beatsPerMinute;
    Serial.print("IR=");
    Serial.print(irValue);
    Serial.print(", BPM=");
    Serial.print(beatsPerMinute);
    Serial.print(", Avg BPM=");
    Serial.print(beatAvg);
  }
  
  // Format message with HR and hydration status
  // Format: "HR:X,HYD:Y" where X is heart rate and Y is 1 (hydrated) or 0 (not hydrated)
  message = "HR:" + String(currentHR) + ",HYD:" + String(isHydrated ? 1 : 0);
  
  // Debug print
  Serial.print(", Hydration=");
  Serial.print(isHydrated ? "Hydrated" : "Less Hydrated");
  Serial.println();
  
  // Send data via BLE at the specified interval
  unsigned long currentMillis = millis();
  if (deviceConnected && (currentMillis - previousMillis >= UPDATE_INTERVAL)) {
    previousMillis = currentMillis;
    
    // Send the message
    pCharacteristic->setValue(message.c_str());
    pCharacteristic->notify();
    //Serial.println("Sent via BLE: " + message);
  }
  
  // Handle connection changes
  if (!deviceConnected && oldDeviceConnected) {
    delay(500); // Give the Bluetooth stack time to get ready
    pServer->startAdvertising(); // Restart advertising
    Serial.println("Started advertising");
    oldDeviceConnected = deviceConnected;
  }
  
  // Connected
  if (deviceConnected && !oldDeviceConnected) {
    oldDeviceConnected = deviceConnected;
  }
  
  delay(10); // Short delay for stability
}