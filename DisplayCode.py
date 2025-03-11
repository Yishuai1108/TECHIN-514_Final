#include <TFT_eSPI.h>
#include <SPI.h>

// Include the font header (this would be included with TFT_eSPI library)
#include "Free_Fonts.h"

// Create an instance of the TFT_eSPI class
TFT_eSPI tft = TFT_eSPI();

void setup() {
  Serial.begin(115200);
  Serial.println("ESP32 ST7796S LCD Arial Font Test");
  
  // Initialize the display
  tft.begin();
  
  // Set the orientation (1 = landscape)
  tft.setRotation(1);
  
  // Clear the screen to black
  tft.fillScreen(TFT_BLACK);
  
  // Set the text color to white with black background
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  
  // Set the text datum to middle center
  tft.setTextDatum(MC_DATUM);
  
  // Calculate the center position of the screen
  int xpos = tft.width() / 2;
  int ypos = tft.height() / 2;
  
  // Use Arial font (FF1 = FreeSans9pt7b, which is similar to Arial)
  // You can also try other Arial-like fonts:
  // FSS9 = FreeSans9pt7b (9pt)
  // FSS12 = FreeSans12pt7b (12pt)
  // FSS18 = FreeSans18pt7b (18pt)
  // FSS24 = FreeSans24pt7b (24pt)
  tft.setFreeFont(FSS18);
  
  // Draw "Hello" in the center of the screen
  // The GFXFF parameter tells the library to use the free font
  tft.drawString("Hello", xpos, ypos, GFXFF);
  
  // Set backlight to maximum brightness
  pinMode(15, OUTPUT);
  digitalWrite(15, HIGH);
  
  Serial.println("Text displayed");
}

void loop() {
  // Nothing in the main loop
}