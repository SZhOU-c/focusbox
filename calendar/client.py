import datetime as dt
import os
import zoneinfo

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
TZ = zoneinfo.ZoneInfo(os.getenv("TZ", "America/Chicago"))


def get_service():
    """
    Return an authenticated Google Calendar service client.

    First run:
      - Uses credentials.json (downloaded from Google Cloud)
      - Prompts you in the terminal to visit a URL and paste a code
      - Saves token.json so you don't have to re-auth again
    """
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
        creds = flow.run_console()
        with open("token.json", "w") as f:
            f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def upcoming_tagged_events(service, tags=("FOCUS", "SLEEP"), lookahead_hours=24):
    """
    Return list of (title, start_dt, end_dt) for upcoming events whose titles
    contain any of the given tags.
    """
    now = dt.datetime.now(tz=TZ)
    later = now + dt.timedelta(hours=lookahead_hours)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=now.isoformat(),
        timeMax=later.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = events_result.get("items", [])
    out = []
    for e in events:
        title = e.get("summary", "") or ""
        if not any(tag in title.upper() for tag in tags):
            continue

        # dateTime for timed events, date for all-day
        s = e["start"].get("dateTime") or e["start"]["date"]
        e_ = e["end"].get("dateTime") or e["end"]["date"]
        start = dt.datetime.fromisoformat(s).astimezone(TZ)
        end = dt.datetime.fromisoformat(e_).astimezone(TZ)
        out.append((title, start, end))

    return out
