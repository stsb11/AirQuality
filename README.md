# AirQuality
A Pi-based air quality monitor


Hardware: Nova SDS011 PM Sensor w. USB adaptor, Pi "Official" display screen, BME280 Temp/Humid/Pressure sensor
BME wired for SPI. Can't use I2c as both the display and the sensor have pullups that can't be disabled easily.
BME280 wiring...
VIN → 3.3V
GND → GND
SCK → GPIO11 (pin 23)
SDA → GPIO10 (pin 19)
SDO → GPIO9 (pin 21)
CSB → GPIO8 (pin 24)

sudo raspi-config -> Interfaces -> SPI (enable)

mkdir air_display
cd air_display
python3 -m venv venv
source venv/bin/activate
install libraries
pip install pygame pyserial requests feedparser
sudo apt install -y python3-spidev

Make sure we know where the SDS011 is mounted...
sudo usermod -aG dialout pi
ls -l /dev/serial/by-id/
OUTPUT EXAMPLE: lrwxrwxrwx 1 root root 13 Feb 14 14:56 usb-1a86_USB_Serial-if00-port0 -> ../../ttyUSB0
PATH: /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0

Set BBC Weather location by finding the numeric code for your area in the URL of a BBC weather page.
In display_app.py: BBC_LOCATION_ID = "PUT_ID_HERE"

Turn the screen 180 degrees...
sudo nano /boot/firmware/cmdline.txt
Add to the end of the already very long line:
video=DSI-1:800x480,rotate=180
Save / reboot

Start on boot
mkdir -p ~/.config/systemd/user
emacs ~/.config/systemd/user/air_display.service
