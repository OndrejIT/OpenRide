// Kettler KDRI protocol (ported from NaKole, originally from a Rust implementation):
// frame = 0x02, payload with 0x02/0x03/0x10 escaped as 0x10 (b ^ 0x20), 0x03, CRC16 (poly 0x8408) of the raw payload.
// payload = value (u16 BE), instruction (1 read, 2 write, 3 answer), length (u16 BE), data.
#include "kettler.h"

#include <BluetoothSerial.h>

#include <algorithm>

namespace kettler {

static BluetoothSerial bt;

static const uint32_t FAST_MS = 100;     // cadence, power, pulse
static const uint32_t MEDIUM_MS = 500;   // brake level, online
static const uint32_t SLOW_MS = 1000;    // distance, energy, time
static const uint32_t STATIC_MS = 2000;  // device info and limits until known
static const uint32_t RECONNECT_MS = 5000;
static const int SCAN_MS = 10000;
static const uint8_t SPP_CHANNEL = 1;    // connecting to the channel directly skips the SDP lookup

enum Value : uint16_t {
  DeviceState = 6, BrakeMode = 7, Pulse = 8, Rpm = 9, PowerSet = 10, PowerGet = 11, PowerMin = 12, PowerMax = 13,
  Speed = 14, Distance = 15, Energy = 16, Time = 17, TimeMode = 18, DeviceName = 20, DeviceType = 24,
  DeviceId = 25, InPowerRange = 26, BrakeLevel = 27, BrakeLevelMin = 28, BrakeLevelMax = 29, SpeedGet = 35,
  Online = 38,
};
enum Instruction : uint8_t { Read = 1, Write = 2, Answer = 3 };
static const uint16_t CONSTANT_BRAKE = 1;

// ---- state shared with the web server task (guarded by `lock`)

static SemaphoreHandle_t lock;
static Data shared;
static bool shared_connected = false;
static bool shared_scanning = false;
static std::vector<Device> shared_scan;
static String target_mac, target_name;
static bool target_changed = false;
static int pending_brake = -1;
static bool scan_requested = false;

struct Guard {
  Guard() { xSemaphoreTake(lock, portMAX_DELAY); }
  ~Guard() { xSemaphoreGive(lock); }
};

// ---- CRC and framing

static uint16_t crc_table[256];

static void crc_init() {
  for (uint16_t i = 0; i < 256; i++) {
    uint16_t data = i, crc = 0;
    for (int bit = 0; bit < 8; bit++) {
      crc = ((data ^ crc) & 1) ? (crc >> 1) ^ 0x8408 : crc >> 1;
      data >>= 1;
    }
    crc_table[i] = crc;
  }
}

static uint16_t crc16(const uint8_t* bytes, size_t len) {
  uint16_t crc = 0;
  for (size_t i = 0; i < len; i++) crc = (crc >> 8) ^ crc_table[(crc ^ bytes[i]) & 0xFF];
  return crc;
}

static std::vector<uint8_t> out;  // bytes waiting for the Bluetooth link

static void send_framed(const uint8_t* payload, size_t len) {
  out.push_back(0x02);
  for (size_t i = 0; i < len; i++) {
    uint8_t b = payload[i];
    if (b == 0x02 || b == 0x03 || b == 0x10) {
      out.push_back(0x10);
      out.push_back(b ^ 0x20);
    } else {
      out.push_back(b);
    }
  }
  out.push_back(0x03);
  uint16_t crc = crc16(payload, len);
  out.push_back(crc >> 8);
  out.push_back(crc & 0xFF);
}

static void send(uint16_t value, uint8_t instr, const uint8_t* add = nullptr, uint16_t add_len = 0) {
  std::vector<uint8_t> p = {uint8_t(value >> 8), uint8_t(value), instr, uint8_t(add_len >> 8), uint8_t(add_len)};
  p.insert(p.end(), add, add + add_len);
  send_framed(p.data(), p.size());
}

static void read(uint16_t value) { send(value, Read); }
static void write_u8(uint16_t value, uint8_t v) { send(value, Write, &v, 1); }

static void send_handshake() {
  static const uint8_t hs[] = {0x00, 0x01, 0x01, 0x00, 0x12, 0x2d, 0x24, 0xf2, 0x24, 0x96, 0xa4, 0xff,
                               0x98, 0x29, 0xf9, 0x21, 0xbe, 0x9d, 0xaa, 0x9e, 0x4d, 0x01, 0x17};
  send_framed(hs, sizeof(hs));
}

// ---- incoming packets

struct Analyzer {
  std::vector<uint8_t> data;
  bool unescape = false, in_crc = false, first = true;
  int crc_bytes = 0;

