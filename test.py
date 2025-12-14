from datetime import datetime, timedelta

from dateutil.tz import gettz

from focusbox.config import LOCAL_TZ
from focusbox.google_calendar import fetch_events, build_schedule


def print_raw_events(events):
    print("=== RAW EVENTS FROM GOOGLE CALENDAR ===")
    if not events:
        print("(no events found in this time range)")
        return

    for i, e in enumerate(events):
        summary = e.get("summary") or "<no title>"

        start_raw = e["start"].get("dateTime") or e["start"].get("date")
        end_raw = e["end"].get("dateTime") or e["end"].get("date")

        print(f"[{i:02d}] {summary}")
        print(f"      start: {start_raw}")
        print(f"      end  : {end_raw}")
    print()


def print_schedule(schedule):
    print("=== SCHEDULED BLOCKS (FOCUS / SLEEP) ===")
    if not schedule:
        print("(no FOCUS/SLEEP blocks detected)")
        return

    for blk in schedule:
        # blk.mode is a string "FOCUS"/"SLEEP" in our earlier design
        mode = blk.mode
        title = blk.title
        start = blk.start.strftime("%Y-%m-%d %H:%M")
        end = blk.end.strftime("%Y-%m-%d %H:%M")
        print(f"- [{mode}] {title}")
        print(f"      {start}  →  {end}")
    print()


def main():
    # Use local timezone from config
    tz = gettz(LOCAL_TZ)

    # Test for "today" (midnight → midnight+1day)
    now = datetime.now(tz=tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)

    print(f"Querying events between:\n  {start}\n  {end}\n")

    # 1) Fetch raw events
    events = fetch_events(start, end)
    print(f"Fetched {len(events)} raw events from Google Calendar.\n")

    # 2) Print raw events
    print_raw_events(events)

    # 3) Build Focus Box schedule (FOCUS/SLEEP blocks)
    schedule = build_schedule(events)
    print_schedule(schedule)


if __name__ == "__main__":
    main()