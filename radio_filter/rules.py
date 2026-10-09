"""Pure rule matching for Music Assistant Radio Filter."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def normalize(value: str) -> str:
    """Normalize punctuation, spaces and case."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", value.casefold())).strip()


def split_title(text: str) -> tuple[str, str]:
    """Parse the most common ICY title format."""
    if " - " not in text:
        return "", text.strip()
    artist, title = text.split(" - ", 1)
    return artist.strip(), title.strip()


@dataclass
class Rule:
    """Global or station-specific blocking rule."""

    kind: str
    pattern: str = ""
    station: str = ""
    action: dict[str, Any] = field(default_factory=lambda: {"mode": "mute"})
    days: list[int] = field(default_factory=list)
    start: str = ""
    end: str = ""
    monitor_url: str = ""
    max_seconds: int = 300

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Rule":
        """Validate and construct a blocking rule."""
        kind = str(data.get("kind", "")).lower().strip()
        if kind not in {"artist", "song", "text", "schedule"}:
            raise ValueError(f"Unknown rule kind: {kind}")
        action = data.get("action", {"mode": "mute"})
        if not isinstance(action, dict) or action.get("mode", "mute") not in {
            "mute", "radio", "track", "random", "playlist"
        }:
            raise ValueError("Unknown rule action")
        if action.get("mode") in {"radio", "track", "playlist"} and not action.get("uri"):
            raise ValueError("This action requires a Music Assistant URI")
        if action.get("return_mode", "when_clear") not in {
            "when_clear", "one_song", "timeout"
        }:
            raise ValueError("Invalid return_mode")
        days = data.get("days", [])
        if not isinstance(days, list) or any(type(d) is not int or d not in range(7) for d in days):
            raise ValueError("days must be weekday indexes 0..6")
        start, end = str(data.get("start", "")), str(data.get("end", ""))
        if kind == "schedule":
            for value in (start, end):
                if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
                    raise ValueError("Schedule needs start and end as HH:MM")
        elif not data.get("pattern"):
            raise ValueError("A non-schedule rule needs a pattern")
        return cls(
            kind=kind, pattern=str(data.get("pattern", "")).strip(),
            station=str(data.get("station", "")).strip(), action=action.copy(),
            days=days, start=start, end=end,
            monitor_url=str(data.get("monitor_url", "")).strip(),
            max_seconds=max(15, min(int(data.get("max_seconds", 300)), 3600)),
        )

    def applies_to(self, station_name: str, station_uri: str) -> bool:
        """Return true if the station selector matches, or is absent."""
        return not self.station or normalize(self.station) == normalize(station_name) or self.station == station_uri

    def matches(self, artist: str, title: str, text: str, now: datetime) -> bool:
        """Evaluate a rule against current radio data and local time."""
        pat = normalize(self.pattern)
        if self.kind == "artist":
            return bool(artist and pat == normalize(artist))
        if self.kind == "song":
            return bool(title and (pat == normalize(title) or pat == normalize(f"{artist} - {title}")))
        if self.kind == "text":
            return bool(pat and pat in normalize(text))
        minute = now.hour * 60 + now.minute
        h1, m1 = map(int, self.start.split(":"))
        h2, m2 = map(int, self.end.split(":"))
        start, end = h1 * 60 + m1, h2 * 60 + m2
        if start == end:
            return False
        if start < end:
            return (not self.days or now.weekday() in self.days) and start <= minute < end
        return (minute >= start and (not self.days or now.weekday() in self.days)) or (
            minute < end and (not self.days or (now.weekday() - 1) % 7 in self.days)
        )


def load_rules(
    raw: str, artists: str = "", songs: str = "",
    default_action: dict[str, Any] | None = None,
) -> list[Rule]:
    """Load JSON rules and simple newline-separated global blacklists."""
    data = json.loads(raw or "[]")
    if not isinstance(data, list):
        raise ValueError("Rules must be a JSON array")
    rules = [Rule.from_dict(entry) for entry in data]
    action = default_action or {"mode": "mute"}
    for artist in artists.splitlines():
        if artist.strip():
            rules.append(Rule.from_dict({"kind": "artist", "pattern": artist, "action": action}))
    for song in songs.splitlines():
        if song.strip():
            rules.append(Rule.from_dict({"kind": "song", "pattern": song, "action": action}))
    return sorted(rules, key=lambda rule: bool(rule.station), reverse=True)
