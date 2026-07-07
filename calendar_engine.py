"""
calendar_engine.py
==================
Builds an authenticated Google Calendar v3 service, sharing the same
OAuth credentials, token file, and scopes as gmail_fetch.py.

Also provides parse_meeting_request() to extract structured meeting
details from an email thread using Gemini (gemini-2.5-flash).
"""

import json
import os
import re
import socket
from datetime import date

import google.generativeai as genai
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

load_dotenv()

# ── IPv4 monkey-patch ──────────────────────────────────────────────────────
# Forces the Google API client to connect over IPv4, avoiding hangs on
# networks where IPv6 is advertised but not fully functional.
_orig_getaddrinfo = socket.getaddrinfo

def _getaddrinfo_ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

socket.getaddrinfo = _getaddrinfo_ipv4_only
# ──────────────────────────────────────────────────────────────────────────

# Shared with gmail_fetch.py — same credentials, token, and scope set.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
]

CREDENTIALS_FILE = (
    r"C:\Users\diksh\chief_of_staff\servers"
    r"\client_secret_98708590862-eg0cc2ktd0ojud37j7f2c5kn04mun4ua"
    r".apps.googleusercontent.com.json"
)
TOKEN_FILE = r"C:\Users\diksh\chief_of_staff\token.json"


def _build_calendar_service():
    """
    Authenticate with OAuth 2.0 and return a Google Calendar v3 service object.

    Uses the same credentials file, token file, and scopes as gmail_fetch.py
    so a single token covers both Gmail and Calendar without re-prompting.
    """
    creds = None

    # Load cached token if it exists
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # Refresh or run the OAuth flow if credentials are missing / expired
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        # Persist the token for subsequent runs
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


# ── Gemini setup ───────────────────────────────────────────────────────────
_GEMINI_MODEL = "gemini-2.5-flash"

_SYSTEM_INSTRUCTION = (
    "You are a scheduling assistant. "
    "Extract meeting details from the email thread the user provides and return "
    "ONLY a valid JSON object — no markdown, no code fences, no commentary. "
    "The JSON must have exactly these keys:\n"
    "  proposed_times   — list of ISO-8601 datetime strings (e.g. '2026-07-04T14:00:00')\n"
    "  attendees        — list of email addresses found in the thread\n"
    "  topic            — one-line plain-text summary of the meeting purpose\n"
    "  duration_minutes — integer number of minutes (default 30 if not stated)\n"
    "If a value cannot be determined, use an empty list [] or the default. "
    "Never include extra keys."
)


def parse_meeting_request(thread: dict) -> dict:
    """
    Use Gemini to extract structured meeting details from an email thread.

    Args:
        thread: Dict with keys ``subject`` (str) and ``messages``
                (list of dicts with ``from``, ``date``, ``body``).

    Returns:
        A dict with keys:
            proposed_times   (list[str])  — ISO-8601 datetime strings
            attendees        (list[str])  — email addresses
            topic            (str)        — one-line summary
            duration_minutes (int)        — default 30
        On any failure, returns {"parsing_error": "<reason>"} instead.
    """
    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return {"parsing_error": "GEMINI_API_KEY not set in environment"}

        genai.configure(api_key=api_key)

        # Build a readable transcript of the thread
        subject = thread.get("subject", "(No subject)")
        lines = [f"Subject: {subject}", ""]
        for msg in thread.get("messages", []):
            lines.append(f"From: {msg.get('from', 'Unknown')}")
            lines.append(f"Date: {msg.get('date', '')}")
            lines.append(f"{msg.get('body', '').strip()}")
            lines.append("")
        transcript = "\n".join(lines).strip()

        today = date.today().isoformat()
        prompt = (
            f"Today's date is {today}. "
            "Use this to resolve relative day names like 'tomorrow' or 'next Monday'.\n\n"
            f"{transcript}"
        )

        model = genai.GenerativeModel(
            _GEMINI_MODEL,
            system_instruction=_SYSTEM_INSTRUCTION,
        )
        response = model.generate_content(prompt)
        raw = response.text.strip()

        # Strip markdown code fences if Gemini wraps the JSON anyway
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        raw = raw.strip()

        parsed = json.loads(raw)

        # Normalise and fill defaults
        return {
            "proposed_times": list(parsed.get("proposed_times") or []),
            "attendees": list(parsed.get("attendees") or []),
            "topic": str(parsed.get("topic") or subject),
            "duration_minutes": int(parsed.get("duration_minutes") or 30),
        }

    except Exception as exc:
        return {"parsing_error": str(exc)}


