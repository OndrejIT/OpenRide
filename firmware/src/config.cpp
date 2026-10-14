#include "config.h"

#include <Preferences.h>

namespace config {

static const char* NS = "openride";

Settings load() {
  Preferences p;
  p.begin(NS, true);
  Settings s{p.getString("wifi_ssid", ""), p.getString("wifi_pass", ""), p.getString("kettler_mac", ""),
             p.getString("kettler_name", "")};
  p.end();
  return s;
}

static void put(std::initializer_list<std::pair<const char*, const String*>> values) {
  Preferences p;
  p.begin(NS, false);
  for (auto& [key, value] : values) {
    if (value) p.putString(key, *value);
    else p.remove(key);
  }
  p.end();
}

void saveWifi(const String& ssid, const String& pass) { put({{"wifi_ssid", &ssid}, {"wifi_pass", &pass}}); }
void forgetWifi() { put({{"wifi_ssid", nullptr}, {"wifi_pass", nullptr}}); }
void saveKettler(const String& mac, const String& name) { put({{"kettler_mac", &mac}, {"kettler_name", &name}}); }
void forgetKettler() { put({{"kettler_mac", nullptr}, {"kettler_name", nullptr}}); }

void forgetAll() {
  Preferences p;
  p.begin(NS, false);
  p.clear();
  p.end();
}

}  // namespace config
