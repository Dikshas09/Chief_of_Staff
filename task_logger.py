"""
task_logger.py
==============
Lightweight action logger for The Draft Desk.

Persists sent-reply and booked-meeting records to action_log.json.
No dependencies beyond the Python standard library.
"""

import json
import os
from datetime import datetime, timezone

LOG_FILE = os.path.join(os.path.dirname(__file__), "action_log.json")


def log_action(
    action_type: str,
    thread_subject: str,
    detail: str,
    action_id: str,
) -> None:
    """
    Append one record to action_log.json, creating the file if needed.

    Args:
        action_type:    "sent" or "booked".
        thread_subject: Subject line of the originating email thread.
        detail:         Recipient email address (for "sent") or meeting
                        title (for "booked").
        action_id:      Gmail message_id (for "sent") or Google Calendar
                        event_id (for "booked").
    """
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action_type": action_type,
        "thread_subject": thread_subject,
        "detail": detail,
        "id": action_id,
    }

    existing = get_action_log()
    existing.append(record)

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)


def get_action_log() -> list:
    """
    Read and return all records from action_log.json.

    Returns:
        List of record dicts, or [] if the file does not exist or is empty.
    """
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def clear_log() -> None:
    """Overwrite action_log.json with an empty list."""
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)
