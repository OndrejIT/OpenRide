// OpenRide trainer bridge: Kettler (Bluetooth Classic) <-> HTTP JSON API on the home Wi-Fi.
// Without saved Wi-Fi it runs an open setup network "NaKole-xxxx" with a captive setup page.
#include <Arduino.h>
#include <ArduinoJson.h>
#include <DNSServer.h>
#include <ESPmDNS.h>
#include <WebServer.h>
#include <WiFi.h>

#include "config.h"
#include "kettler.h"
#include "setup_page.h"

static const char* HOSTNAME = "nakole";  // http://nakole.local
static const char* VERSION = "1";
static const int BOOT_PIN = 0;
static const uint32_t FORGET_HOLD_MS = 5000;
static const uint32_t WIFI_JOIN_TIMEOUT_MS = 15000;

static WebServer server(80);
static DNSServer dns;
static bool setup_mode = false;
static bool mdns_started = false;
static uint32_t restart_at = 0;

// ---- HTTP helpers

static void cors() {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  server.sendHeader("Access-Control-Allow-Headers", "Content-Type");
  // Chrome's Private Network Access preflight: the app is served from another origin than this LAN device
  server.sendHeader("Access-Control-Allow-Private-Network", "true");
}

static void send_json(int code, const JsonDocument& doc) {
  cors();
  String out;
  serializeJson(doc, out);
  server.send(code, "application/json; charset=utf-8", out);
}

static void send_error(int code, const char* message) {
  JsonDocument doc;
  doc["ok"] = false;
  doc["error"] = message;
  send_json(code, doc);
}

static void send_ok() {
  JsonDocument doc;
  doc["ok"] = true;
  send_json(200, doc);
}

static bool body(JsonDocument& doc) {
  if (!server.hasArg("plain") || deserializeJson(doc, server.arg("plain"))) {
    send_error(400, "Neplatný JSON");
    return false;
  }
  return true;
}

template <typename T>
static void put(JsonObject o, const char* key, bool has, T value) {
  if (has) o[key] = value;
  else o[key] = nullptr;
}

// ---- API

static void handle_status() {
  JsonDocument doc;
  doc["version"] = VERSION;
  doc["mode"] = setup_mode ? "setup" : "station";

  JsonObject w = doc["wifi"].to<JsonObject>();
  bool joined = WiFi.status() == WL_CONNECTED;
  w["ssid"] = joined ? WiFi.SSID() : config::load().wifiSsid;
  w["connected"] = joined;
  put(w, "ip", joined, WiFi.localIP().toString());
  put(w, "rssi", joined, WiFi.RSSI());

  JsonObject k = doc["kettler"].to<JsonObject>();
  k["mac"] = kettler::targetMac();
  k["name"] = kettler::targetName();
  k["connected"] = kettler::connected();
  k["scanning"] = kettler::scanning();
  JsonArray devices = k["devices"].to<JsonArray>();
  for (auto& d : kettler::scanResults()) {
    JsonObject o = devices.add<JsonObject>();
    o["mac"] = d.mac;
    o["name"] = d.name;
    o["rssi"] = d.rssi;
    o["kettler"] = d.kettler;
  }

  kettler::Data d = kettler::data();
  JsonObject v = doc["data"].to<JsonObject>();
  put(v, "rpm", d.has_rpm, d.rpm);
  put(v, "power", d.has_power, d.power);
  put(v, "pulse", d.has_pulse, d.pulse);
  put(v, "speed", d.has_speed, d.speed);
  put(v, "brake", d.has_brake, d.brake);
  put(v, "brake_min", d.has_brake_min, d.brake_min);
  put(v, "brake_max", d.has_brake_max, d.brake_max);
  put(v, "distance", d.has_distance, d.distance);
  put(v, "energy", d.has_energy, d.energy);
  put(v, "time", d.has_time, d.time);
  put(v, "online", d.has_online, d.online);
  put(v, "device_name", d.has_device_name, d.device_name);
  put(v, "device_type", d.has_device_type, String(d.device_type));
  send_json(200, doc);
}

static void handle_brake() {
  JsonDocument in;
  if (!body(in)) return;
  if (!in["brake"].is<int>()) return send_error(400, "Chybí pole brake");
  if (!kettler::connected()) return send_error(503, "Kettler není připojen");
  kettler::Data d = kettler::data();
  int lo = d.has_brake_min ? d.brake_min : 1, hi = d.has_brake_max ? d.brake_max : 20;
  int level = constrain(in["brake"].as<int>(), lo, hi);
  kettler::setBrake(level);
  JsonDocument doc;
  doc["ok"] = true;
  doc["brake"] = level;
  send_json(200, doc);
}

static void handle_kettler_scan() {
  kettler::requestScan();
  send_ok();
}

static void handle_kettler_select() {
  JsonDocument in;
  if (!body(in)) return;
  String mac = in["mac"] | "", name = in["name"] | "";
  if (mac.length() != 17) return send_error(400, "Neplatná MAC adresa");
  config::saveKettler(mac, name);
  kettler::setTarget(mac, name);
  send_ok();
}

static void handle_kettler_forget() {
  config::forgetKettler();
  kettler::setTarget("", "");
  send_ok();
}

