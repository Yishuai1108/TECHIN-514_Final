/*
  BLE Heart Rate & Hydration Monitor Client with TFT Display, Stepper Motor, and LED
  Receives heart rate and hydration data from a BLE server and displays it on a TFT screen
  Controls a stepper motor and LED based on heart rate threshold
  
  Hardware:
  - ESP32 with TFT display
  - Stepper motor connected to pins 25, 27, 14, 12
  - LED connected to pin 36
  
  Libraries:
  - TFT_eSPI must be installed and configured for your specific display
  - Free_Fonts.h should be included with TFT_eSPI
*/

#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <TFT_eSPI.h>

// If Free_Fonts.h is in a different location, modify this include
// If you copied Free_Fonts.h to your sketch directory, use:
#include "Free_Fonts.h"
// If it's part of TFT_eSPI library, you may need to use:
// #include <TFT_eSPI/Free_Fonts.h>

// TFT display setup
TFT_eSPI tft = TFT_eSPI();

// BLE server details - MUST match the server
#define SERVICE_UUID        "153d58a2-6e5d-46b3-8df2-7288b3ef3c4e"
#define CHARACTERISTIC_UUID "537a9060-3f8a-4cd9-86ce-a9cd306bc3cb"

// Define pins for stepper motor
#define COIL_A1 25  // Connect to stepper motor coil A1
#define COIL_A2 27  // Connect to stepper motor coil A2
#define COIL_B1 14  // Connect to stepper motor coil B1
#define COIL_B2 12  // Connect to stepper motor coil B2

// Define pin for LED
#define LED_PIN 13  // Connect LED to GPIO 36 (must be a HIGH active LED)

// Stepper motor step sequence (full step mode)
const int stepSequence[4][4] = {
    {1, 0, 1, 0}, // Step 1
    {0, 1, 1, 0}, // Step 2
    {0, 1, 0, 1}, // Step 3
    {1, 0, 0, 1}  // Step 4
};

// BLE client variables
BLEClient* pClient = NULL;
BLERemoteCharacteristic* pRemoteCharacteristic = NULL;
BLEAdvertisedDevice* myDevice = NULL;
bool doConnect = false;
bool connected = false;
bool doScan = true;
bool newDataReceived = false;
int heartRate = 0;
bool isHydrated = false;

// Stepper motor and LED control variables
int currentStepPosition = 0;
const int TOTAL_STEPS = 160;  // Total steps for the stepper motor
bool motorNeedsUpdate = false;
bool previousConditionTriggered = false;
bool conditionTriggered = false;
unsigned long lastLedBlinkTime = 0;
int ledBlinkCount = 0;
bool ledState = false;

// Heart rate history for 1-minute trend and average
const int HISTORY_SIZE = 60;  // Store 1 minute of data
int heartRateHistory[HISTORY_SIZE];
int historyIndex = 0;
bool historyFilled = false;
int minuteAverage = 0;
unsigned long lastDisplayUpdateTime = 0;
unsigned long lastMinuteUpdateTime = 0;

// Display layout - split screen
const int LEFT_AREA_WIDTH = 150;  // Width of left panel

// Graph dimensions
const int GRAPH_X = LEFT_AREA_WIDTH + 10;
const int GRAPH_Y = 60;
const int GRAPH_WIDTH = 160;
const int GRAPH_HEIGHT = 100;
const int GRAPH_MAX_HR = 180;  // Maximum heart rate to show on graph
const int GRAPH_MIN_HR = 40;   // Minimum heart rate to show on graph

// Timing variables
const unsigned long DISPLAY_UPDATE_INTERVAL = 1000; // Update display every 1 second
const unsigned long MOTOR_UPDATE_INTERVAL = 5;      // Update motor position much faster (was 100ms)
const unsigned long LED_BLINK_INTERVAL = 250;       // LED blink interval (250ms)

// Move stepper motor one step in the specified direction
void moveStepperOneStep(bool clockwise) {
  static int stepIndex = 0;
  
  // Determine direction
  if (clockwise) {
    stepIndex = (stepIndex + 1) % 4;
  } else {
    stepIndex = (stepIndex + 3) % 4;  // +3 is same as -1 with wrap around
  }
  
  // Set the coils according to the step sequence
  digitalWrite(COIL_A1, stepSequence[stepIndex][0]);
  digitalWrite(COIL_A2, stepSequence[stepIndex][1]);
  digitalWrite(COIL_B1, stepSequence[stepIndex][2]);
  digitalWrite(COIL_B2, stepSequence[stepIndex][3]);
}

