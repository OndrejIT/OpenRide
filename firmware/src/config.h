// Persistent settings (NVS): survive restarts and power loss, cleared by "forget" or by holding BOOT.
#pragma once
#include <Arduino.h>

namespace config {

struct Settings {
  String wifiSsid;
  String wifiPass;
  String kettlerMac;   // "00:80:25:43:6D:20", empty = none chosen yet
  String kettlerName;
};

Settings load();
void saveWifi(const String& ssid, const String& pass);
void forgetWifi();
void saveKettler(const String& mac, const String& name);
void forgetKettler();
void forgetAll();

}  // namespace config
