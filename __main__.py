# focusbox/__main__.py

from datetime import datetime, timedelta
import time

from dateutil.tz import gettz

from .config import CALENDAR_REFRESH_INTERVAL, LOCAL_TZ
from .google_calendar import fetch_events, build_schedule
from .scheduler import FocusBoxStateMachine
from .box import BoxHardware


def main():
    local_tz = gettz(LOCAL_TZ)

    # Hardware interface (motors + sensors via robot_hat)
    box = BoxHardware()

    # State machine (uses robot_hat Music internally)
    fsm = FocusBoxStateMachine(box=box)

    schedule = []
    last_fetch = datetime.min.replace(tzinfo=local_tz)

    print("[Main] Focus Box started. Press Ctrl+C to exit.")

    try:
        while True:
            now = datetime.now(tz=local_tz)

            # Periodically refresh today's calendar schedule
            if now - last_fetch > CALENDAR_REFRESH_INTERVAL:
                start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                end = start + timedelta(days=1)

                events = fetch_events(start, end)
                schedule = build_schedule(events)
                last_fetch = now

            # Update state machine (handles phone placement + lock + sounds)
            fsm.update(now, schedule)

            # Run more frequently for responsiveness.
            # Phone detection polling rate is controlled inside scheduler.py (phone_poll_period_s).
            time.sleep(0.2)

    except KeyboardInterrupt:
        print("\n[Main] Exiting...")
        # optional: ensure unlocked on exit
        try:
            box.unlock()
        except Exception:
            pass


if __name__ == "__main__":
    main()