// Move stepper motor to the target position gradually but faster
void updateStepperPosition() {
  static unsigned long lastStepTime = 0;
  int targetPosition;
  
  // Set target position based on the heart rate condition
  if (conditionTriggered) {
    targetPosition = TOTAL_STEPS;  // Move to 160 steps when HR >= 60
  } else {
    targetPosition = 0;  // Move back to 0 when HR < 60
  }
  
  // Move one step at a time with a delay between steps (faster now)
  if (currentStepPosition != targetPosition && millis() - lastStepTime >= MOTOR_UPDATE_INTERVAL) {
    lastStepTime = millis();
    
    // Determine direction
    bool clockwise = currentStepPosition < targetPosition;
    
    // Move one step
    moveStepperOneStep(clockwise);
    
    // Update position
    if (clockwise) {
      currentStepPosition++;
    } else {
      currentStepPosition--;
    }
    
    //Serial.print("Stepper position: ");
    //Serial.println(currentStepPosition);
  }
}

// Update LED based on heart rate condition - try direct digitalWrite
void updateLed() {
  // Check if LED needs to be on (heart rate >= 60)
  if (conditionTriggered) {
    // Only blink when the condition is first triggered
    if (!previousConditionTriggered) {
      ledBlinkCount = 0;  // Reset blink count
      ledState = true;    // Start with LED on
      digitalWrite(LED_PIN, HIGH);
      lastLedBlinkTime = millis();
    }
    
    // Handle LED blinking (blink twice when condition is first triggered)
    if (ledBlinkCount < 4 && millis() - lastLedBlinkTime >= LED_BLINK_INTERVAL) {
      ledState = !ledState;
      digitalWrite(LED_PIN, ledState ? HIGH : LOW);
      lastLedBlinkTime = millis();
      ledBlinkCount++;
      
      // After blinking twice (4 state changes), keep LED on
      if (ledBlinkCount >= 4) {
        digitalWrite(LED_PIN, HIGH);
      }
    } 
    // Keep LED on when condition is triggered (after initial blinks)
    else if (ledBlinkCount >= 4) {
      digitalWrite(LED_PIN, HIGH);
    }
  } 
  // Turn LED off when condition is not triggered
  else if (!conditionTriggered) {
    digitalWrite(LED_PIN, LOW);
  }
  
  // Debug output for LED status
  static unsigned long lastLedDebugTime = 0;
  if (millis() - lastLedDebugTime > 1000) {  // Debug output once per second
    lastLedDebugTime = millis();
    Serial.print("LED Pin State: ");
    Serial.print(digitalRead(LED_PIN));
    Serial.print(", conditionTriggered: ");
    Serial.print(conditionTriggered);
    Serial.print(", ledState: ");
    Serial.print(ledState);
    Serial.print(", ledBlinkCount: ");
    Serial.println(ledBlinkCount);
  }
}

// Callback for when a device is found during scan
class MyAdvertisedDeviceCallbacks: public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice advertisedDevice) {
    Serial.print("Found device: ");
    Serial.println(advertisedDevice.toString().c_str());

    // Check if the device provides the service we're looking for
    if (advertisedDevice.haveServiceUUID() && advertisedDevice.isAdvertisingService(BLEUUID(SERVICE_UUID))) {
      BLEDevice::getScan()->stop();
      myDevice = new BLEAdvertisedDevice(advertisedDevice);
      doConnect = true;
      doScan = false;
      Serial.println("Found HR Monitor Server!");
    }
  }
};

