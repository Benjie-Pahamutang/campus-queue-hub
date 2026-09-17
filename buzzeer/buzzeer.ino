/* 
  ========================================================
  Campus Queue System - Integrated Dual Buzzers & Thermal Printer
  
  Wiring:
  - Buzzer 1 I/O: Digital Pin 8 (Active-LOW)
  - Buzzer 2 I/O: Digital Pin 9 (Active-LOW)
  - Printer RX:   Digital Pin 10 -> Connected to Printer TX Wire/Pin
  - Printer TX:   Digital Pin 11 -> Connected to Printer RX Wire/Pin
  - Printer GND:  Arduino GND
  ========================================================
*/

#include <SoftwareSerial.h>

// 📌 PIN CONFIGURATION
const int BUZZER_1_PIN = 8; 
const int BUZZER_2_PIN = 9; 
const int PRINTER_RX_PIN = 10; // Arduino Pin 10 -> Printer TX
const int PRINTER_TX_PIN = 11; // Arduino Pin 11 -> Printer RX

// Initialize SoftwareSerial for Thermal Printer
SoftwareSerial printerSerial(PRINTER_RX_PIN, PRINTER_TX_PIN);

// ⚙️ SETUP
void setup() {
  // Main USB Serial Communication with Python (main.py)
  Serial.begin(9600);
  
  // SoftwareSerial for Thermal Printer
  printerSerial.begin(9600);
  
  // Configure active-LOW buzzer pins
  pinMode(BUZZER_1_PIN, OUTPUT);
  pinMode(BUZZER_2_PIN, OUTPUT);
  
  // Set both pins HIGH immediately to keep active-LOW buzzers SILENT at boot
  digitalWrite(BUZZER_1_PIN, HIGH);
  digitalWrite(BUZZER_2_PIN, HIGH);
  
  // Quick startup chime on BOTH buzzers to confirm power & wiring
  playQueueChime();
}

// 🔔 DUAL ACTIVE-LOW BUZZER CHIME FUNCTION
void playQueueChime() {
  // Beep 1: Turn BOTH ON (LOW)
  digitalWrite(BUZZER_1_PIN, LOW);   
  digitalWrite(BUZZER_2_PIN, LOW);   
  delay(120);
  
  // Turn BOTH OFF (HIGH)
  digitalWrite(BUZZER_1_PIN, HIGH);  
  digitalWrite(BUZZER_2_PIN, HIGH);  
  delay(80);
  
  // Beep 2: Turn BOTH ON (LOW)
  digitalWrite(BUZZER_1_PIN, LOW);   
  digitalWrite(BUZZER_2_PIN, LOW);   
  delay(220);
  
  // Force BOTH OFF completely (HIGH)
  digitalWrite(BUZZER_1_PIN, HIGH);  
  digitalWrite(BUZZER_2_PIN, HIGH);  
}

// 🎟️ THERMAL PRINTER RECEIPT FUNCTION (ESC/POS)
void printTicket(String ticketType, String ticketNum, String name, String purpose, String dateStr, String timeStr, String apptStr) {
  // Ensure SoftwareSerial is listening
  printerSerial.listen();
  
  // Clear any residual garbage characters from the serial buffer
  while(printerSerial.available() > 0) { 
    printerSerial.read(); 
  }

  // ESC/POS Reset & Align Center
  printerSerial.write((uint8_t)0x1B); 
  printerSerial.write((uint8_t)0x40); // Reset printer hardware state
  delay(50);                          // Brief pause to allow printer EEPROM initialization

  printerSerial.write((uint8_t)0x1B); 
  printerSerial.write((uint8_t)0x61); 
  printerSerial.write((uint8_t)1);    // Center Alignment
  
  // Header
  printerSerial.write((uint8_t)0x1B); 
  printerSerial.write((uint8_t)0x45); 
  printerSerial.write((uint8_t)1);    // Bold ON
  printerSerial.println(F("TORRES CAPITOL COLLEGE"));
  printerSerial.println(F("SCHOOL PAYMENT QUEUE SYSTEM"));
  printerSerial.write((uint8_t)0x1B); 
  printerSerial.write((uint8_t)0x45); 
  printerSerial.write((uint8_t)0);    // Bold OFF
  printerSerial.println(F("--------------------------------"));
  
  // Queue Number Label
  printerSerial.println(F("YOUR QUEUE NUMBER"));
  printerSerial.println("");
  
  // Quadruple-Size Text for Ticket Number (0x33)
  printerSerial.write((uint8_t)0x1D); 
  printerSerial.write((uint8_t)0x21); 
  printerSerial.write((uint8_t)0x33);
  printerSerial.println(ticketType + "-" + ticketNum);
  
  // Reset Text Size back to normal
  printerSerial.write((uint8_t)0x1D); 
  printerSerial.write((uint8_t)0x21); 
  printerSerial.write((uint8_t)0x00);
  
  // Details Section (Payer & Purpose)
  printerSerial.println(F("................................"));
  printerSerial.println("Payer: " + name);
  printerSerial.println("Purpose: " + purpose);
  printerSerial.println(F("................................"));
  
  // Date & Time
  printerSerial.println("DATE: " + dateStr);
  printerSerial.println("TIME: " + timeStr);
  
  // Print Appt ONLY if it contains a valid slot (hides when "NONE" or "N/A")
  apptStr.trim();
  if (apptStr != "NONE" && apptStr != "N/A" && apptStr.length() > 0) {
    printerSerial.println("Appt: " + apptStr);
  }
  
  printerSerial.println(F("--------------------------------"));
  
  // Footer
  printerSerial.println(F("  PLEASE WAIT FOR YOUR NUMBER   "));
  printerSerial.println(F("     *  THANK YOU!  *          "));
  
  // Feed paper lines to clear printer slot
  printerSerial.println("\n\n\n");
  printerSerial.flush();
}

// 🔄 MAIN LOOP
void loop() {
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim(); 
    
    // Command 'B' -> Trigger Dual Buzzer Chime
    if (command == "B") {
      playQueueChime();
    } 
    // Updated Command format matching Python: P|TYPE|NUM|NAME|PURPOSE|DATE|TIME|APPT
    else if (command.startsWith("P|")) {
      int p1 = command.indexOf('|');
      int p2 = command.indexOf('|', p1 + 1);
      int p3 = command.indexOf('|', p2 + 1);
      int p4 = command.indexOf('|', p3 + 1);
      int p5 = command.indexOf('|', p4 + 1);
      int p6 = command.indexOf('|', p5 + 1);
      int p7 = command.indexOf('|', p6 + 1);
      
      if (p1 != -1 && p2 != -1 && p3 != -1 && p4 != -1 && p5 != -1 && p6 != -1) {
        String ticketType = command.substring(p1 + 1, p2);
        String ticketNum  = command.substring(p2 + 1, p3);
        String name       = command.substring(p3 + 1, p4);
        String purpose    = command.substring(p4 + 1, p5);
        String dateStr    = command.substring(p5 + 1, p6);
        
        String timeStr;
        String apptStr = "NONE";
        
        if (p7 != -1) {
          timeStr = command.substring(p6 + 1, p7);
          apptStr = command.substring(p7 + 1);
        } else {
          timeStr = command.substring(p6 + 1);
        }
        
        printTicket(ticketType, ticketNum, name, purpose, dateStr, timeStr, apptStr);
      }
    }
  }
}