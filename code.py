# code.py
#
# MagicBand Reader V3 (ESP32-S3 + PN532 UID + Home Assistant Webhook + NeoPixels + I2S Audio)
#
# Goals:
# - Read PN532 tag UID over I2C, normalize as "AA:BB:CC..."
# - POST JSON payload to Home Assistant webhook: {"uid": "...", ...}
# - Keep a chase animation running WHILE waiting for the HTTP response (no “frozen” chase)
# - Show a yellow chase while booting (PN532 init, Wi-Fi connect, etc.)
# - Be resilient to cold-boot PN532 timing (retry init)
#
# Notes:
# - The non-freezing chase during webhook uses a raw NON-BLOCKING socket.
# - That approach is implemented for http:// HA_BASE_URL (LAN) which matches your `local_only: true`.
# - If you set HA_BASE_URL to https://, this code will raise with a clear message.

import os
import json
import random
import time
import math
import microcontroller
import board
import busio
import wifi
import audiobusio
from audiocore import WaveFile
import neopixel

import adafruit_connection_manager

from adafruit_pn532.i2c import PN532_I2C

from adafruit_led_animation.animation.chase import Chase
from adafruit_led_animation.animation.solid import Solid
from adafruit_led_animation.color import BLACK


# -----------------------------
# Config
# -----------------------------
PIXEL_PIN = board.D6
PIXEL_COUNT = 16 # How many LED pixels in your strip, depends on what kind of NeoPixel strip you got and how tightly it's in there
PIXEL_BRIGHTNESS = 0.5  # global cap

# Boot animation (yellow chase)
BOOT_COLOR = (140, 120, 0)
BOOT_CHASE_SIZE = 5
BOOT_CHASE_SPEED = 0.04

# Warm "white" for chase (less blue, more amber)
WARM_WHITE = (180, 160, 120)
CHASE_SIZE = 4
CHASE_SPEED = 0.03

# Idle heartbeat: very subtle glow for a brief moment every 10s
IDLE_HEARTBEAT_INTERVAL_S = 15.0
IDLE_HEARTBEAT_DURATION_S = 0.8
IDLE_HEARTBEAT_COLOR = (9, 6, 3)  # very dim warm glow (0–255)

# Pulse timing
PULSE_STEPS = 60  # higher = smoother
SUCCESS_COLOR = (0, 120, 0)  # medium green
FAIL_COLOR = (120, 0, 0)     # medium red

PRE_CALL_CHASE_SECONDS = 2.0

WAV_DIR = "sounds"
SUCCESS_SOUNDS = [
    "chime",
    "excellent",
    "hello",
    "operational",
    "startours",
]
# (Intentionally no failure sounds)

# HA Webhook (from settings.toml)
HA_BASE_URL = os.getenv("HA_BASE_URL")
WEBHOOK_ID = os.getenv("HA_WEBHOOK_ID")
HA_METHOD = (os.getenv("HA_METHOD") or "POST").upper()

# Device name - should be kept unique, so HomeAssistant knows where the request is coming from
DEVICE_NAME = os.getenv("DEVICE_NAME") or "magicband_v3"

HTTP_TIMEOUT = 5.0  # seconds overall for connect+send+recv
RETRIGGER_COOLDOWN_S = 1.5
TAG_PRESENT_RELEASE_S = 0.8

if not HA_BASE_URL or not WEBHOOK_ID:
    raise RuntimeError("Missing HA_BASE_URL and/or HA_WEBHOOK_ID in settings.toml")

# For the non-blocking socket approach we require plain HTTP.
if not HA_BASE_URL.startswith("http://"):
    raise RuntimeError(
        "HA_BASE_URL must start with http:// for non-blocking chase during webhook.\n"
        "Use a local IP like: http://192.168.x.x:8123 (matches local_only: true)."
    )

if HA_METHOD not in ("POST", "PUT"):
    raise RuntimeError("HA_METHOD must be POST or PUT (or omit it for default POST).")