// Callback for received notifications from the BLE server
static void notifyCallback(BLERemoteCharacteristic* pBLERemoteCharacteristic, 
                            uint8_t* pData, size_t length, bool isNotify) {
  String message = "";
  for (int i = 0; i < length; i++) {
    message += (char)pData[i];
  }
  
  Serial.print("Received notification: ");
  Serial.println(message);
  
  // Parse the heart rate value and hydration status
  // Format: "HR:X,HYD:Y" where X is heart rate and Y is 1 (hydrated) or 0 (not hydrated)
  if (message.startsWith("HR:")) {
    // Find heart rate
    int hydIndex = message.indexOf(",HYD:");
    if (hydIndex > 0) {
      // Parse heart rate
      heartRate = message.substring(3, hydIndex).toInt();
      
      // Parse hydration status
      isHydrated = (message.substring(hydIndex + 5).toInt() == 1);
      
      // Add heart rate to history array
      heartRateHistory[historyIndex] = heartRate;
      historyIndex = (historyIndex + 1) % HISTORY_SIZE;
      
      // If we've filled one complete cycle, mark as filled
      if (historyIndex == 0) {
        historyFilled = true;
      }
      
      // Calculate minute average if we have data
      calculateMinuteAverage();
      
      // Check if the condition for stepper motor and LED is triggered
      previousConditionTriggered = conditionTriggered;
      conditionTriggered = (heartRate >= 60);
      
      // Flag new data received for display update
      newDataReceived = true;
      
      Serial.print("Heart Rate: ");
      Serial.print(heartRate);
      Serial.print(" - Hydration: ");
      Serial.print(isHydrated ? "Hydrated" : "Less Hydrated");
      Serial.print(" - Condition triggered: ");
      Serial.println(conditionTriggered);
    }
  }
}

// Calculate the average heart rate over the past minute
void calculateMinuteAverage() {
  int sum = 0;
  int count = 0;
  int validPoints = historyFilled ? HISTORY_SIZE : historyIndex;
  
  for (int i = 0; i < validPoints; i++) {
    if (heartRateHistory[i] > 0) {
      sum += heartRateHistory[i];
      count++;
    }
  }
  
  minuteAverage = (count > 0) ? sum / count : 0;
}

// Connect to a BLE server
bool connectToServer() {
  Serial.print("Connecting to server: ");
  Serial.println(myDevice->getAddress().toString().c_str());
  
  pClient = BLEDevice::createClient();
  
  // Connect to the remote BLE server
  pClient->connect(myDevice);
  if (!pClient->isConnected()) {
    Serial.println("Failed to connect to server");
    return false;
  }
  
  // Obtain a reference to the service in the remote BLE server
  BLERemoteService* pRemoteService = pClient->getService(BLEUUID(SERVICE_UUID));
  if (pRemoteService == nullptr) {
    Serial.println("Failed to find our service");
    pClient->disconnect();
    return false;
  }
  
  // Obtain a reference to the characteristic in the service of the remote BLE server
  pRemoteCharacteristic = pRemoteService->getCharacteristic(BLEUUID(CHARACTERISTIC_UUID));
  if (pRemoteCharacteristic == nullptr) {
    Serial.println("Failed to find our characteristic");
    pClient->disconnect();
    return false;
  }
  
  // Read the value of the characteristic
  if (pRemoteCharacteristic->canRead()) {
    String valueStr = pRemoteCharacteristic->readValue();
    String value = String(valueStr.c_str());
    Serial.print("Initial value: ");
    Serial.println(value);
  }
  
  // Register for notifications if the characteristic supports it
  if (pRemoteCharacteristic->canNotify()) {
    pRemoteCharacteristic->registerForNotify(notifyCallback);
  }
  
  connected = true;
  lastMinuteUpdateTime = millis();
  lastDisplayUpdateTime = millis();
  return true;
}

// Draw the vertical divider line between left and right areas
void drawDivider() {
  tft.drawLine(LEFT_AREA_WIDTH, 0, LEFT_AREA_WIDTH, tft.height(), TFT_DARKGREY);
}