static void handle_wifi_scan() {
  JsonDocument doc;
  JsonArray list = doc.to<JsonArray>();
  int n = WiFi.scanNetworks();
  for (int i = 0; i < n; i++) {
    if (WiFi.SSID(i).isEmpty()) continue;
    bool seen = false;  // one row per network name, the strongest access point first (scan is sorted by RSSI)
    for (JsonObject o : list) seen |= o["ssid"] == WiFi.SSID(i);
    if (seen) continue;
    JsonObject o = list.add<JsonObject>();
    o["ssid"] = WiFi.SSID(i);
    o["rssi"] = WiFi.RSSI(i);
    o["open"] = WiFi.encryptionType(i) == WIFI_AUTH_OPEN;
  }
  WiFi.scanDelete();
  send_json(200, doc);
}

static void handle_wifi_join() {
  if (!setup_mode) return send_error(409, "Wi-Fi je nastavená; nejdřív ji zapomeň");
  JsonDocument in;
  if (!body(in)) return;
  String ssid = in["ssid"] | "", pass = in["password"] | "";
  if (ssid.isEmpty()) return send_error(400, "Vyber síť");
  WiFi.begin(ssid.c_str(), pass.c_str());
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_JOIN_TIMEOUT_MS) {
    dns.processNextRequest();
    delay(100);
  }
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.disconnect();
    return send_error(422, "Nepodařilo se připojit (špatné heslo, nebo síť mimo dosah?)");
  }
  // saved only once it worked, so a typo never locks the bridge out of setup mode
  config::saveWifi(ssid, pass);
  JsonDocument doc;
  doc["ok"] = true;
  doc["ip"] = WiFi.localIP().toString();
  send_json(200, doc);
  restart_at = millis() + 8000;  // leave time to read the address on the setup page
}

static void handle_wifi_forget() {
  config::forgetWifi();
  send_ok();
  restart_at = millis() + 1000;
}

static void handle_not_found() {
  if (server.method() == HTTP_OPTIONS) {
    cors();
    server.send(204);
  } else if (setup_mode) {
    // captive portal: every page the phone probes leads to the setup page
    server.sendHeader("Location", "http://" + WiFi.softAPIP().toString() + "/");
    server.send(302);
  } else {
    send_error(404, "Neznámá adresa");
  }
}

static void routes() {
  server.on("/", HTTP_GET, [] { server.send_P(200, "text/html; charset=utf-8", SETUP_PAGE); });
  server.on("/api/status", HTTP_GET, handle_status);
  server.on("/api/brake", HTTP_POST, handle_brake);
  server.on("/api/kettler/scan", HTTP_POST, handle_kettler_scan);
  server.on("/api/kettler", HTTP_POST, handle_kettler_select);
  server.on("/api/kettler/forget", HTTP_POST, handle_kettler_forget);
  server.on("/api/wifi/scan", HTTP_GET, handle_wifi_scan);
  server.on("/api/wifi", HTTP_POST, handle_wifi_join);
  server.on("/api/wifi/forget", HTTP_POST, handle_wifi_forget);
  server.onNotFound(handle_not_found);
}

// ---- setup / loop

static void check_boot_button() {
  static uint32_t pressed_at = 0;
  if (digitalRead(BOOT_PIN) == HIGH) {
    pressed_at = 0;
    return;
  }
  if (!pressed_at) pressed_at = millis();
  if (millis() - pressed_at >= FORGET_HOLD_MS) {
    Serial.println("[setup] BOOT held: forgetting Wi-Fi and Kettler");
    config::forgetAll();
    delay(200);
    ESP.restart();
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(BOOT_PIN, INPUT_PULLUP);
  config::Settings s = config::load();

  kettler::begin("OpenRide-Bridge");
  if (s.kettlerMac.length()) kettler::setTarget(s.kettlerMac, s.kettlerName);

  WiFi.setHostname(HOSTNAME);
  if (s.wifiSsid.isEmpty()) {
    setup_mode = true;
    String mac = WiFi.macAddress();  // "AA:BB:CC:DD:EE:FF" -> NaKole-EEFF
    String ap = "NaKole-" + mac.substring(12, 14) + mac.substring(15, 17);
    WiFi.mode(WIFI_AP_STA);  // STA too: the setup page scans and test-joins the home network
    WiFi.softAP(ap.c_str());
    dns.start(53, "*", WiFi.softAPIP());
    Serial.printf("[setup] open network %s, page http://%s/\n", ap.c_str(), WiFi.softAPIP().toString().c_str());
  } else {
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin(s.wifiSsid.c_str(), s.wifiPass.c_str());
    Serial.printf("[wifi] joining %s\n", s.wifiSsid.c_str());
  }

  routes();
  server.begin();
}

void loop() {
  if (setup_mode) dns.processNextRequest();
  server.handleClient();
  check_boot_button();

  if (!setup_mode && !mdns_started && WiFi.status() == WL_CONNECTED) {
    mdns_started = MDNS.begin(HOSTNAME);
    if (mdns_started) MDNS.addService("http", "tcp", 80);
    Serial.printf("[wifi] connected, http://%s/ or http://%s.local/\n", WiFi.localIP().toString().c_str(),
                  HOSTNAME);
  }
  if (restart_at && millis() > restart_at) ESP.restart();
  delay(2);
}