# -----------------------------
# NeoPixels + Animations
# -----------------------------
pixels = neopixel.NeoPixel(
    PIXEL_PIN,
    PIXEL_COUNT,
    brightness=PIXEL_BRIGHTNESS,
    auto_write=False
)
# Initialize to off, otherwise we see a couple pixels light up weirdly
pixels.fill((0, 0, 0))
pixels.show()

boot_chase = Chase(
    pixels,
    speed=BOOT_CHASE_SPEED,
    color=BOOT_COLOR,
    size=BOOT_CHASE_SIZE,
    spacing=max(1, PIXEL_COUNT - BOOT_CHASE_SIZE),
)

chase = Chase(
    pixels,
    speed=CHASE_SPEED,
    color=WARM_WHITE,
    size=CHASE_SIZE,
    spacing=max(1, PIXEL_COUNT - CHASE_SIZE),
)

idle = Solid(pixels, color=BLACK)
last_heartbeat = time.monotonic()


def idle_heartbeat_if_due():
    global last_heartbeat
    now = time.monotonic()
    if now - last_heartbeat >= IDLE_HEARTBEAT_INTERVAL_S:
        pulse_sine(IDLE_HEARTBEAT_COLOR, seconds=IDLE_HEARTBEAT_DURATION_S)
        pixels.fill((0, 0, 0))
        pixels.show()
        last_heartbeat = time.monotonic()

def pre_call_chase(seconds=PRE_CALL_CHASE_SECONDS):
    t_end = time.monotonic() + seconds
    while time.monotonic() < t_end:
        chase.animate()
        time.sleep(0.01)

def ensure_wifi():
    if not wifi.radio.connected:
        print("Wi-Fi dropped, reconnecting...")
        init_wifi_with_retries()


# -----------------------------
# Audio (MAX98357A via I2S)
# -----------------------------
audio = audiobusio.I2SOut(
    bit_clock=board.D10,
    word_select=board.D9,
    data=board.D11,
)


# -----------------------------
# Helpers
# -----------------------------
def uid_to_str(uid_bytes) -> str:
    return ":".join("{:02X}".format(b) for b in uid_bytes)


def pulse_sine_step(color, i, steps):
    r0, g0, b0 = color
    t = (i / steps) * math.pi      # 0..pi
    k = math.sin(t)                # 0..1..0
    k = 0.25 + 0.75 * k            # keep it from going fully off
    return (int(r0 * k), int(g0 * k), int(b0 * k))


def pulse_sine(color, seconds, steps=PULSE_STEPS):
    dt = seconds / steps
    for i in range(steps + 1):
        pixels.fill(pulse_sine_step(color, i, steps))
        pixels.show()
        time.sleep(dt)


def pulse_green_and_play_success_sound():
    sound = random.choice(SUCCESS_SOUNDS)
    path = f"{WAV_DIR}/{sound}.wav"
    print("SUCCESS: playing:", path)

    with open(path, "rb") as f:
        wave = WaveFile(f)
        audio.play(wave)
        # Visual duration is fixed; not tied to audio length
        pulse_sine(SUCCESS_COLOR, seconds=3)


def _parse_http_base(url: str):
    # Supports http://host:port
    u = url[len("http://"):]
    if "/" in u:
        hostport, _ = u.split("/", 1)
    else:
        hostport = u

    if ":" in hostport:
        host, port_s = hostport.split(":", 1)
        port = int(port_s)
    else:
        host, port = hostport, 80

    return host, port