// Draw the heart rate trend graph on the right side
void drawGraph() {
  // Clear graph area
  tft.fillRect(GRAPH_X, GRAPH_Y - 20, GRAPH_WIDTH + 10, GRAPH_HEIGHT + 30, TFT_BLACK);
  
  // Draw graph border
  tft.drawRect(GRAPH_X, GRAPH_Y, GRAPH_WIDTH, GRAPH_HEIGHT, TFT_WHITE);
  
  // Draw graph title
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextFont(2);
  tft.setCursor(GRAPH_X, GRAPH_Y - 20);
  tft.print("Heart Rate Trend");
  
  // Draw baseline grid
  tft.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  tft.setTextFont(1);
  
  // Draw horizontal grid lines and labels
  for (int hr = GRAPH_MIN_HR; hr <= GRAPH_MAX_HR; hr += 40) {
    int y = map(hr, GRAPH_MIN_HR, GRAPH_MAX_HR, GRAPH_Y + GRAPH_HEIGHT, GRAPH_Y);
    for (int x = GRAPH_X; x < GRAPH_X + GRAPH_WIDTH; x += 5) {
      tft.drawPixel(x, y, TFT_DARKGREY);
    }
    tft.setCursor(GRAPH_X - 20, y - 3);
    tft.print(hr);
  }
  
  // Draw minute average line if we have data
  if (minuteAverage > 0) {
    int avgY = map(minuteAverage, GRAPH_MIN_HR, GRAPH_MAX_HR, GRAPH_Y + GRAPH_HEIGHT, GRAPH_Y);
    tft.drawFastHLine(GRAPH_X, avgY, GRAPH_WIDTH, TFT_YELLOW);
    
    // Draw average label
    tft.setTextColor(TFT_YELLOW, TFT_BLACK);
    tft.setCursor(GRAPH_X + GRAPH_WIDTH + 5, avgY - 3);
    tft.print(minuteAverage);
  }
  
  // Draw points and connect them with lines
  int count = historyFilled ? HISTORY_SIZE : historyIndex;
  int start = historyFilled ? historyIndex : 0;
  
  if (count > 1) {
    for (int i = 0; i < count - 1; i++) {
      int idx1 = (start + i) % HISTORY_SIZE;
      int idx2 = (start + i + 1) % HISTORY_SIZE;
      
      int hr1 = heartRateHistory[idx1];
      int hr2 = heartRateHistory[idx2];
      
      // Only plot if we have valid heart rates
      if (hr1 > 0 && hr2 > 0) {
        // Map heart rate to graph coordinates
        int x1 = map(i, 0, HISTORY_SIZE - 1, GRAPH_X, GRAPH_X + GRAPH_WIDTH);
        int y1 = map(hr1, GRAPH_MIN_HR, GRAPH_MAX_HR, GRAPH_Y + GRAPH_HEIGHT, GRAPH_Y);
        
        int x2 = map(i + 1, 0, HISTORY_SIZE - 1, GRAPH_X, GRAPH_X + GRAPH_WIDTH);
        int y2 = map(hr2, GRAPH_MIN_HR, GRAPH_MAX_HR, GRAPH_Y + GRAPH_HEIGHT, GRAPH_Y);
        
        // Draw line segment with color based on heart rate
        uint16_t lineColor;
        if (hr1 < 60 || hr2 < 60) {
          lineColor = TFT_CYAN;  // Low
        } else if (hr1 < 100 && hr2 < 100) {
          lineColor = TFT_GREEN; // Normal
        } else if (hr1 < 120 && hr2 < 120) {
          lineColor = TFT_YELLOW; // Elevated
        } else {
          lineColor = TFT_RED; // High
        }
        
        tft.drawLine(x1, y1, x2, y2, lineColor);
      }
    }
  }
  
  // Draw time labels at bottom
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setCursor(GRAPH_X, GRAPH_Y + GRAPH_HEIGHT + 5);
  tft.print("60s");
  tft.setCursor(GRAPH_X + GRAPH_WIDTH - 20, GRAPH_Y + GRAPH_HEIGHT + 5);
  tft.print("0s");
  
  // Display 1-minute average info below the graph
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextFont(2);
  tft.setCursor(GRAPH_X, GRAPH_Y + GRAPH_HEIGHT + 15);
  tft.print("1-min avg: ");
  
  // Color code the average value
  if (minuteAverage < 60) {
    tft.setTextColor(TFT_CYAN, TFT_BLACK);
  } else if (minuteAverage < 100) {
    tft.setTextColor(TFT_GREEN, TFT_BLACK);
  } else if (minuteAverage < 120) {
    tft.setTextColor(TFT_YELLOW, TFT_BLACK);
  } else {
    tft.setTextColor(TFT_RED, TFT_BLACK);
  }
  
  tft.print(minuteAverage);
  tft.print(" BPM");
}

