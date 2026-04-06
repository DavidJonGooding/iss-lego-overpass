#!/usr/bin/env python3
"""
ISS Pass Tracker
================
Polls the Open-Notify API for upcoming ISS passes and drives:
  - Red LED    (GPIO17) : no pass within the next hour
  - Amber LED  (GPIO27) : pass coming within 60 minutes
  - Green LED  (GPIO22) : ISS overhead right now
  - Buzzer     (GPIO18) : single beep on IDLE -> UPCOMING transition
  - OLED 128x32 (I2C)  : next pass info / overhead status

Designed for Raspberry Pi 3B with Raspberry Pi OS Lite.
Run inside the iss-tracker venv:
    source ~/iss-tracker/venv/bin/activate
    python3 iss_tracker.py
"""

import time
import datetime
import logging
import requests
import RPi.GPIO as GPIO
from skyfield.api import load, wgs84, EarthSatellite

# ── Attempt OLED import (graceful degradation if not yet wired) ──────────────
try:
    from luma.core.interface.serial import i2c
    from luma.oled.device import ssd1306
    from luma.core.render import canvas
    from PIL import ImageFont
    OLED_AVAILABLE = True
except ImportError:
    OLED_AVAILABLE = False

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
LAT = 51.76          # Hatfield, Hertfordshire
LON = -0.23
ALTITUDE_M = 55      # metres above sea level (approximate)

UPCOMING_WINDOW_S = 3600   # amber threshold: 60 minutes
POLL_INTERVAL_S   = 3600   # recalculate passes once per hour (TLE refresh)
MIN_ELEVATION_DEG = 20     # ignore passes below this max elevation

# GPIO pins (BCM numbering)
PIN_RED   = 17
PIN_AMBER = 27
PIN_GREEN = 22
PIN_BUZZ  = 18

# ── GPIO setup ────────────────────────────────────────────────────────────────
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
for pin in (PIN_RED, PIN_AMBER, PIN_GREEN, PIN_BUZZ):
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.LOW)

buzzer_pwm = GPIO.PWM(PIN_BUZZ, 1000)   # 1 kHz tone

# ── OLED setup ────────────────────────────────────────────────────────────────
oled = None
if OLED_AVAILABLE:
    try:
        serial = i2c(port=1, address=0x3C)
        oled = ssd1306(serial, width=128, height=32)
        log.info("OLED initialised at 0x3C")
    except Exception as e:
        log.warning("OLED not found: %s", e)

# ── State machine ─────────────────────────────────────────────────────────────
STATE_IDLE     = "IDLE"
STATE_UPCOMING = "UPCOMING"
STATE_OVERHEAD = "OVERHEAD"


# ── Helpers ───────────────────────────────────────────────────────────────────
def set_leds(red=False, amber=False, green=False):
    GPIO.output(PIN_RED,   GPIO.HIGH if red   else GPIO.LOW)
    GPIO.output(PIN_AMBER, GPIO.HIGH if amber else GPIO.LOW)
    GPIO.output(PIN_GREEN, GPIO.HIGH if green else GPIO.LOW)


def beep(frequency=1000, duration=0.2):
    """Single short beep."""
    buzzer_pwm.ChangeFrequency(frequency)
    buzzer_pwm.start(50)
    time.sleep(duration)
    buzzer_pwm.stop()


def fetch_tle():
    """
    Download the latest ISS TLE from CelesTrak.
    Returns an EarthSatellite object, or None on failure.
    TLE is cached to disk so the tracker works offline after first run.
    """
    TLE_URL   = "https://celestrak.org/SOCRATES/query.php?CODE=ISS&FORMAT=TLE"
    TLE_URL   = "https://celestrak.org/SATCAT/tle.php?CATNR=25544"
    CACHE_FILE = "/home/{}/iss-tracker/iss.tle".format(
        __import__('os').environ.get('USER', 'pi'))

    tle_lines = None

    # Try downloading fresh TLE
    try:
        resp = requests.get(
            "https://celestrak.org/SATCAT/tle.php?CATNR=25544",
            timeout=10)
        resp.raise_for_status()
        lines = [l.strip() for l in resp.text.strip().splitlines() if l.strip()]
        if len(lines) >= 3:
            tle_lines = lines[:3]
            # Cache to disk
            with open(CACHE_FILE, 'w') as f:
                f.write('\n'.join(tle_lines))
            log.info("TLE updated from CelesTrak")
    except Exception as e:
        log.warning("TLE download failed: %s", e)

    # Fall back to cached TLE
    if tle_lines is None:
        try:
            with open(CACHE_FILE) as f:
                tle_lines = [l.strip() for l in f.read().strip().splitlines()]
            log.info("Using cached TLE")
        except FileNotFoundError:
            log.error("No TLE available — no internet and no cache")
            return None

    ts = load.timescale()
    satellite = EarthSatellite(tle_lines[1], tle_lines[2], tle_lines[0], ts)
    return satellite, ts


