import time
from typing import Optional, Tuple

try:
    from bme280_spi import BME280SPI
except Exception:
    BME280SPI = None  # allows app to run even if module missing


class BME280Sensor:
    """
    Robust BME280 reader over SPI (spidev0.0 / CE0 by default).
    Returns (temp_c, humidity_pct, pressure_mb).
    """

    def __init__(self, retry_seconds: int = 10, bus: int = 0, device: int = 0):
        self.retry_seconds = retry_seconds
        self.bus = bus
        self.device = device

        self._bme = None
        self._last_init_attempt = 0.0

    def _try_init(self) -> None:
        now = time.time()
        if self._bme is not None:
            return
        if now - self._last_init_attempt < self.retry_seconds:
            return

        self._last_init_attempt = now

        if BME280SPI is None:
            return

        try:
            self._bme = BME280SPI(bus=self.bus, device=self.device)
        except Exception:
            self._bme = None

    def read(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        self._try_init()
        if self._bme is None:
            return None, None, None

        try:
            r = self._bme.read()
            return r.temperature_c, r.humidity_pct, r.pressure_mb
        except Exception:
            # if the bus/sensor hiccups, drop and re-init later
            try:
                self._bme.close()
            except Exception:
                pass
            self._bme = None
            return None, None, None