// Update the left side with current heart rate and hydration display
void updateHeartRateDisplay() {
  // Clear the heart rate display area (left side)
  tft.fillRect(0, 60, LEFT_AREA_WIDTH, 200, TFT_BLACK);
  
  // Current HR Label
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextFont(2);
  tft.setCursor(10, 60);
  tft.print("Current HR");
  
  // Heart rate value with color coding
  if (heartRate < 60) {
    tft.setTextColor(TFT_CYAN, TFT_BLACK); // Low
  } else if (heartRate < 100) {
    tft.setTextColor(TFT_GREEN, TFT_BLACK); // Normal
  } else if (heartRate < 120) {
    tft.setTextColor(TFT_YELLOW, TFT_BLACK); // Elevated
  } else {
    tft.setTextColor(TFT_RED, TFT_BLACK); // High
  }
  
  // Display heart rate in large font
  tft.setFreeFont(FSS24);
  int hrXpos = 40;
  int hrYpos = 100;
  tft.drawString(String(heartRate), hrXpos, hrYpos, GFXFF);
  
  // BPM label
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setFreeFont(FSS9);
  tft.drawString("BPM", hrXpos + 75, hrYpos, GFXFF);
  
  // Draw heart rate status
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextFont(2);
  tft.setCursor(10, 140);
  tft.print("Status: ");
  
  // Color code the status text
  if (heartRate < 60) {
    tft.setTextColor(TFT_CYAN, TFT_BLACK);
    tft.print("Low");
  } else if (heartRate < 100) {
    tft.setTextColor(TFT_GREEN, TFT_BLACK);
    tft.print("Normal");
  } else if (heartRate < 120) {
    tft.setTextColor(TFT_YELLOW, TFT_BLACK);
    tft.print("Elevated");
  } else {
    tft.setTextColor(TFT_RED, TFT_BLACK);
    tft.print("High");
  }
  
  // Draw hydration status
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextFont(2);
  tft.setCursor(10, 160);
  tft.print("Hydration: ");
  
  // Color code the hydration status
  if (isHydrated) {
    tft.setTextColor(TFT_GREEN, TFT_BLACK);
    tft.print("Hydrated");
  } else {
    tft.setTextColor(TFT_YELLOW, TFT_BLACK);
    tft.print("Less Hydrated");
  }
  
  // Draw motor status
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setCursor(10, 180);
  tft.print("Motor: ");
  if (heartRate >= 60) {
    tft.setTextColor(TFT_GREEN, TFT_BLACK);
    tft.print("Active");
  } else {
    tft.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
    tft.print("Standby");
  }
  
  // Draw divider line
  drawDivider();
}

// Update both the heart rate display and graph
void updateDisplay() {
  updateHeartRateDisplay();
  drawGraph();
}

void setup() {
  Serial.begin(115200);
  Serial.println("Starting BLE Heart Rate & Hydration Monitor Client");
  
  // Initialize heart rate history array
  for (int i = 0; i < HISTORY_SIZE; i++) {
    heartRateHistory[i] = 0;
  }
  
  // Initialize stepper motor pins with explicit pin definitions
  pinMode(COIL_A1, OUTPUT); // Pin 25
  pinMode(COIL_A2, OUTPUT); // Pin 27
  pinMode(COIL_B1, OUTPUT); // Pin 14
  pinMode(COIL_B2, OUTPUT); // Pin 12
  
  // Turn off all coils at startup
  digitalWrite(COIL_A1, LOW);
  digitalWrite(COIL_A2, LOW);
  digitalWrite(COIL_B1, LOW);
  digitalWrite(COIL_B2, LOW);
  
  // Initialize LED pin
  pinMode(LED_PIN, OUTPUT); // Pin 36
  
  // Test the LED at startup to confirm it works
  digitalWrite(LED_PIN, HIGH);
  delay(500);
  digitalWrite(LED_PIN, LOW);
  
  Serial.println("LED test complete - should have seen LED blink once");
  
  // Initialize display
  tft.begin();
  tft.setRotation(1); // Landscape mode
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  
  // Display startup message
  tft.setFreeFont(FSS18);
  tft.drawString("Heart Rate Monitor", tft.width()/2, 40, GFXFF);
  tft.setFreeFont(FSS12);
  tft.drawString("Scanning for device...", tft.width()/2, 100, GFXFF);
  
  // Set backlight to maximum brightness (if your screen supports it)
  pinMode(15, OUTPUT);
  digitalWrite(15, HIGH);
  
  // Initialize BLE
  BLEDevice::init("");

  // Configure BLE scan
  BLEScan* pBLEScan = BLEDevice::getScan();
  pBLEScan->setAdvertisedDeviceCallbacks(new MyAdvertisedDeviceCallbacks());
  pBLEScan->setInterval(1349);
  pBLEScan->setWindow(449);
  pBLEScan->setActiveScan(true);
  pBLEScan->start(5, false);
  
  Serial.println("Scanning for BLE devices...");
}

