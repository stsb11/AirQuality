#!/usr/bin/env python3

# Hardware: Nova SDS011 PM Sensor w. USB adaptor, Pi "Official" display screen, BME280 Temp/Humid/Pressure sensor
# BME wired for SPI. Can't use I2c as both the display and the sensor have pullups that can't be disabled easily.
# BME280 wiring...
# VIN → 3.3V
# GND → GND
# SCK → GPIO11 (pin 23)
# SDA → GPIO10 (pin 19)
# SDO → GPIO9 (pin 21)
# CSB → GPIO8 (pin 24)

# sudo raspi-config -> Interfaces -> SPI (enable)

# mkdir air_display
# cd air_display
# python3 -m venv venv
# source venv/bin/activate
# install libraries
# pip install pygame pyserial requests feedparser
# sudo apt install -y python3-spidev

# Make sure we know where the SDS011 is mounted...
# sudo usermod -aG dialout pi
# ls -l /dev/serial/by-id/
# OUTPUT EXAMPLE: lrwxrwxrwx 1 root root 13 Feb 14 14:56 usb-1a86_USB_Serial-if00-port0 -> ../../ttyUSB0
# PATH: /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0

# Set BBC Weather location by finding the numeric code for your area in the URL of a BBC weather page.
# In display_app.py: BBC_LOCATION_ID = "PUT_ID_HERE"

# Turn the screen 180 degrees...
# sudo nano /boot/firmware/cmdline.txt
# Add to the end of the already very long line:
# video=DSI-1:800x480,rotate=180
# Save / reboot

# Start on boot
# mkdir -p ~/.config/systemd/user
# emacs ~/.config/systemd/user/air_display.service

