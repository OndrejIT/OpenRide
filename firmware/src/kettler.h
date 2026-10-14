// Kettler over Bluetooth Classic (SPP): protocol, polling and commands run in their own FreeRTOS task, so a slow
// (re)connect never blocks the web API. Everything here is safe to call from the web server task.
#pragma once
#include <Arduino.h>

#include <vector>

namespace kettler {

// Last values read from the trainer; has_* is false until the trainer answered (or after a reconnect).
struct Data {
  bool has_rpm = false;          uint16_t rpm = 0;
  bool has_power = false;        uint16_t power = 0;        // W
  bool has_pulse = false;        uint16_t pulse = 0;        // bpm
  bool has_speed = false;        uint16_t speed = 0;        // raw value as reported by the trainer
  bool has_brake = false;        uint8_t brake = 0;         // brake level
  bool has_brake_min = false;    uint8_t brake_min = 0;
  bool has_brake_max = false;    uint8_t brake_max = 0;
  bool has_distance = false;     uint16_t distance = 0;
  bool has_energy = false;       uint16_t energy = 0;
  bool has_time = false;         uint16_t time = 0;
  bool has_online = false;       bool online = false;
  bool has_device_name = false;  String device_name;
  bool has_device_type = false;  char device_type = 0;      // 'B' bike, 'S' racer, 'X', 'T', 'R'
};

struct Device {
  String mac;
  String name;
  int rssi;
  bool kettler;  // name looks like a Kettler (shown first in the setup lists)
};

void begin(const char* btName);
void setTarget(const String& mac, const String& name);  // empty mac = disconnect and stay idle
void setBrake(int level);
void requestScan();

bool connected();
bool scanning();
String targetMac();
String targetName();
Data data();
std::vector<Device> scanResults();

}  // namespace kettler
