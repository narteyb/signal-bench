# SPDX-License-Identifier: Apache-2.0
"""Helpers for parsing telemetry JSON-line events in integration tests."""

from __future__ import annotations

import json
from typing import Any

Event = dict[str, Any]


def parse_events(stderr_bytes: bytes | str) -> list[Event]:
    """Parse JSON-line telemetry events, ignoring non-JSON stderr lines."""
    text = stderr_bytes.decode() if isinstance(stderr_bytes, bytes) else stderr_bytes
    events: list[Event] = []
    for line in text.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "event" in payload:
            events.append(payload)
    return events


def events_of_type(events: list[Event], event_name: str) -> list[Event]:
    """Return all events with a matching event name."""
    return [event for event in events if event.get("event") == event_name]


def find_event(events: list[Event], event_name: str) -> Event:
    """Return the single matching event."""
    matches = events_of_type(events, event_name)
    if len(matches) != 1:
        msg = f"expected one {event_name!r} event, found {len(matches)}"
        raise AssertionError(msg)
    return matches[0]