def init_wifi_with_retries(max_tries=5, delay_s=0.25):
    ssid = os.getenv("CIRCUITPY_WIFI_SSID")
    pw = os.getenv("CIRCUITPY_WIFI_PASSWORD")
    if not ssid or not pw:
        raise RuntimeError("Missing CIRCUITPY_WIFI_SSID and/or CIRCUITPY_WIFI_PASSWORD in settings.toml")

    print("Connecting Wi-Fi...")
    last_err = None
    for attempt in range(1, max_tries + 1):
        try:
            boot_chase.animate()
            wifi.radio.connect(ssid, pw)
            print("Wi-Fi connected:", wifi.radio.ipv4_address)
            return
        except Exception as e:
            last_err = e
            print(f"Wi-Fi connect failed (attempt {attempt}/{max_tries}): {repr(e)}")
            # keep animating while we wait
            t_end = time.monotonic() + delay_s
            while time.monotonic() < t_end:
                boot_chase.animate()
                time.sleep(0.01)

    raise RuntimeError(f"Wi-Fi failed to connect after {max_tries} attempts: {last_err}")


def init_pn532_with_retries(max_tries=20, delay_s=0.25, first_delay_s=0.6):
    """
    Cold boot: PN532 can be slow to respond.
    IMPORTANT: Don't recreate busio.I2C repeatedly without deinit, or you'll get 'SCL in use'.

    Strategy:
    - Create I2C once
    - Retry PN532_I2C + SAM_configuration on that bus
    - Animate boot chase while waiting
    """
    print("Initializing PN532...")

    # Create I2C ONCE
    i2c_local = busio.I2C(board.SCL, board.SDA)

    # Wait for the bus to become ready
    t_end = time.monotonic() + 1.5
    while time.monotonic() < t_end:
        boot_chase.animate()
        time.sleep(0.01)

    # Give PN532 some time after power-up
    t_end = time.monotonic() + first_delay_s
    while time.monotonic() < t_end:
        boot_chase.animate()
        time.sleep(0.01)

    last_err = None
    for attempt in range(1, max_tries + 1):
        try:
            boot_chase.animate()
            pn = PN532_I2C(i2c_local, debug=False)
            pn.SAM_configuration()
            print(f"PN532 ready (attempt {attempt}/{max_tries}).")
            return pn

        except ValueError as e:
            # Typical: "No I2C device at address: 0x24"
            last_err = e
            print(f"PN532 not responding yet (attempt {attempt}/{max_tries}): {e}")

        except Exception as e:
            last_err = e
            print(f"PN532 init error (attempt {attempt}/{max_tries}): {repr(e)}")

        # Animate during backoff
        t_end = time.monotonic() + delay_s
        while time.monotonic() < t_end:
            boot_chase.animate()
            time.sleep(0.01)

    raise RuntimeError(f"PN532 failed to initialize after {max_tries} attempts: {last_err}")

