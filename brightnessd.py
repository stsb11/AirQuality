#!/usr/bin/env python3
import time
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

from astral import LocationInfo
from astral.sun import sun

TZ = ZoneInfo("Europe/London")

# Market Deeping-ish
LAT = 52.67654
LON = -0.31629

# Backlight control
BRIGHTNESS_PATH = "/sys/class/backlight/10-0045/brightness"
BL_POWER_PATH   = "/sys/class/backlight/10-0045/bl_power"


# Your policy
OFF_START = (0, 30)   # 00:30
OFF_END   = (6, 0)    # 06:00

EVENING_TARGET = 0.50  # 50% after ramp
MORNING_START  = 0.20  # 20% at sunrise
RAMP_MINUTES   = 60

# Summer shortcut: if sunrise is before this, just go 100% immediately
SUMMER_EARLY_SUNRISE_CUTOFF = (5, 30)  # 05:30

def hhmm_today(h, m):
    now = datetime.now(TZ)
    return now.replace(hour=h, minute=m, second=0, microsecond=0)

def write_int(path, value):
    with open(path, "w") as f:
        f.write(str(int(value)))

def set_backlight(on: bool):
    # 0 = on, 1 = off (Pi backlight driver convention)
    write_int(BL_POWER_PATH, 0 if on else 1)

def set_brightness_pct(pct: float):
    pct = max(0.0, min(1.0, pct))
    # official backlight is typically 0..255
    value = round(pct * 255)
    write_int(BRIGHTNESS_PATH, value)

def lerp(a, b, t):
    return a + (b - a) * t

def ramp(now, start, end, from_pct, to_pct):
    if now <= start:
        return from_pct
    if now >= end:
        return to_pct
    span = (end - start).total_seconds()
    t = (now - start).total_seconds() / span
    return lerp(from_pct, to_pct, t)

def main():
    loc = LocationInfo(name="Market Deeping", region="UK", timezone="Europe/London",
                       latitude=LAT, longitude=LON)

    last_day = None
    s_today = None

    while True:
        now = datetime.now(TZ)

        # Recompute sun times once per day
        if last_day != now.date():
            s_today = sun(loc.observer, date=now.date(), tzinfo=TZ)
            last_day = now.date()

        off_start = hhmm_today(*OFF_START)
        off_end = hhmm_today(*OFF_END)

        # Overnight off window
        if off_start <= now < off_end:
            set_backlight(False)
            time.sleep(20)
            continue

        # Otherwise: backlight on
        set_backlight(True)

        sunrise = s_today["sunrise"]
        sunset = s_today["sunset"]

        # Morning rule
        early_cutoff = hhmm_today(*SUMMER_EARLY_SUNRISE_CUTOFF)
        if sunrise <= early_cutoff:
            # summer: don't bother with gentle dawn theatrics
            morning_from = 1.0
        else:
            morning_from = MORNING_START

        morning_start = sunrise
        morning_end = sunrise + timedelta(minutes=RAMP_MINUTES)

        evening_start = sunset
        evening_end = sunset + timedelta(minutes=RAMP_MINUTES)

        # Decide brightness
        if now < morning_start:
            # before sunrise: low but visible
            pct = morning_from
        elif morning_start <= now <= morning_end:
            pct = ramp(now, morning_start, morning_end, morning_from, 1.0)
        elif morning_end < now < evening_start:
            pct = 1.0
        elif evening_start <= now <= evening_end:
            pct = ramp(now, evening_start, evening_end, 1.0, EVENING_TARGET)
        else:
            # after evening ramp: hold at 50% until off window
            pct = EVENING_TARGET

        #print("Setting to " + str(pct*100) + "%")
        set_brightness_pct(pct)
        time.sleep(20)

if __name__ == "__main__":
    main()
