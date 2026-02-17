import time
import re
import requests
import feedparser

class BBCOutsideTemp:
    """
    Fetches BBC Weather observation RSS and extracts temperature (°C).
    Uses the modern broker endpoint and caches results.
    """
    def __init__(self, location_id: str, refresh_seconds: int = 600):
        self.location_id = str(location_id)
        self.refresh_seconds = refresh_seconds
        self._last_fetch = 0.0
        self._last_temp_c = None

    def _feed_url(self) -> str:
        # Modern BBC endpoint (works with your example)
        return f"https://weather-broker-cdn.api.bbci.co.uk/en/observation/rss/{self.location_id}"

    @staticmethod
    def _extract_temp_c(text: str):
        if not text:
            return None

        # Fix common mojibake: "Â°C" -> "°C"
        t = text.replace("Â", "")
        t = " ".join(t.split())

        # Prefer the explicit "Temperature: X°C" in description
        m = re.search(r"Temperature:\s*([+-]?\d+(?:\.\d+)?)\s*°\s*C", t, re.IGNORECASE)
        if m:
            return float(m.group(1))

        # Fallback: any "X°C" occurrence
        m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*°\s*C", t)
        if m:
            return float(m.group(1))

        return None

    def get_temp_c(self):
        now = time.time()
        if now - self._last_fetch < self.refresh_seconds:
            return self._last_temp_c

        headers = {"User-Agent": "Mozilla/5.0"}  # helps avoid odd CDN behaviour

        try:
            r = requests.get(self._feed_url(), timeout=8, headers=headers)
            r.raise_for_status()

            feed = feedparser.parse(r.content)  # bytes -> avoids encoding weirdness

            candidates = []
            if feed.entries:
                e0 = feed.entries[0]
                candidates += [
                    getattr(e0, "summary", ""),
                    getattr(e0, "description", ""),
                    getattr(e0, "title", "")
                ]
            candidates += [
                getattr(feed.feed, "description", ""),
                getattr(feed.feed, "title", "")
            ]

            temp = None
            for c in candidates:
                temp = self._extract_temp_c(c)
                if temp is not None:
                    break

            self._last_fetch = now
            if temp is not None:
                self._last_temp_c = temp

        except Exception:
            self._last_fetch = now  # keep last known value

        return self._last_temp_c