"""
[Unit]
Description=Air Quality Display (pygame dashboard)
After=default.target network-online.target
Wants=network-online.target

[Service]
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/pi/.Xauthority
ExecStartPre=/bin/sleep 5
Type=simple
WorkingDirectory=/home/pi/air_display
ExecStart=/home/pi/air_display/venv/bin/python /home/pi/air_display/display_app.py
Restart=always
RestartSec=2

# If the app crashes, you want evidence:
StandardOutput=journal
StandardError=journal

# Optional niceties:
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""

# sudo loginctl enable-linger pi
# systemctl --user daemon-reload
# systemctl --user enable air_display.service
# systemctl --user start air_display.service
# reboot to test

# WHILE WORKING ON THE CODE, LOAD WITH...
# DISPLAY=:0 XAUTHORITY=/home/pi/.Xauthority python3 display_app.py
import time
import pygame
import math
from bbc_weather import BBCOutsideTemp
from sds011 import SDS011
from bme280_sensor import BME280Sensor

BBC_LOCATION_ID = "2643029"

# ---- Screen ----
WIDTH, HEIGHT = 800, 480
FPS = 10

BLACK = (0, 0, 0)
WHITE = (245, 245, 245)

SDS_PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
UGM3 = "µg/m³"  # proper µ and superscript 3

def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x

def lerp(a, b, t):
    return a + (b - a) * t

def lerp_rgb(c1, c2, t):
    return (
        int(lerp(c1[0], c2[0], t)),
        int(lerp(c1[1], c2[1], t)),
        int(lerp(c1[2], c2[2], t)),
    )

def quality_colour(value: float, kind: str):
    dark_green = (0, 90, 0)
    light_green = (120, 220, 120)
    amber = (255, 170, 0)
    red = (220, 40, 40)
    dark_red = (120, 0, 0)

    if kind == "pm25":
        b0, b1, b2, b3, b4, b5 = 0, 10, 20, 35, 50, 100
    else:
        b0, b1, b2, b3, b4, b5 = 0, 20, 35, 50, 100, 200

    v = clamp(value, float(b0), float(b5))

    if v <= b1:
        return lerp_rgb(dark_green, light_green, (v - b0) / (b1 - b0))
    if v <= b2:
        return lerp_rgb(light_green, amber, (v - b1) / (b2 - b1))
    if v <= b3:
        return lerp_rgb(amber, red, (v - b2) / (b3 - b2))
    if v <= b4:
        return lerp_rgb(red, dark_red, (v - b3) / (b4 - b3))
    return dark_red

def quality_label(value: float, kind: str):
    if kind == "pm25":
        if value <= 10: return "Excellent"
        if value <= 20: return "Good"
        if value <= 35: return "Fair"
        if value <= 50: return "Poor"
        if value <= 100: return "Very Poor"
        if value <= 225: return "Bad"
        return "Really Bad"
    else:
        if value <= 20: return "Excellent"
        if value <= 40: return "Good"
        if value <= 50: return "Fair"
        if value <= 100: return "Poor"
        if value <= 150: return "Very Poor"
        if value <= 300: return "Bad"
        return "Really Bad"

def render_aq_block(screen, label_font, value_font, status_font, x, y, label, value, kind):
    lbl = label_font.render(label, True, WHITE)
    screen.blit(lbl, (x, y))

    if value is None:
        val_text = f"-- {UGM3}"
        colour = WHITE
        status = "--"
    else:
        colour = quality_colour(value, kind)
        val_text = f"{value:.0f}{UGM3}" if value >= 10 else f"{value:.1f}{UGM3}"
        status = quality_label(value, kind)

    val = value_font.render(val_text, True, colour)
    screen.blit(val, (x, y + 30))

    st = status_font.render(status, True, colour)
    screen.blit(st, (x, y + 100))

def temp_to_colour(temp_c: float):
    deep_blue = (30, 120, 255)
    green = (80, 220, 80)
    red = (255, 80, 80)

    if temp_c is None:
        return WHITE

    t = temp_c
    if t <= -5:
        return deep_blue
    if t < 18:
        return lerp_rgb(deep_blue, green, (t + 5) / 23.0)
    if t <= 22:
        return green
    if t < 30:
        return lerp_rgb(green, red, (t - 22) / 8.0)
    return red

# For air pressure analysis...
SUBTLE = (180, 180, 180)  # soft grey for subtle insights
PRESSURE_HISTORY_SECONDS = 30 * 60   # 30 minutes
PRESSURE_SAMPLE_MIN_GAP = 20         # don't store more often than every 20s

def pressure_trend_text(history):
    """
    history: list of (timestamp, pressure_mb)
    Returns (text, colour) where colour is subtle grey.
    """
    if len(history) < 6:
        return ("Trend: --", SUBTLE)

    # Simple slope (mb per hour) using endpoints to keep it cheap
    t0, p0 = history[0]
    t1, p1 = history[-1]
    dt = t1 - t0
    if dt < 60:
        return ("Trend: --", SUBTLE)

    slope_mbps = (p1 - p0) / dt
    slope_mbph = slope_mbps * 3600.0

    # Categorise
    abs_s = abs(slope_mbph)
    if abs_s < 0.5:
        return ("Steady – Settled", SUBTLE)

    rising = slope_mbph > 0
    if abs_s < 2.0:
        return (("Rising slowly – Improving" if rising else "Falling slowly – Changeable"), SUBTLE)

    # Proper movement
    return (("Rising – Fair weather likely" if rising else "Falling – Rain likely"), SUBTLE)

# Feedback on humidity levels.
def dew_point_c(temp_c, humidity_pct):
    a = 17.62
    b = 243.12
    gamma = (a * temp_c) / (b + temp_c) + math.log(humidity_pct / 100.0)
    return (b * gamma) / (a - gamma)

def comfort_text(temp_c, humidity_pct):
    if temp_c is None or humidity_pct is None:
        return "Comfort: --"

    dp = dew_point_c(temp_c, humidity_pct)

    if dp < 5:
        return "Crisp – Dry air"
    if dp < 10:
        return "Fresh – Comfortable"
    if dp < 15:
        return "Comfortable"
    if dp < 18:
        return "Slightly humid"
    if dp < 21:
        return "Muggy"
    return "Oppressive"


def main():
    pygame.init()
    pygame.mouse.set_visible(False)

    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)
    clock = pygame.time.Clock()

    # Fonts (created once, not every frame)
    aq_label_font = pygame.font.SysFont("DejaVu Sans", 28)
    aq_value_font = pygame.font.SysFont("DejaVu Sans", 60)
    aq_status_font = pygame.font.SysFont("DejaVu Sans", 54)

    temp_title_font = pygame.font.SysFont("DejaVu Sans", 34)
    temp_value_font = pygame.font.SysFont("DejaVu Sans", 64)

    env_label_font = pygame.font.SysFont("DejaVu Sans", 34)
    env_value_font = pygame.font.SysFont("DejaVu Sans", 60)

    time_font = pygame.font.SysFont("DejaVu Sans", 64)

    pressure_hint_font = pygame.font.SysFont("DejaVu Sans", 22)

    sds = SDS011(SDS_PORT)
    pm25 = None
    pm10 = None
    last_sds_read = 0.0

    bbc = BBCOutsideTemp(BBC_LOCATION_ID, refresh_seconds=60)
    outside_temp = None

    bme = BME280Sensor(retry_seconds=10)
    inside_temp = None
    humidity = None
    pressure_mb = None
    last_env_read = 0.0

    pressure_history = []  # list of (timestamp, pressure_mb)
    last_pressure_store = 0.0

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        now = time.time()

        # SDS011 ~1Hz
        if now - last_sds_read >= 1.0:
            reading = sds.read()
            if reading:
                pm25, pm10 = reading
            last_sds_read = now

        # BBC cached in module
        outside_temp = bbc.get_temp_c()

        # BME280 ~1Hz (plenty). Keep last good values.
        if now - last_env_read >= 1.0:
            t, h, p = bme.read()
            if t is not None:
                inside_temp = t
            if h is not None:
                humidity = h
            if p is not None:
                pressure_mb = p
            last_env_read = now

            # store pressure history for trend (keep it lightweight)
            if pressure_mb is not None and (now - last_pressure_store) >= PRESSURE_SAMPLE_MIN_GAP:
                pressure_history.append((now, pressure_mb))
                last_pressure_store = now

                # drop old samples
                cutoff = now - PRESSURE_HISTORY_SECONDS
                while pressure_history and pressure_history[0][0] < cutoff:
                    pressure_history.pop(0)

        screen.fill(BLACK)

        # ---- Left column: Air Quality blocks ----
        render_aq_block(
            screen, aq_label_font, aq_value_font, aq_status_font,
            x=40, y=20,
            label="Air Quality: PM2.5",
            value=pm25,
            kind="pm25"
        )

        render_aq_block(
            screen, aq_label_font, aq_value_font, aq_status_font,
            x=40, y=210,
            label="Air Quality: PM10",
            value=pm10,
            kind="pm10"
        )

        # ---- Top-right: Temperature title ----
        title = temp_title_font.render("Temperature", True, WHITE)
        title_rect = title.get_rect(topright=(WIDTH - 120, 20))
        screen.blit(title, title_rect)

        # Outside: label white, value coloured
        if outside_temp is None:
            out_val_text = "--.-C"
            out_colour = WHITE
        else:
            out_val_text = f"{outside_temp:.1f}C"
            out_colour = temp_to_colour(outside_temp)

        outside_label = temp_value_font.render("Outside:", True, WHITE)
        outside_label_rect = outside_label.get_rect(topright=(WIDTH - 200, 60))
        screen.blit(outside_label, outside_label_rect)

        out_val = temp_value_font.render(f" {out_val_text}", True, out_colour)
        out_val_rect = out_val.get_rect(topleft=(outside_label_rect.right, outside_label_rect.top))
        screen.blit(out_val, out_val_rect)

        # Inside: label white, value coloured (always rendered)
        if inside_temp is None:
            in_val_text = "--.-C"
            in_colour = WHITE
        else:
            in_val_text = f"{inside_temp:.1f}C"
            in_colour = temp_to_colour(inside_temp)

        inside_label = temp_value_font.render("Inside:", True, WHITE)
        inside_label_rect = inside_label.get_rect(topright=(WIDTH - 200, 140))
        screen.blit(inside_label, inside_label_rect)

        in_val = temp_value_font.render(f" {in_val_text}", True, in_colour)
        in_val_rect = in_val.get_rect(topleft=(inside_label_rect.right, inside_label_rect.top))
        screen.blit(in_val, in_val_rect)

        # ---- Bottom-right: Pressure (left) and Humidity (right) ----
        # Layout based on your photo: there's space to shift humidity right and slot pressure left.
        bottom_block_top = 235

        # Pressure (left of humidity)
        pres_label = env_label_font.render("Pressure", True, WHITE)
        pres_label_rect = pres_label.get_rect(topright=(WIDTH - 230, bottom_block_top))
        screen.blit(pres_label, pres_label_rect)

        if pressure_mb is None:
            pres_text = "----hPa"
        else:
            pres_text = f"{pressure_mb:.0f}hPa"

        pres_val = env_value_font.render(pres_text, True, WHITE)
        pres_val_rect = pres_val.get_rect(topright=(WIDTH - 230, bottom_block_top + 35))
        screen.blit(pres_val, pres_val_rect)

        # Then show comment about trend...
        trend_text, trend_colour = pressure_trend_text(pressure_history)
        trend_surf = pressure_hint_font.render(trend_text, True, trend_colour)
        trend_rect = trend_surf.get_rect(topright=(WIDTH - 230, bottom_block_top + 100))
        screen.blit(trend_surf, trend_rect)

        # Humidity (shifted right)
        hum_label = env_label_font.render("Humidity", True, WHITE)
        hum_label_rect = hum_label.get_rect(topright=(WIDTH - 10, bottom_block_top))
        screen.blit(hum_label, hum_label_rect)

        if humidity is None:
            hum_text = "--%"
        else:
            hum_text = f"{humidity:.0f}%"

        hum_val = env_value_font.render(hum_text, True, WHITE)
        hum_val_rect = hum_val.get_rect(topright=(WIDTH - 10, bottom_block_top + 35))
        screen.blit(hum_val, hum_val_rect)

        comfort = comfort_text(inside_temp, humidity)
        comfort_surf = pressure_hint_font.render(comfort, True, SUBTLE)
        comfort_rect = comfort_surf.get_rect(topright=(WIDTH - 10, bottom_block_top + 100))
        screen.blit(comfort_surf, comfort_rect)


        # ---- Time (bottom centre) ----
        timestamp = time.strftime("%d/%m/%Y - %H:%M:%S")
        t_surf = time_font.render(timestamp, True, WHITE)
        t_rect = t_surf.get_rect(midbottom=(WIDTH // 2, HEIGHT - 16))
        screen.blit(t_surf, t_rect)

        pygame.display.flip()
        clock.tick(FPS)

    sds.close()
    pygame.quit()

if __name__ == "__main__":
    main()
