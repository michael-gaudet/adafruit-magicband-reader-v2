# Magic Band Reader V2 (ESP32-S3 + Home Assistant Webhook)
This is an iteration on Adafruit’s Magic Band Reader project, adapted to:
- Use an Adafruit Feather **ESP32-S3** (with on-board Wi-Fi), so we can integrate it as an IoT device
- Use the Elechouse V4 NFC chip, so we know the actual ID of the scanned tag
- Call a [Home Assistant](https://www.home-assistant.io/) webhook, so scanned tags can do different things -- like play music, turn on lights in your house, etc.

# Original Adafruit Project
The original adafruit project can be found here:
https://learn.adafruit.com/magic-band-reader/
Those instructions work great as-is, except it was difficult to find the specific NeoPixel strip those instructions called for. That guide calls for a Feather RP2040, which has no external connectivity functionality. It also uses the RFID Wiz kit, which is great for controlling doors or latches or whatever, but won't let you know _which_ tag was scanned. It only knows if a tag scanned was previously learned or not.

Wouldn't it be great to actually have your scan interaction actually... *do* something?

## Hardware
The hardware used here uses the same amp, speaker, etc. called for by the original project, with some changes/additions.
- [Adafruit Feather ESP32-S3 (4MB Flash / 2MB PSRAM) (PID 5477)](https://learn.adafruit.com/adafruit-esp32-s3-feather/overview)
- MAX98357A I2S 3W Class-D Amp
- Elechouse NFC V4 chip (NOTE: The RFID Wiz kit includes the V3 chip. This one has a better range and support for other bands.)
- [NeoPixel edge-lit strip](https://www.adafruit.com/product/4911) (trimmed to fit: **16 LEDs** in the diffuser ring) since the original strip called for is always out of stock
- 470Ω resistor (data line) for improved LED performance
- 470–1000µF electrolytic capacitor (across NeoPixel power input) for improved LED performance

## Firmware Setup (ESP32-S3 + CircuitPython)

### Flashing CircuitPython
This Feather did not accept UF2 drag-and-drop reliably in our case.
We flashed CircuitPython using **Microsoft Edge** and Adafruit’s web-based ESP tool.

1. Put the Feather into bootloader mode
2. Use Adafruit’s ESP Web Flasher in Edge to flash CircuitPython [here](https://circuitpython.org/board/adafruit_feather_esp32s3_4mbflash_2mbpsram/)
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

### Elechouse NFC V4
I used some of the ribbon cable called for in the original project to make a 24cm / 9" lead of 4 wires. Tip: It's a lot easier to pull these wires through the neck of the scanner if you slide the ends of the ribbon cable into some shrinkwrap tube first!
- **VCC**: Feather **3.3V**
- **GND**: Feather **GND**
- **SDA**: Feather **SDA**
- **SCL**: Feather **SCL**

## Home Assistant Integration

This project triggers Home Assistant using a webhook URL of the form:
> http://:8123/api/webhook/<webhook_id>

On the device, HA connection settings live in `settings.toml`.

### settings.toml (example)
Create `CIRCUITPY/settings.toml`:

```toml
CIRCUITPY_WIFI_SSID="YourSSID"
CIRCUITPY_WIFI_PASSWORD="YourPassword"
HA_BASE_URL="http://192.168.x.x:8123"
HA_WEBHOOK_ID="YOUR_WEBHOOK_ID"
HA_METHOD="POST"
DEVICE_NAME="your_device_name_here"
```

# Behavior
* Idle: LEDs off, with a heartbeat blink every ~10s
* Scan: warm-white chase while the HA call runs
* Success: pulse green for 3 seconds + play a success WAV
* Failure: pulse red for 3 seconds (no audio)

# Libraries

Install the Adafruit CircuitPython Bundle for your CircuitPython major version and copy required libraries into lib/:
* adafruit_led_animation (directory)
* adafruit_pn532 (directory)
* adafruit_connection_manager.mpy
* adafruit_pixelbuf.mpy
* adafruit_requests.mpy
* neopixel.mpy

# Credits

Based on Adafruit’s “Magic Band Reader” guide, adapted for ESP32-S3 + Home Assistant webhook control.
