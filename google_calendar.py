# focusbox/google_calendar.py

from __future__ import annotations
from typing import List, Tuple
from datetime import datetime, timezone

import os.path

from dateutil.parser import isoparse
from dateutil.tz import gettz

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .config import (
    GOOGLE_SCOPES,
    GOOGLE_TOKEN_FILE,
    GOOGLE_CREDENTIALS_FILE,
    FOCUS_KEYWORD,
    SLEEP_KEYWORD,
    LOCAL_TZ,
)

# --------- A. 获取/刷新 Credentials --------- #

def get_credentials() -> Credentials:
    creds = None
    if os.path.exists(GOOGLE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, GOOGLE_SCOPES)
    # 没有 token 或 token 失效，就重新走 OAuth
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("[Google] Refreshing access token...")
            creds.refresh(Request())
        else:
            print("[Google] Running OAuth flow...")
            flow = InstalledAppFlow.from_client_secrets_file(
                GOOGLE_CREDENTIALS_FILE, GOOGLE_SCOPES
            )
            creds = flow.run_local_server(port=0)
        # 保存 token
        with open(GOOGLE_TOKEN_FILE, "w") as token:
            token.write(creds.to_json())
            print(f"[Google] Saved token to {GOOGLE_TOKEN_FILE}")
    return creds


# --------- B. 从 Google Calendar 获取事件 --------- #

def fetch_events(time_min: datetime, time_max: datetime):
    """
    在 [time_min, time_max) 区间内获取事件。
    time_min/time_max 必须是 aware datetime（含时区）。
    """
    creds = get_credentials()
    service = build("calendar", "v3", credentials=creds)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=time_min.isoformat(),
        timeMax=time_max.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    items = events_result.get("items", [])
    print(f"[Google] Fetched {len(items)} events.")
    return items


# --------- C. 解析事件 → 内部 schedule 结构 --------- #

class ScheduledBlock:
    """
    内部统一表示一个锁定区间（FOCUS 或 SLEEP）。
    """

    def __init__(self, mode: str, title: str,
                 start: datetime, end: datetime):
        self.mode = mode        # "FOCUS" / "SLEEP"
        self.title = title
        self.start = start      # aware datetime
        self.end = end

    def __repr__(self):
        return (f"<ScheduledBlock {self.mode} {self.title} "
                f"{self.start.isoformat()} → {self.end.isoformat()}>")

def build_schedule(events) -> List[ScheduledBlock]:
    """
    将 Google 事件转成我们自己的 schedule。
    匹配规则：summary 里包含 FOCUS 或 SLEEP（大小写不敏感）。
    """
    schedule: List[ScheduledBlock] = []
    local_tz = gettz(LOCAL_TZ)

    for e in events:
        summary = (e.get("summary") or "").strip()
        summary_upper = summary.upper()

        start_raw = e["start"].get("dateTime") or e["start"].get("date")
        end_raw = e["end"].get("dateTime") or e["end"].get("date")

        if not start_raw or not end_raw:
            continue

        start = isoparse(start_raw)
        end = isoparse(end_raw)

        # 统一转到本地时区
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        start = start.astimezone(local_tz)
        end = end.astimezone(local_tz)

        mode = None
        if FOCUS_KEYWORD in summary_upper:
            mode = "FOCUS"
        elif SLEEP_KEYWORD in summary_upper:
            mode = "SLEEP"

        if mode is None:
            continue

        block = ScheduledBlock(mode=mode, title=summary, start=start, end=end)
        schedule.append(block)

    print(f"[Schedule] Built {len(schedule)} blocks from events.")
    return schedule