void loop() {
  // Connect to server if device was found
  if (doConnect) {
    if (connectToServer()) {
      Serial.println("Connected to the BLE Server.");
      
      // Update display to show connected
      tft.fillScreen(TFT_BLACK);
      tft.setTextColor(TFT_GREEN, TFT_BLACK);
      tft.setFreeFont(FSS18);
      tft.drawString("Connected!", tft.width()/2, 80, GFXFF);
      tft.setTextColor(TFT_WHITE, TFT_BLACK);
      tft.setFreeFont(FSS12);
      tft.drawString("Waiting for data...", tft.width()/2, 120, GFXFF);
      
      delay(1000);
      tft.fillScreen(TFT_BLACK);
      
      // Draw header
      tft.setTextColor(TFT_WHITE, TFT_BLACK);
      tft.setFreeFont(FSS12);
      tft.drawString("Heart Rate Monitor", tft.width()/2, 20, GFXFF);
      
      // Draw initial layout
      drawDivider();
    } else {
      Serial.println("Failed to connect to the server.");
      
      // Update display
      tft.fillScreen(TFT_BLACK);
      tft.setTextColor(TFT_RED, TFT_BLACK);
      tft.setFreeFont(FSS18);
      tft.drawString("Connection Failed", tft.width()/2, 100, GFXFF);
      
      // Wait a bit and try scanning again
      delay(3000);
      doScan = true;
    }
    doConnect = false;
  }
  
  // If disconnected and should scan, start scanning again
  if (!connected && doScan) {
    BLEDevice::getScan()->start(0);
  }
  
  // Update display at regular intervals (not on every new data)
  unsigned long currentMillis = millis();
  if (connected && newDataReceived && 
      (currentMillis - lastDisplayUpdateTime >= DISPLAY_UPDATE_INTERVAL)) {
    lastDisplayUpdateTime = currentMillis;
    updateDisplay();
    newDataReceived = false;
  }
  
  // Check if a minute has passed to update the average 
  // (this ensures the display updates even without new data)
  if (connected && (currentMillis - lastMinuteUpdateTime >= 60000)) {
    calculateMinuteAverage();
    updateDisplay();
    lastMinuteUpdateTime = currentMillis;
    Serial.print("Updated 1-minute average: ");
    Serial.println(minuteAverage);
  }
  
  // Update stepper motor position
  if (connected) {
    updateStepperPosition();
  }
  
  // Update LED
  if (connected) {
    updateLed();
  }
  
  // Check if client is still connected
  if (connected && !pClient->isConnected()) {
    connected = false;
    Serial.println("Disconnected from server");
    
    // Update display
    tft.fillScreen(TFT_BLACK);
    tft.setTextColor(TFT_RED, TFT_BLACK);
    tft.setFreeFont(FSS18);
    tft.drawString("Disconnected", tft.width()/2, 80, GFXFF);
    tft.setTextColor(TFT_WHITE, TFT_BLACK);
    tft.setFreeFont(FSS12);
    tft.drawString("Scanning for device...", tft.width()/2, 120, GFXFF);
    
    // Turn off LED and stepper motor when disconnected
    digitalWrite(LED_PIN, LOW);
    digitalWrite(COIL_A1, LOW);
    digitalWrite(COIL_A2, LOW);
    digitalWrite(COIL_B1, LOW);
    digitalWrite(COIL_B2, LOW);
    
    // Reset data
    for (int i = 0; i < HISTORY_SIZE; i++) {
      heartRateHistory[i] = 0;
    }
    historyIndex = 0;
    historyFilled = false;
    minuteAverage = 0;
    currentStepPosition = 0;
    
    // Start scanning again
    doScan = true;
  }
  
  delay(5); // Reduced delay for faster response
}