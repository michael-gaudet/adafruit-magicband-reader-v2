# Magic Band Reader V2 (ESP32-S3 + Home Assistant Webhook)
This is a “V2” modernization of Adafruit’s Magic Band Reader project, adapted to:
- Use an Adafruit Feather **ESP32-S3** (with on-board Wi-Fi)
- Use [Home Assistant](https://www.home-assistant.io/) webhook integration (device triggers HA, behavior lives in HA)

# Original Adafruit Project
The original adafruit project can be found here:
https://learn.adafruit.com/magic-band-reader/
That guide calls for a Feather RP2040, which has no real connectivity functionality. Those instructions work great as-is, except it was difficult to find the specific NeoPixel strip those instructions called for.

But wouldn't it be great to actually have your scan interaction actually... *do* something?

## Hardware
The hardware used here uses the same amp, speaker, etc. called for by the original project, with some changes/additions.
- [Adafruit Feather ESP32-S3 (4MB Flash / 2MB PSRAM) (PID 5477)](https://learn.adafruit.com/adafruit-esp32-s3-feather/overview)
- MAX98357A I2S 3W Class-D Amp
- RFID “Wiz” module (used for its `SIG` output)
- [NeoPixel edge-lit strip](https://www.adafruit.com/product/4911) (trimmed to fit: **16 LEDs** in the diffuser ring) since the original strip called for is always out of stock
- 470Ω resistor (data line) for improved LED performance
- 470–1000µF electrolytic capacitor (across NeoPixel power input) for improved LED performance

## Firmware Setup (ESP32-S3 + CircuitPython)

### Flashing CircuitPython
This Feather did not accept UF2 drag-and-drop reliably in our case.
We flashed CircuitPython using **Microsoft Edge** and Adafruit’s web-based ESP tool.

1. Put the Feather into bootloader mode
2. Use Adafruit’s ESP Web Flasher in Edge to flash CircuitPython
3. After flashing, the board should present a `CIRCUITPY` drive

## CircuitPython
Download `code.py` in this repo into the `CIRCUITPY` drive.

Make sure you properly eject the drive in Windows before disconnecting it to avoid any data issues.

## Pinout / Wiring

### NeoPixels (edge-lit strip)
- **DATA**: Feather **D6** → **470Ω** resistor → NeoPixel **DIN**
- **5V**: Feather **USB** pin → NeoPixel **+5V**
- **GND**: Feather **GND** → NeoPixel **GND**
- **Capacitor**: 470–1000µF across NeoPixel +5V/GND near the strip input
  - capacitor **+** to +5V, capacitor **-** (striped side) to GND

### Audio (MAX98357A)
- **VIN**: Feather **3.3V**
- **GND**: Feather **GND**
- **BCLK**: Feather **D10**
- **LRC/WS**: Feather **D9**
- **DIN**: Feather **D11**
- Speaker to amp output terminals

### RFID Wiz (SIG output only)
- **SIG**: Feather **A1** (configured as input w/ pull-down)
- **GND**: Feather **GND**
- Note: the Wiz typically requires its own power arrangement (often 12V) depending on module behavior/revision.

## Home Assistant Integration

This project triggers Home Assistant using a webhook URL of the form:
> http://:8123/api/webhook/<webhook_id>

On the device, HA connection settings live in `settings.toml`.

### settings.toml (example)
Create `CIRCUITPY/settings.toml` (do not commit it):

```toml
CIRCUITPY_WIFI_SSID="YourSSID"
CIRCUITPY_WIFI_PASSWORD="YourPassword"

HA_BASE_URL="http://192.168.1.123:8123"
HA_WEBHOOK_ID="YOUR_WEBHOOK_ID"
HA_METHOD="POST"
```

# Behavior
* Idle: LEDs off, with a subtle heartbeat glow every ~10s
* Scan: warm-white chase while the HA call runs
* Success: pulse green for 3 seconds + play a success WAV
* Failure: pulse red for 3 seconds (no audio)

# Libraries

Install the Adafruit CircuitPython Bundle for your CircuitPython major version and copy required libraries into lib/:
* neopixel
* adafruit_led_animation
* adafruit_requests
* adafruit_connection_manager
* dependencies pulled in by the above

# Credits

Based on Adafruit’s “Magic Band Reader” guide, adapted for ESP32-S3 + Home Assistant webhook control.