def ha_webhook_call_nonblocking(uid_str: str) -> bool:
    """
    Make the webhook call while keeping the chase animation moving.

    Uses repeated SHORT-TIMEOUT blocking connect attempts (more reliable than true
    non-blocking connect on ESP32 socketpool), then sends/receives in small chunks
    while animating.
    """
    payload = {
        "event": "rfid_scan",
        "ts": time.time(),
        "device_name": DEVICE_NAME,
        "uid": uid_str,
    }
    body = json.dumps(payload).encode("utf-8")

    host, port = _parse_http_base(HA_BASE_URL)
    path = f"/api/webhook/{WEBHOOK_ID}"

    req = (
        f"{HA_METHOD} {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode("utf-8") + body

    sp = adafruit_connection_manager.get_radio_socketpool(wifi.radio)

    # ---- CONNECT (short timeout attempts) ----
    t_start = time.monotonic()
    s = None
    while (time.monotonic() - t_start) < HTTP_TIMEOUT:
        chase.animate()
        try:
            s = sp.socket(sp.AF_INET, sp.SOCK_STREAM)
            s.settimeout(0.25)  # short blocking timeout
            s.connect((host, port))
            break
        except OSError:
            try:
                if s:
                    s.close()
            except Exception:
                pass
            s = None
            time.sleep(0.01)

    if not s:
        print("Webhook connect timeout")
        return False

    # ---- SEND (may also need to yield/animate) ----
    s.settimeout(0.25)
    sent = 0
    t_send = time.monotonic()
    while sent < len(req) and (time.monotonic() - t_send) < HTTP_TIMEOUT:
        chase.animate()
        try:
            n = s.send(req[sent:])
            if n:
                sent += n
        except OSError:
            time.sleep(0.01)

    if sent < len(req):
        try:
            s.close()
        except Exception:
            pass
        print("Webhook send timeout")
        return False

    # ---- RECV (read until we get status line) ----
    buf = b""
    tmp = bytearray(128)

    t_recv = time.monotonic()
    while (time.monotonic() - t_recv) < HTTP_TIMEOUT:
        chase.animate()
        try:
            n = s.recv_into(tmp)  # <-- CircuitPython socketpool uses recv_into
            if n and n > 0:
                buf += bytes(tmp[:n])
            else:
                break
        except OSError:
            time.sleep(0.01)

        # As soon as we have the status line, decide
        if b"\r\n" in buf:
            line = buf.split(b"\r\n", 1)[0].decode("utf-8", "ignore")
            parts = line.split(" ")
            if len(parts) >= 2 and parts[1].isdigit():
                code = int(parts[1])
                print("HA webhook status:", code)
                try:
                    s.close()
                except Exception:
                    pass
                return 200 <= code < 300



# -----------------------------
# Boot sequence (yellow chase while we get ready)
# -----------------------------
print("Booting...")

try:
    # 1) Init PN532 (retry on cold boot)
    pn532 = init_pn532_with_retries()

    # 2) Connect Wi-Fi (retry)
    init_wifi_with_retries()

    print("Boot complete. Ready to scan.")
    pulse_sine(SUCCESS_COLOR, seconds=2)
    pixels.fill((0, 0, 0))
    pixels.show()

except RuntimeError as e:
    print("Boot failed:", e)
    pulse_sine(FAIL_COLOR, seconds=3)
    pixels.fill((0, 0, 0))
    pixels.show()
    time.sleep(10)
    microcontroller.reset()


# -----------------------------
# Main loop
# -----------------------------
last_uid_sent = None
last_uid_sent_at = 0.0
last_seen_uid_at = 0.0

while True:
    uid = pn532.read_passive_target(timeout=0.2)
    now = time.monotonic()

    if uid is None:
        idle.animate()
        idle_heartbeat_if_due()

        # If we previously saw a tag, track when it "fully left"
        if last_seen_uid_at and (now - last_seen_uid_at) > TAG_PRESENT_RELEASE_S:
            last_uid_sent = None
            last_seen_uid_at = 0.0

        time.sleep(0.01)
        continue

    # Tag present
    uid_str = uid_to_str(uid)
    last_seen_uid_at = now

    # Debounce/cooldown: don't spam HA while tag sits there
    if last_uid_sent == uid_str and (now - last_uid_sent_at) < RETRIGGER_COOLDOWN_S:
        time.sleep(0.02)
        continue

    print("Tag detected UID:", uid_str)

    # Fake loading ring to simulate checking!
    pre_call_chase()
    
    # Make sure there is a valid Wi-Fi connection before attempting the webhook call, and if not, try to reconnect.
    try:
        ensure_wifi()
    except RuntimeError as e:
        print("Wi-Fi reconnect failed:", e)
        pulse_sine(FAIL_COLOR, seconds=3)
        last_uid_sent = uid_str
        last_uid_sent_at = time.monotonic()
        continue

    ok = ha_webhook_call_nonblocking(uid_str)

    if ok:
        print("Webhook result: SUCCESS")
        pulse_green_and_play_success_sound()
    else:
        print("Webhook result: FAIL")
        pulse_sine(FAIL_COLOR, seconds=3)

    last_uid_sent = uid_str
    last_uid_sent_at = time.monotonic()

    # Back to polling quickly
    time.sleep(0.05)
