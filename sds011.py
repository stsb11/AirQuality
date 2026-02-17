import serial

class SDS011:
    def __init__(self, port: str, baudrate: int = 9600, timeout: float = 2.0):
        self.ser = serial.Serial(port, baudrate=baudrate, timeout=timeout)

    def read(self):
        """
        Returns (pm25, pm10) floats in µg/m³, or None if no valid frame.
        Frame: AA C0 PM25_L PM25_H PM10_L PM10_H ID1 ID2 CHK AB
        """
        data = self.ser.read(10)
        if len(data) != 10:
            return None
        if data[0] != 0xAA or data[1] != 0xC0 or data[9] != 0xAB:
            return None

        pm25 = (data[2] + data[3] * 256) / 10.0
        pm10 = (data[4] + data[5] * 256) / 10.0

        chk = (sum(data[2:8]) % 256)
        if chk != data[8]:
            return None

        return (pm25, pm10)

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass
