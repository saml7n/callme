"""Google Calendar integration — check availability & book appointments.

Uses Google Calendar REST API v3 with OAuth refresh tokens.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CALENDAR_API = "https://www.googleapis.com/calendar/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"


async def _get_access_token(config: dict[str, Any]) -> str:
    """Exchange refresh token for a fresh access token."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "refresh_token": config["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


async def check_availability(
    config: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Check free/busy for a time window.

    *params* may contain:
      - date (str) — ISO date, defaults to today
      - time_min (str) — ISO datetime, optional (defaults to start of *date*)
      - time_max (str) — ISO datetime, optional (defaults to end of *date*)
      - duration_minutes (int) — desired slot length, default 30
    """
    access_token = await _get_access_token(config)
    calendar_id = config.get("calendar_id", "primary")
    duration = int(params.get("duration_minutes", 30))

    # Determine time window
    if params.get("time_min") and params.get("time_max"):
        t_min = params["time_min"]
        t_max = params["time_max"]
    elif params.get("date"):
        day = datetime.fromisoformat(params["date"])
        t_min = day.isoformat() + "T00:00:00Z"
        t_max = day.isoformat() + "T23:59:59Z"
    else:
        today = datetime.utcnow().date()
        t_min = f"{today.isoformat()}T00:00:00Z"
        t_max = f"{today.isoformat()}T23:59:59Z"

    async with httpx.AsyncClient(timeout=10) as client:
        # Get events in the window
        resp = await client.get(
            f"{CALENDAR_API}/calendars/{calendar_id}/events",
            params={
                "timeMin": t_min,
                "timeMax": t_max,
                "singleEvents": "true",
                "orderBy": "startTime",
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        events = resp.json().get("items", [])

    busy_slots = []
    for evt in events:
        start = evt.get("start", {}).get("dateTime", evt.get("start", {}).get("date", ""))
        end = evt.get("end", {}).get("dateTime", evt.get("end", {}).get("date", ""))
        busy_slots.append({"start": start, "end": end, "summary": evt.get("summary", "")})

    return {
        "calendar_id": calendar_id,
        "time_min": t_min,
        "time_max": t_max,
        "busy_slots": busy_slots,
        "busy_count": len(busy_slots),
        "requested_duration_minutes": duration,
    }


async def book_appointment(
    config: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Book an appointment on the calendar.

    *params* must contain:
      - start_time (str) — ISO datetime for the event start
      - duration_minutes (int) — length, default 30
      - summary (str) — event title
      - description (str) — optional notes
      - attendee_email (str) — optional attendee
    """
    access_token = await _get_access_token(config)
    calendar_id = config.get("calendar_id", "primary")

    start_str = params["start_time"]
    duration = int(params.get("duration_minutes", 30))
    start_dt = datetime.fromisoformat(start_str)
    end_dt = start_dt + timedelta(minutes=duration)

    event_body: dict[str, Any] = {
        "summary": params.get("summary", "Appointment"),
        "description": params.get("description", ""),
        "start": {"dateTime": start_dt.isoformat(), "timeZone": config.get("timezone", "UTC")},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": config.get("timezone", "UTC")},
    }

    attendee = params.get("attendee_email")
    if attendee:
        event_body["attendees"] = [{"email": attendee}]

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{CALENDAR_API}/calendars/{calendar_id}/events",
            json=event_body,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        created = resp.json()

    return {
        "event_id": created.get("id"),
        "html_link": created.get("htmlLink"),
        "start": created.get("start", {}).get("dateTime"),
        "end": created.get("end", {}).get("dateTime"),
        "summary": created.get("summary"),
        "status": "confirmed",
    }


# Registry of supported actions for this integration type
ACTIONS: dict[str, Any] = {
    "check_availability": check_availability,
    "book_appointment": book_appointment,
}