  void reset() {
    data.clear();
    unescape = in_crc = false;
    first = true;
    crc_bytes = 0;
  }

  // true when `data` holds a complete packet (payload + 2 CRC bytes)
  bool next(uint8_t b) {
    if (first) {
      first = false;
      if (b != 0x02) reset();
      return false;
    }
    if (unescape) {
      unescape = false;
      if (b != 0x22 && b != 0x23 && b != 0x30) {
        reset();
        return false;
      }
      b ^= 0x20;
    } else if (b == 0x02) {
      reset();
      first = false;  // this byte starts the next packet
      return false;
    } else if (b == 0x03) {
      if (in_crc) reset();
      else in_crc = true;
      return false;
    } else if (b == 0x10) {
      unescape = true;
      return false;
    }
    data.push_back(b);
    if (in_crc) crc_bytes++;
    return crc_bytes == 2;
  }
};

static Analyzer analyzer;

static uint16_t u16(const uint8_t* b) { return (uint16_t(b[0]) << 8) | b[1]; }

static void handle_answer(Data& d, uint16_t value, const uint8_t* a, uint16_t n) {
  bool is16 = n == 2, is8 = n == 1;
  switch (value) {
    case Rpm: if (is16) { d.rpm = u16(a); d.has_rpm = true; } break;
    case PowerGet: if (is16) { d.power = u16(a); d.has_power = true; } break;
    case Pulse: if (is16) { d.pulse = u16(a); d.has_pulse = true; } break;
    case SpeedGet: if (is16) { d.speed = u16(a); d.has_speed = true; } break;
    case Distance: if (is16) { d.distance = u16(a); d.has_distance = true; } break;
    case Energy: if (is16) { d.energy = u16(a); d.has_energy = true; } break;
    case Time: if (is16) { d.time = u16(a); d.has_time = true; } break;
    case BrakeLevel: if (is8) { d.brake = a[0]; d.has_brake = true; } break;
    case BrakeLevelMin: if (is8) { d.brake_min = a[0]; d.has_brake_min = true; } break;
    case BrakeLevelMax: if (is8) { d.brake_max = a[0]; d.has_brake_max = true; } break;
    case Online: if (is8) { d.online = a[0] == 0; d.has_online = true; } break;  // the trainer reports 0 = online
    case DeviceType: if (is8) { d.device_type = char(a[0]); d.has_device_type = true; } break;
    case DeviceName: d.device_name = String(reinterpret_cast<const char*>(a), n); d.has_device_name = true; break;
    default: break;
  }
}

static void handle_packet(const std::vector<uint8_t>& pkg) {
  if (pkg.size() < 7) return;
  size_t len = pkg.size() - 2;
  if (u16(&pkg[len]) != crc16(pkg.data(), len)) return;
  uint16_t add_len = u16(&pkg[3]);
  if (pkg[2] != Answer || len != size_t(add_len) + 5) return;
  Guard g;
  handle_answer(shared, u16(&pkg[0]), &pkg[5], add_len);
}

// ---- worker task

static void set_connected(bool c) {
  Guard g;
  shared_connected = c;
  if (!c) shared = Data();  // stale values must not look live
}

static void do_scan() {
  { Guard g; shared_scanning = true; }
  if (bt.connected()) bt.disconnect();
  set_connected(false);
  std::vector<Device> found;
  BTScanResults* res = bt.discover(SCAN_MS);
  if (res) {
    for (int i = 0; i < res->getCount(); i++) {
      BTAdvertisedDevice* dev = res->getDevice(i);
      String name = dev->haveName() ? String(dev->getName().c_str()) : String();
      String upper = name;
      upper.toUpperCase();
      bool k = upper.indexOf("KETTLER") >= 0 || upper.startsWith("RACER") || upper.startsWith("ERGO");
      found.push_back({String(dev->getAddress().toString().c_str()), name, dev->haveRSSI() ? dev->getRSSI() : 0, k});
    }
    bt.discoverClear();
  }
  std::sort(found.begin(), found.end(), [](const Device& a, const Device& b) {
    return a.kettler != b.kettler ? a.kettler : a.rssi > b.rssi;
  });
  Guard g;
  shared_scan = found;
  shared_scanning = false;
}

static bool parse_mac(const String& s, uint8_t mac[6]) {
  unsigned v[6];
  if (sscanf(s.c_str(), "%x:%x:%x:%x:%x:%x", &v[0], &v[1], &v[2], &v[3], &v[4], &v[5]) != 6) return false;
  for (int i = 0; i < 6; i++) mac[i] = uint8_t(v[i]);
  return true;
}

static bool try_connect(const String& mac_str) {
  uint8_t mac[6];
  if (!parse_mac(mac_str, mac)) return false;
  Serial.printf("[kettler] connecting to %s\n", mac_str.c_str());
  if (!bt.connect(mac, SPP_CHANNEL, ESP_SPP_SEC_NONE, ESP_SPP_ROLE_MASTER)) return false;
  Serial.println("[kettler] connected");
  analyzer.reset();
  out.clear();
  send_handshake();
  return true;
}

static void task(void*) {
  uint32_t last_fast = 0, last_medium = 0, last_slow = 0, last_static = 0, last_attempt = 0;
  for (;;) {
    bool scan, changed;
    String mac;
    int brake;
    {
      Guard g;
      scan = scan_requested;
      scan_requested = false;
      changed = target_changed;
      target_changed = false;
      mac = target_mac;
      brake = pending_brake;
      pending_brake = -1;
    }
    if (scan) do_scan();
    if (changed && bt.connected()) {
      bt.disconnect();
      set_connected(false);
    }

    if (!bt.connected()) {
      if (connected()) set_connected(false);
      uint32_t now = millis();
      if (mac.length() && (changed || scan || now - last_attempt >= RECONNECT_MS)) {
        last_attempt = now;
        if (try_connect(mac)) {
          set_connected(true);
        } else {
          bt.disconnect();
        }
      }
      vTaskDelay(pdMS_TO_TICKS(50));
      continue;
    }

    while (bt.available() > 0) {
      if (analyzer.next(uint8_t(bt.read()))) {
        handle_packet(analyzer.data);
        analyzer.reset();
      }
    }

    if (brake >= 0) {
      // every time, like NaKole: the trainer drops out of online / constant brake mode on its own,
      // and then ignores a bare level
      write_u8(Online, 0);
      write_u8(BrakeMode, CONSTANT_BRAKE);
      write_u8(BrakeLevel, uint8_t(brake));
    }

    uint32_t now = millis();
    if (now - last_fast >= FAST_MS) {
      last_fast = now;
      read(Rpm);
      read(PowerGet);
      read(Pulse);
      read(SpeedGet);
    }
    if (now - last_medium >= MEDIUM_MS) {
      last_medium = now;
      read(BrakeLevel);
      read(Online);
    }
    if (now - last_slow >= SLOW_MS) {
      last_slow = now;
      read(Distance);
      read(Energy);
      read(Time);
    }
    if (now - last_static >= STATIC_MS) {
      last_static = now;
      Data d = data();
      if (!d.has_device_type) read(DeviceType);
      if (!d.has_device_name) read(DeviceName);
      if (!d.has_brake_min) read(BrakeLevelMin);
      if (!d.has_brake_max) read(BrakeLevelMax);
    }

    if (!out.empty()) {
      size_t n = bt.write(out.data(), out.size());
      out.erase(out.begin(), out.begin() + n);
    }
    vTaskDelay(pdMS_TO_TICKS(2));
  }
}

// ---- public API

void begin(const char* btName) {
  lock = xSemaphoreCreateMutex();
  crc_init();
  if (!bt.begin(btName, true)) {  // master: the ESP32 connects to the trainer
    Serial.println("[kettler] Bluetooth start failed");
    return;
  }
  bt.enableSSP();
  xTaskCreatePinnedToCore(task, "kettler", 8192, nullptr, 1, nullptr, 0);
}

void setTarget(const String& mac, const String& name) {
  Guard g;
  target_mac = mac;
  target_name = name;
  target_changed = true;
}

void setBrake(int level) {
  Guard g;
  pending_brake = level;
}

void requestScan() {
  Guard g;
  scan_requested = true;
  shared_scanning = true;  // visible at once, before the task picks it up
}

bool connected() { Guard g; return shared_connected; }
bool scanning() { Guard g; return shared_scanning; }
String targetMac() { Guard g; return target_mac; }
String targetName() { Guard g; return target_name; }
Data data() { Guard g; return shared; }
std::vector<Device> scanResults() { Guard g; return shared_scan; }

}  // namespace kettler
