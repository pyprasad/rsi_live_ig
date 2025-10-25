import time

class PositionGate:
    def __init__(self, broker, refresh_sec=5.0):
        self.broker = broker
        self.refresh_sec = refresh_sec
        self._has_open = False
        self._next_refresh = 0.0

    def refresh_if_due(self):
        now = time.time()
        if now >= self._next_refresh:
            try:
                pos = self.broker.open_positions()
                self._has_open = len(pos) > 0
            except Exception:
                self._has_open = True  # be conservative
            self._next_refresh = now + self.refresh_sec

    def has_open(self):
        self.refresh_if_due()
        return self._has_open

    def mark_open(self): self._has_open = True
    def mark_closed(self): self._has_open = False
