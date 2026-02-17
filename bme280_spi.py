import time
import spidev
from dataclasses import dataclass

# BME280 registers
REG_ID = 0xD0
REG_RESET = 0xE0
REG_CTRL_HUM = 0xF2
REG_STATUS = 0xF3
REG_CTRL_MEAS = 0xF4
REG_CONFIG = 0xF5
REG_PRESS_MSB = 0xF7  # starts burst: press[3] temp[3] hum[2]

@dataclass
class BME280Reading:
    temperature_c: float
    humidity_pct: float
    pressure_mb: float  # mb == hPa

class BME280SPI:
    def __init__(self, bus=0, device=0, max_hz=500_000):
        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = max_hz
        self.spi.mode = 0b00

        chip_id = self.read_u8(REG_ID)
        if chip_id != 0x60:
            raise RuntimeError(f"Not a BME280 (chip id {hex(chip_id)})")

        # Read calibration data
        self._read_calibration()

        # Configure sensor (oversampling + normal mode)
        # humidity oversampling x1
        self.write_u8(REG_CTRL_HUM, 0x01)
        # temp oversampling x1, pressure oversampling x1, normal mode
        self.write_u8(REG_CTRL_MEAS, 0x27)
        # standby 1000ms, filter off
        self.write_u8(REG_CONFIG, 0xA0)

        self.t_fine = 0

    # --- SPI low-level helpers ---
    def read_bytes(self, reg, length):
        # For BME280 SPI: bit7=1 means read
        reg |= 0x80
        resp = self.spi.xfer2([reg] + [0x00] * length)
        return resp[1:]  # first byte is dummy

    def write_u8(self, reg, val):
        # bit7=0 for write
        self.spi.xfer2([reg & 0x7F, val & 0xFF])

    def read_u8(self, reg):
        return self.read_bytes(reg, 1)[0]

    def read_u16_le(self, reg):
        b = self.read_bytes(reg, 2)
        return b[0] | (b[1] << 8)

    def read_s16_le(self, reg):
        v = self.read_u16_le(reg)
        return v - 65536 if v > 32767 else v

    def _read_calibration(self):
        # Temperature and pressure calibration (0x88..0xA1)
        self.dig_T1 = self.read_u16_le(0x88)
        self.dig_T2 = self.read_s16_le(0x8A)
        self.dig_T3 = self.read_s16_le(0x8C)

        self.dig_P1 = self.read_u16_le(0x8E)
        self.dig_P2 = self.read_s16_le(0x90)
        self.dig_P3 = self.read_s16_le(0x92)
        self.dig_P4 = self.read_s16_le(0x94)
        self.dig_P5 = self.read_s16_le(0x96)
        self.dig_P6 = self.read_s16_le(0x98)
        self.dig_P7 = self.read_s16_le(0x9A)
        self.dig_P8 = self.read_s16_le(0x9C)
        self.dig_P9 = self.read_s16_le(0x9E)

        self.dig_H1 = self.read_u8(0xA1)
        # Humidity calibration (0xE1..0xE7)
        self.dig_H2 = self.read_s16_le(0xE1)
        self.dig_H3 = self.read_u8(0xE3)
        e4 = self.read_u8(0xE4)
        e5 = self.read_u8(0xE5)
        e6 = self.read_u8(0xE6)
        self.dig_H4 = (e4 << 4) | (e5 & 0x0F)
        self.dig_H5 = (e6 << 4) | (e5 >> 4)
        self.dig_H6 = self.read_u8(0xE7)
        if self.dig_H6 > 127:
            self.dig_H6 -= 256

    # --- Compensation formulas (from Bosch datasheet) ---
    def _compensate_temperature(self, adc_T):
        var1 = (adc_T / 16384.0 - self.dig_T1 / 1024.0) * self.dig_T2
        var2 = ((adc_T / 131072.0 - self.dig_T1 / 8192.0) ** 2) * self.dig_T3
        self.t_fine = int(var1 + var2)
        return (var1 + var2) / 5120.0

    def _compensate_pressure(self, adc_P):
        var1 = self.t_fine / 2.0 - 64000.0
        var2 = var1 * var1 * self.dig_P6 / 32768.0
        var2 = var2 + var1 * self.dig_P5 * 2.0
        var2 = var2 / 4.0 + self.dig_P4 * 65536.0
        var1 = (self.dig_P3 * var1 * var1 / 524288.0 + self.dig_P2 * var1) / 524288.0
        var1 = (1.0 + var1 / 32768.0) * self.dig_P1
        if var1 == 0:
            return 0.0
        p = 1048576.0 - adc_P
        p = (p - var2 / 4096.0) * 6250.0 / var1
        var1 = self.dig_P9 * p * p / 2147483648.0
        var2 = p * self.dig_P8 / 32768.0
        p = p + (var1 + var2 + self.dig_P7) / 16.0
        # p is Pa; convert to hPa/mb
        return p / 100.0

    def _compensate_humidity(self, adc_H):
        h = self.t_fine - 76800.0
        if h == 0:
            return 0.0
        h = (adc_H - (self.dig_H4 * 64.0 + self.dig_H5 / 16384.0 * h)) * (
            self.dig_H2 / 65536.0 * (1.0 + self.dig_H6 / 67108864.0 * h * (1.0 + self.dig_H3 / 67108864.0 * h))
        )
        h = h * (1.0 - self.dig_H1 * h / 524288.0)
        return max(0.0, min(100.0, h))

    def read(self) -> BME280Reading:
        data = self.read_bytes(REG_PRESS_MSB, 8)

        adc_P = (data[0] << 12) | (data[1] << 4) | (data[2] >> 4)
        adc_T = (data[3] << 12) | (data[4] << 4) | (data[5] >> 4)
        adc_H = (data[6] << 8) | data[7]

        temp_c = self._compensate_temperature(adc_T)
        pressure_mb = self._compensate_pressure(adc_P)
        humidity_pct = self._compensate_humidity(adc_H)

        return BME280Reading(temp_c, humidity_pct, pressure_mb)

    def close(self):
        self.spi.close()