def fetch_passes():
    """
    Calculate upcoming ISS passes locally using skyfield + CelesTrak TLE.
    Returns a list of dicts: {risetime, duration, max_elevation}
    Only includes passes above MIN_ELEVATION_DEG.
    Returns None on error.
    """
    result = fetch_tle()
    if result is None:
        return None
    satellite, ts = result

    observer = wgs84.latlon(LAT, LON, elevation_m=ALTITUDE_M)

    # Search window: now → now + 24 hours
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    t0 = ts.utc(now_utc.year, now_utc.month, now_utc.day,
                now_utc.hour, now_utc.minute, now_utc.second)
    t1 = ts.utc(now_utc.year, now_utc.month, now_utc.day,
                now_utc.hour + 48, now_utc.minute, now_utc.second)

    # Find all rise/set events (altitude crosses 0°)
    t, events = satellite.find_events(observer, t0, t1, altitude_degrees=0.0)

    passes = []
    rise_time = None

    for ti, event in zip(t, events):
        if event == 0:   # rise
            rise_time = ti
        elif event == 2 and rise_time is not None:   # set
            rise_unix = rise_time.utc_datetime().timestamp()
            set_unix  = ti.utc_datetime().timestamp()
            duration  = set_unix - rise_unix

            # Sample elevation at midpoint for max estimate
            mid_unix = rise_unix + duration / 2
            mid_dt   = datetime.datetime.fromtimestamp(mid_unix, datetime.timezone.utc)
            t_mid    = ts.utc(mid_dt.year, mid_dt.month, mid_dt.day,
                              mid_dt.hour, mid_dt.minute, mid_dt.second)
            difference = satellite - observer
            topocentric = difference.at(t_mid)
            alt, _, _ = topocentric.altaz()
            max_el = alt.degrees

            if max_el >= MIN_ELEVATION_DEG:
                passes.append({
                    "risetime":      rise_unix,
                    "duration":      duration,
                    "max_elevation": max_el,
                })
            rise_time = None

    passes.sort(key=lambda p: p["risetime"])
    log.info("Calculated %d qualifying passes in next 48h", len(passes))
    return passes


def next_good_pass(passes):
    """Return the next pass that hasn't ended yet, or None."""
    now = time.time()
    for p in passes:
        if p["risetime"] + p["duration"] > now:
            return p
    return None


def format_time(unix_ts):
    """Format a Unix timestamp as HH:MM local time."""
    return datetime.datetime.fromtimestamp(unix_ts).strftime("%H:%M")


def format_duration(seconds):
    """Format seconds as m:ss."""
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s:02d}s"


def update_oled(state, next_pass=None):
    """Refresh the OLED display."""
    if not oled:
        return

    with canvas(oled) as draw:
        if state == STATE_OVERHEAD and next_pass:
            end_time = next_pass["risetime"] + next_pass["duration"]
            remaining = max(0, int(end_time - time.time()))
            draw.text((0,  0), "** ISS OVERHEAD **", fill="white")
            draw.text((0, 16), f"Ends in: {format_duration(remaining)}", fill="white")

        elif state == STATE_UPCOMING and next_pass:
            secs_away = int(next_pass["risetime"] - time.time())
            mins_away = secs_away // 60
            el = next_pass["max_elevation"]
            dur = format_duration(next_pass["duration"])
            draw.text((0,  0), f"Pass at {format_time(next_pass['risetime'])}"
                               f"  ({mins_away}m)", fill="white")
            draw.text((0, 16), f"Elev:{el:.0f}deg  Dur:{dur}", fill="white")

        else:
            # IDLE — show next pass time if known
            if next_pass:
                draw.text((0,  0), "ISS Tracker  [idle]", fill="white")
                draw.text((0, 16), f"Next: {format_time(next_pass['risetime'])}"
                                   f"  El:{next_pass['max_elevation']:.0f}deg",
                          fill="white")
            else:
                draw.text((0,  0), "ISS Tracker  [idle]", fill="white")
                draw.text((0, 16), "No passes found", fill="white")


def cleanup():
    log.info("Cleaning up GPIO")
    set_leds()
    buzzer_pwm.stop()
    GPIO.cleanup()
    if oled:
        oled.cleanup()


# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    log.info("ISS Tracker starting  (lat=%.2f, lon=%.2f)", LAT, LON)
    log.info("Upcoming window: %d min  |  Min elevation: %d deg",
             UPCOMING_WINDOW_S // 60, MIN_ELEVATION_DEG)

    passes        = []
    last_poll     = 0
    current_state = None   # force LED update on first iteration

    try:
        while True:
            now = time.time()

            # ── Refresh pass predictions ──────────────────────────────────────
            if now - last_poll >= POLL_INTERVAL_S:
                result = fetch_passes()
                if result is not None:
                    passes = result
                last_poll = now

            # ── Determine state ───────────────────────────────────────────────
            nxt = next_good_pass(passes)

            if nxt is None:
                new_state = STATE_IDLE

            elif nxt["risetime"] <= now <= nxt["risetime"] + nxt["duration"]:
                new_state = STATE_OVERHEAD

            elif nxt["risetime"] - now <= UPCOMING_WINDOW_S:
                new_state = STATE_UPCOMING

            else:
                new_state = STATE_IDLE

            # ── Act on state changes ──────────────────────────────────────────
            if new_state != current_state:
                log.info("State: %s → %s", current_state, new_state)

                if new_state == STATE_IDLE:
                    set_leds(red=True)
                elif new_state == STATE_UPCOMING:
                    set_leds(amber=True)
                    if current_state == STATE_IDLE:
                        beep(1000, 0.15)          # short alert beep
                        time.sleep(0.1)
                        beep(1200, 0.15)          # two-tone: distinctive
                elif new_state == STATE_OVERHEAD:
                    set_leds(green=True)
                    beep(1500, 0.3)               # longer beep for overhead

                current_state = new_state

            # ── Update display every loop iteration ───────────────────────────
            update_oled(current_state, nxt)

            # ── Log current status ────────────────────────────────────────────
            if nxt:
                secs = int(nxt["risetime"] - now)
                log.debug(
                    "State=%s  Next pass in %ds at %s  El=%.0f  Dur=%s",
                    current_state, secs,
                    format_time(nxt["risetime"]),
                    nxt["max_elevation"],
                    format_duration(nxt["duration"]),
                )

            time.sleep(10)   # check state every 10 seconds

    except KeyboardInterrupt:
        log.info("Interrupted by user")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
