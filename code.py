import random
import time
import math

import board
import digitalio
import audiobusio
from audiocore import WaveFile
import neopixel

from adafruit_led_animation.animation.chase import Chase
from adafruit_led_animation.animation.solid import Solid
from adafruit_led_animation.color import BLACK

import os
import wifi
import socketpool
import ssl
import adafruit_connection_manager
import adafruit_requests


# -----------------------------
# Config
# -----------------------------
PIXEL_PIN = board.D6
PIXEL_COUNT = 16
PIXEL_BRIGHTNESS = 0.2  # global cap

# Warm "white" for chase (less blue, more amber)
WARM_WHITE = (180, 160, 120)

CHASE_SIZE = 4
CHASE_SPEED = 0.03

# Idle heartbeat: very subtle glow for a brief moment every 10s
IDLE_HEARTBEAT_INTERVAL_S = 10.0
IDLE_HEARTBEAT_DURATION_S = 0.25
IDLE_HEARTBEAT_COLOR = (8, 6, 3)  # very dim warm glow (0–255)

# Simulated HTTPS call
SIMULATED_CALL_SECONDS = 2.0

# Pulse timing
PULSE_SECONDS = 0.5
PULSE_STEPS = 40  # higher = smoother
SUCCESS_COLOR = (0, 120, 0)  # medium green
FAIL_COLOR = (120, 0, 0)     # medium red

WAV_DIR = "sounds"  # change if needed
SUCCESS_SOUNDS = [
    "chime",
    "excellent",
    "hello",
    "operational",
    "startours",
]
# (Intentionally no failure sounds)

# HA Webhook - set these in settings.toml
HA_BASE_URL = os.getenv("HA_BASE_URL")
WEBHOOK_ID = os.getenv("HA_WEBHOOK_ID")
WEBHOOK_URL = f"{HA_BASE_URL}/api/webhook/{WEBHOOK_ID}"
HTTP_TIMEOUT = 5  # seconds


# -----------------------------
# RFID Wiz "SIG" input (active-high)
# -----------------------------
sig = digitalio.DigitalInOut(board.A1)
sig.switch_to_input(pull=digitalio.Pull.DOWN)

# -----------------------------
# I2S Audio
# -----------------------------
audio = audiobusio.I2SOut(
    bit_clock=board.D10,
    word_select=board.D9,
    data=board.D11,
)

# -----------------------------
# NeoPixels
# -----------------------------
pixels = neopixel.NeoPixel(
    PIXEL_PIN,
    PIXEL_COUNT,
    brightness=PIXEL_BRIGHTNESS,
    auto_write=False
)

chase = Chase(
    pixels,
    speed=CHASE_SPEED,
    color=WARM_WHITE,
    size=CHASE_SIZE,
    spacing=PIXEL_COUNT - CHASE_SIZE
)

idle = Solid(pixels, color=BLACK)

last_heartbeat = time.monotonic()

# -----------------------------
# Wi-Fi + Requests
# -----------------------------
print("Connecting Wi-Fi...")
wifi.radio.connect(
    # These are set in settings.toml
    os.getenv("CIRCUITPY_WIFI_SSID"),
    os.getenv("CIRCUITPY_WIFI_PASSWORD")
)
print("Wi-Fi connected:", wifi.radio.ipv4_address)

pool = adafruit_connection_manager.get_radio_socketpool(wifi.radio)
ssl_context = adafruit_connection_manager.get_radio_ssl_context(wifi.radio)
requests = adafruit_requests.Session(pool, ssl_context)

def idle_heartbeat_if_due():
    global last_heartbeat
    now = time.monotonic()
    if now - last_heartbeat >= IDLE_HEARTBEAT_INTERVAL_S:
        pixels.fill(IDLE_HEARTBEAT_COLOR)
        pixels.show()
        time.sleep(IDLE_HEARTBEAT_DURATION_S)
        pixels.fill((0, 0, 0))
        pixels.show()
        last_heartbeat = now

def simulated_https_call():
    """Simulate a 2s network call while showing chase animation."""
    t_end = time.monotonic() + SIMULATED_CALL_SECONDS
    while time.monotonic() < t_end:
        chase.animate()
    return random.choice([True])

def ha_webhook_call():
    """
    Call Home Assistant webhook. Returns True on HTTP 2xx, else False.
    """
    payload = {
        "event": "rfid_scan",
        "ts": time.time(),   # seconds since boot epoch in CircuitPython (ok for debugging)
        "device": "magicband_v2" # RFID Wiz doesn't give us a device ID, but maybe future hardware will let us read that data
    }

    try:
        # Start chase for a moment to indicate "sending"
        t_end = time.monotonic() + 2
        while time.monotonic() < t_end:
            chase.animate()

        # Make the actual request
        # Use POST (or PUT) — your automation allows both.
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=HTTP_TIMEOUT)
        ok = 200 <= resp.status_code < 300
        print("HA webhook status:", resp.status_code)
        resp.close()
        return ok

    except Exception as e:
        print("HA webhook error:", repr(e))
        return False

def pulse_sine_step(color, i, steps):
    """One step of a sine-ish pulse, returns RGB tuple for this frame."""
    r0, g0, b0 = color
    t = (i / steps) * math.pi      # 0..pi
    k = math.sin(t)                # 0..1..0
    k = 0.25 + 0.75 * k            # keep it from going fully off
    return (int(r0 * k), int(g0 * k), int(b0 * k))

def pulse_sine(color, seconds=PULSE_SECONDS, steps=PULSE_STEPS):
    """Pulse whole ring without audio."""
    dt = seconds / steps
    for i in range(steps + 1):
        pixels.fill(pulse_sine_step(color, i, steps))
        pixels.show()
        time.sleep(dt)

def pulse_green_while_playing_success_sound():
    """
    Start success sound and keep pulsing green while audio is playing.
    Pulse continues until the WAV is done.
    """
    sound = random.choice(SUCCESS_SOUNDS)
    path = f"{WAV_DIR}/{sound}.wav"
    print("SUCCESS: playing while pulsing:", path)

    with open(path, "rb") as f:
        wave = WaveFile(f)
        audio.play(wave)

        pulse_sine(SUCCESS_COLOR, seconds=3)

# -----------------------------
# Main loop
# -----------------------------
while True:
    # Idle: off + heartbeat
    while not sig.value:
        idle.animate()
        idle_heartbeat_if_due()
        time.sleep(0.01)

    # Debounce
    time.sleep(0.02)

    print("RFID triggered. Simulating HTTPS call...")
    #ok = simulated_https_call()
    ok = ha_webhook_call()

    if ok:
        print("Webhook result: SUCCESS")
        # Success: pulse green and play sound simultaneously
        pulse_green_while_playing_success_sound()
    else:
        print("Webhook result: FAIL")
        # Fail: pulse red only, no sound afterwards
        pulse_sine(FAIL_COLOR, seconds=3)

    # Wait for SIG to return low (prevents retriggers if tag stays present)
    while sig.value:
        idle.animate()
        time.sleep(0.01)

    # Reset idle heartbeat timer so it doesn't immediately blink again
    last_heartbeat = time.monotonic()