def check_availability(time_min: str, time_max: str) -> bool:
    """
    Query the FreeBusy API for the user's primary calendar.

    Args:
        time_min: ISO-8601 start of the window (e.g. '2026-07-04T14:00:00').
        time_max: ISO-8601 end of the window.

    Returns:
        True if the slot is free, False if busy or if any error occurs.
    """
    try:
        # The FreeBusy API requires timezone info; append "Z" (UTC) when absent.
        if not time_min.endswith("Z") and "+" not in time_min and time_min[-6] != "+":
            time_min = time_min + "Z"
        if not time_max.endswith("Z") and "+" not in time_max and time_max[-6] != "+":
            time_max = time_max + "Z"

        service = _build_calendar_service()
        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": "primary"}],
        }
        result = service.freebusy().query(body=body).execute()
        busy_periods = result.get("calendars", {}).get("primary", {}).get("busy", [])
        return len(busy_periods) == 0

    except Exception:
        # Safe default: treat any error as busy to avoid double-booking.
        return False


def find_free_slot(
    proposed_times: list,
    duration_minutes: int = 30,
) -> str | None:
    """
    Return the first proposed time at which the calendar is free.

    Args:
        proposed_times:   List of ISO-8601 datetime strings to check.
        duration_minutes: Length of the meeting in minutes (default 30).

    Returns:
        The first free ISO-8601 start time string, or None if all are busy
        or the list is empty.
    """
    from datetime import datetime, timedelta, timezone

    for start_str in proposed_times:
        try:
            # Normalise: strip trailing "Z" so fromisoformat works on 3.10
            normalised = start_str.rstrip("Z")
            start_dt = datetime.fromisoformat(normalised).replace(tzinfo=timezone.utc)
            end_dt = start_dt + timedelta(minutes=duration_minutes)

            # Format back to the RFC 3339 strings the FreeBusy API expects
            time_min = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            time_max = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

            if check_availability(time_min, time_max):
                return start_str  # Return the original string the caller supplied

        except Exception:
            # Malformed time string — skip gracefully
            continue

    return None


def create_event(
    summary: str,
    start_time: str,
    duration_minutes: int = 30,
    attendees: list = None,
    description: str = "",
) -> dict:
    """
    Create a Google Calendar event and email invites to attendees.

    Args:
        summary:          Event title.
        start_time:       ISO-8601 start datetime string (e.g. '2026-07-04T14:00:00').
        duration_minutes: Length of the meeting in minutes (default 30).
        attendees:        List of email address strings. Non-email values are ignored.
        description:      Optional event description / agenda.

    Returns:
        The event resource dict returned by the Calendar API.
    """
    from datetime import datetime, timedelta, timezone

    # ── Calculate end time ─────────────────────────────────────────────────
    normalised = start_time.rstrip("Z")
    start_dt = datetime.fromisoformat(normalised).replace(tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    # Format as RFC 3339 without the trailing "Z" — timeZone field carries the zone.
    start_str = start_dt.strftime("%Y-%m-%dT%H:%M:%S")
    end_str = end_dt.strftime("%Y-%m-%dT%H:%M:%S")

    # ── Build event body ───────────────────────────────────────────────────
    event_body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_str, "timeZone": "UTC"},
        "end":   {"dateTime": end_str,   "timeZone": "UTC"},
    }

    # Only attach attendees that look like real email addresses
    valid_attendees = [
        {"email": addr.strip()}
        for addr in (attendees or [])
        if isinstance(addr, str) and "@" in addr
    ]
    if valid_attendees:
        event_body["attendees"] = valid_attendees

    # ── Create the event ───────────────────────────────────────────────────
    service = _build_calendar_service()
    created = (
        service.events()
        .insert(
            calendarId="primary",
            body=event_body,
            sendUpdates="all",
        )
        .execute()
    )

    return created
