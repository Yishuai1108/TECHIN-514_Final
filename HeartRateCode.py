/*
  Heart Rate Monitor using MAX30105
  Measures heart rate for 5 seconds and displays a summary
  Based on SparkFun's PBA algorithm example
*/

#include <Wire.h>
#include "MAX30105.h"
#include "heartRate.h"

MAX30105 particleSensor;

// Heart rate variables
const byte RATE_SIZE = 8; // Increased for better averaging over 5 seconds
byte rates[RATE_SIZE];
byte rateSpot = 0;
long lastBeat = 0;
float beatsPerMinute;
int beatAvg = 0;

// Timing for 5-second sampling
unsigned long startTime;
const unsigned long samplingPeriod = 5000; // 5 seconds in milliseconds
bool samplingComplete = false;
bool fingerDetected = false;

void setup() {
  Serial.begin(115200);
  Serial.println("Heart Rate Monitor - 5 Second Summary");
  Serial.println("--------------------------------------");

  // Initialize sensor
  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("MAX30105 was not found. Please check wiring/power.");
    while (1);
  }
  
  // Configure sensor with default settings
  particleSensor.setup();
  particleSensor.setPulseAmplitudeRed(0x0A); // Turn Red LED to low to indicate sensor is running
  particleSensor.setPulseAmplitudeGreen(0);  // Turn off Green LED
  
  Serial.println("Place your index finger on the sensor with steady pressure.");
  
  // Initialize the timing
  startTime = millis();
}

void loop() {
  long irValue = particleSensor.getIR();
  
  // Check if finger is detected
  if (irValue < 50000) {
    if (fingerDetected) {
      Serial.println("Finger removed. Please place finger on sensor.");
      fingerDetected = false;
      resetMeasurement();
    }
    return;
  } else if (!fingerDetected) {
    Serial.println("Finger detected! Starting 5-second measurement...");
    fingerDetected = true;
    resetMeasurement();
  }
  
  // Beat detection
  if (checkForBeat(irValue)) {
    long delta = millis() - lastBeat;
    lastBeat = millis();
    
    beatsPerMinute = 60 / (delta / 1000.0);
    
    if (beatsPerMinute < 255 && beatsPerMinute > 20) {
      rates[rateSpot++] = (byte)beatsPerMinute;
      rateSpot %= RATE_SIZE;
      
      // Calculate average BPM
      beatAvg = 0;
      byte validValues = 0;
      for (byte x = 0; x < RATE_SIZE; x++) {
        if (rates[x] > 0) {
          beatAvg += rates[x];
          validValues++;
        }
      }
      if (validValues > 0) {
        beatAvg /= validValues;
      }
    }
  }
  
  // Check if 5 seconds have passed
  if (!samplingComplete && (millis() - startTime >= samplingPeriod)) {
    samplingComplete = true;
    displaySummary();
    resetMeasurement();
  }
  
  // Regular status output (once per second)
  static unsigned long lastStatusTime = 0;
  if (millis() - lastStatusTime > 1000) {
    Serial.print("IR=");
    Serial.print(irValue);
    Serial.print(", BPM=");
    Serial.print(beatsPerMinute);
    Serial.print(", Avg BPM=");
    Serial.println(beatAvg);
    lastStatusTime = millis();
  }
}

void displaySummary() {
  Serial.println("\n--- 5-SECOND MEASUREMENT SUMMARY ---");
  if (beatAvg > 0) {
    Serial.print("Average Heart Rate: ");
    Serial.print(beatAvg);
    Serial.println(" BPM");
    
    // Add a simple heart rate status
    Serial.print("Status: ");
    if (beatAvg < 60) Serial.println("Low heart rate");
    else if (beatAvg < 100) Serial.println("Normal heart rate");
    else if (beatAvg < 120) Serial.println("Elevated heart rate");
    else Serial.println("High heart rate");
  } else {
    Serial.println("Unable to determine heart rate. Please check sensor position.");
  }
  Serial.println("--------------------------------------");
}

void resetMeasurement() {
  // Reset variables for next measurement
  startTime = millis();
  samplingComplete = false;
  
  // Clear the rates array
  for (byte i = 0; i < RATE_SIZE; i++) {
    rates[i] = 0;
  }
  rateSpot = 0;
}
