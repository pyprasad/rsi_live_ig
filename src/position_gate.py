import time
import threading


class PositionGate:
    """
    Tracks whether we have an open position to enforce 'one trade at a time' rule.

    Uses event-driven updates from Lightstreamer (real-time) + periodic API polling
    (every 5 minutes) as a safety fallback.
    """

    def __init__(self, broker, fallback_poll_sec=300.0):
        """
        Args:
            broker: IGBroker instance
            fallback_poll_sec: How often to poll API as fallback (default: 300s = 5 min)
        """
        self.broker = broker
        self.fallback_poll_sec = fallback_poll_sec
        self._has_open = False
        self._last_update_time = time.monotonic()
        self._lock = threading.Lock()

        # Fallback polling thread
        self._stop_polling = False
        self._poll_thread = None

    def start_fallback_polling(self):
        """Start background thread for periodic API polling (safety net)."""
        if self._poll_thread is not None:
            return  # Already started

        def _poll_loop():
            while not self._stop_polling:
                time.sleep(self.fallback_poll_sec)
                if self._stop_polling:
                    break
                self._refresh_from_api(source="fallback_poll")

        self._poll_thread = threading.Thread(target=_poll_loop, daemon=True)
        self._poll_thread.start()

    def stop_fallback_polling(self):
        """Stop background polling thread."""
        self._stop_polling = True
        if self._poll_thread:
            self._poll_thread.join(timeout=2.0)

    def _refresh_from_api(self, source="manual"):
        """Query IG API for actual position state (used as fallback/verification)."""
        try:
            positions = self.broker.open_positions()
            # Filter for actually OPEN positions (not closed/pending)
            open_positions = [
                p for p in positions
                if p.get("position", {}).get("dealId")  # Has a deal ID
            ]

            with self._lock:
                old_state = self._has_open
                self._has_open = len(open_positions) > 0
                self._last_update_time = time.monotonic()

            if old_state != self._has_open:
                status = "OPEN" if self._has_open else "CLOSED"
                print(f"🔄 PositionGate [{source}]: State changed to {status} ({len(open_positions)} positions)")

        except Exception as e:
            print(f"⚠️ PositionGate API refresh failed [{source}]: {e}")
            # Be conservative on errors - assume we have a position
            with self._lock:
                self._has_open = True

    def check_startup_state(self):
        """
        Check initial state on startup (one-time API call).
        Returns True if open positions exist.
        """
        self._refresh_from_api(source="startup")
        return self._has_open

    def on_position_event(self, event_type, deal_id=None):
        """
        Called by Lightstreamer when position events occur.

        Args:
            event_type: "OPENED" or "CLOSED"
            deal_id: Optional deal reference for logging
        """
        with self._lock:
            old_state = self._has_open

            if event_type == "OPENED":
                self._has_open = True
            elif event_type == "CLOSED":
                self._has_open = False

            self._last_update_time = time.monotonic()

        if old_state != self._has_open:
            status = "OPEN" if self._has_open else "CLOSED"
            deal_str = f" (deal={deal_id})" if deal_id else ""
            print(f"📡 PositionGate [lightstreamer]: {event_type} → {status}{deal_str}")

    def check_staleness(self, max_age_sec=600.0):
        """
        Check if we haven't received updates for too long (potential LS failure).
        If stale, refresh from API.

        Args:
            max_age_sec: Max seconds without update before considering stale (default: 10 min)
        """
        with self._lock:
            age = time.monotonic() - self._last_update_time

        if age > max_age_sec:
            print(f"⏰ PositionGate: No updates for {age:.0f}s (stale threshold: {max_age_sec}s) - refreshing from API")
            self._refresh_from_api(source="staleness_check")

    def has_open(self):
        """Returns True if we currently have an open position."""
        # Check for staleness periodically
        self.check_staleness(max_age_sec=600.0)  # 10 minutes

        with self._lock:
            return self._has_open

    # Legacy methods (for backward compatibility and manual control)
    def mark_open(self):
        """Manually mark position as open (called after successful trade placement)."""
        self.on_position_event("OPENED", deal_id="manual")

    def mark_closed(self):
        """Manually mark position as closed."""
        self.on_position_event("CLOSED", deal_id="manual")
