# Most trenažéru (ESP32)

ESP32 mezi trenažérem **Kettler** (Bluetooth Classic, protokol KDRI) a aplikací OpenRide (Wi-Fi, HTTP JSON API). Most nemá vlastní aplikaci; trenažér ovládá OpenRide v prohlížeči (stránka **Trenažér**, HUD v jízdě).

## Nahrání

```sh
cd firmware
pio run -t upload          # ESP32 přes USB
pio device monitor         # log (115200 Bd)
```

## První nastavení

1. Most bez uložené Wi-Fi vysílá otevřenou síť **NaKole-xxxx**. Připoj se k ní; nastavovací stránka se otevře sama (jinak http://192.168.4.1/).
2. **Wi-Fi**: vyber domácí síť a zadej heslo. Uloží se, až když se připojení podaří; most se pak restartuje a setup síť zmizí.
3. **Kettler**: zapni trenažér, „Vyhledat Bluetooth zařízení“ (~10 s), u Kettleru „Vybrat“. Jde to i později v OpenRide.
4. Most je pak v síti jako **http://nakole.local** (nebo na IP z nastavovací stránky / logu). V OpenRide na stránce Trenažér zadej adresu, pokud `nakole.local` v tvé síti nefunguje (např. Android).

Wi-Fi i Kettler se pamatují (NVS). Zapomenout: v OpenRide (Trenažér → Zapomenout Kettler / Zapomenout Wi-Fi), nebo **podržením tlačítka BOOT 5 s** (zapomene obojí a restartuje do setup režimu).

## API

CORS je povolený pro všechny originy (volá ho prohlížeč s OpenRide); bez autentizace, určeno pro domácí síť.

| Metoda a cesta | Tělo | Odpověď |
|---|---|---|
| `GET /api/status` | | `{version, mode: setup/station, wifi: {ssid, connected, ip, rssi}, kettler: {mac, name, connected, scanning, devices: [{mac, name, rssi, kettler}]}, data: {rpm, power, pulse, speed, brake, brake_min, brake_max, distance, energy, time, online, device_name, device_type}}` (hodnoty `null`, dokud je trenažér nenahlásí) |
| `POST /api/brake` | `{"brake": 7}` | nastaví úroveň brzdy (oříznutou na rozsah trenažéru); s každou úrovní pošle i „online“ a režim konstantní brzdy. `503`, když Kettler není připojen |
| `POST /api/kettler/scan` | | spustí vyhledání (~10 s; během něj se Kettler odpojí), výsledky v `status.kettler.devices` |
| `POST /api/kettler` | `{"mac": "00:80:25:43:6D:20", "name": "RACER RS 436D20"}` | uloží a připojí Kettler |
| `POST /api/kettler/forget` | | zapomene Kettler a odpojí ho |
| `POST /api/wifi/forget` | | zapomene Wi-Fi a restartuje do setup režimu |
| `GET /api/wifi/scan` | | okolní sítě `[{ssid, rssi, open}]` |
| `POST /api/wifi` | `{"ssid": "…", "password": "…"}` | jen v setup režimu: vyzkouší připojení, při úspěchu uloží a restartuje |

## Struktura

| Soubor | |
|---|---|
| `src/main.cpp` | Wi-Fi (setup síť s captive portálem / domácí síť + mDNS), HTTP API, tlačítko BOOT |
| `src/kettler.cpp` | Bluetooth, protokol Kettleru (rámce, escapování, CRC16, handshake), čtení hodnot a příkazy; běží ve vlastní FreeRTOS úloze, takže připojování Kettleru neblokuje API |
| `src/config.cpp` | uložení nastavení (NVS) |
| `src/setup_page.h` | nastavovací stránka |

Protokol je převzatý z projektu NaKole (github.com/OndrejIT/NaKole, původně z Rust implementace) a ověřený na Kettleru RACER RS; jiné modely Kettleru se stejným protokolem by měly fungovat, neověřeno.
