"""Validated, dependency-free rule parsing for Music Assistant Radio Filter."""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

MAX_RULES = 200
MAX_CONFIG_BYTES = 131072
MAX_TEXT = 2048
ALLOWED_KINDS = frozenset({"artist", "song", "text", "schedule"})
ALLOWED_MODES = frozenset({"mute", "radio", "track", "random", "playlist"})
RETURN_MODES = frozenset({"when_clear", "one_song", "timeout"})
URI_PATTERN = re.compile(r"^[a-z][a-z0-9_]*://(radio|track|playlist)/[^\s\x00-\x1f]{1,512}$")
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def normalize(value: str) -> str:
    """Normalize case and punctuation with bounded input."""
    value = value[:MAX_TEXT]
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", value.casefold())).strip()


def split_title(text: str) -> tuple[str, str]:
    """Extract artist and title from a typical ICY StreamTitle."""
    text = text[:MAX_TEXT]
    if " - " not in text:
        return "", text.strip()
    artist, title = text.split(" - ", 1)
    return artist.strip(), title.strip()


def _text(value: Any, name: str, limit: int = 256) -> str:
    """Reject non-text values, control bytes and overlong strings."""
    if not isinstance(value, str) or len(value) > limit or any(
        ord(char) < 32 and char not in "\t\n" for char in value
    ):
        raise ValueError(f"Invalid {name}: expected at most {limit} characters")
    return value.strip()


def validate_monitor_url(value: str) -> str:
    """Validate URL syntax and local targets; DNS is validated again when connecting."""
    url = _text(value, "monitor_url", 2048)
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        hostname = parts.hostname or ""
        port = parts.port
    except ValueError as exc:
        raise ValueError("Invalid monitor_url") from exc
    if (
        parts.scheme not in {"http", "https"}
        or not hostname
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
        or "%" in hostname
        or not hostname.isascii()
        or hostname.strip(".").casefold() in {"localhost", "metadata.google.internal"}
        or hostname.casefold().endswith((".localhost", ".local", ".internal", ".test", ".invalid"))
        or port == 0
    ):
        raise ValueError("monitor_url must point to a public HTTP(S) radio stream")
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        # Domain names are checked for public DNS results at connect time.
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", hostname) or ".." in hostname:
            raise ValueError("Invalid monitor_url hostname") from None
    else:
        if not addr.is_global:
            raise ValueError("Private or reserved monitor_url address is blocked")
    return url


def validate_action(raw: Any) -> dict[str, Any]:
    """Allow only declared actions and MA media URIs, not arbitrary web/file targets."""
    if not isinstance(raw, dict):
        raise ValueError("action must be a JSON object")
    mode = raw.get("mode", "mute")
    if mode not in ALLOWED_MODES:
        raise ValueError("Unknown action mode")
    return_mode = raw.get("return_mode", "when_clear")
    if return_mode not in RETURN_MODES:
        raise ValueError("Unknown return_mode")
    allowed = {
        "mode", "uri", "return_mode", "artist", "genre", "shuffle",
        "match_duration", "blocked_duration_seconds", "title",
    }
    if set(raw) - allowed:
        raise ValueError("Unknown action options")
    action = {"mode": mode, "return_mode": return_mode}
    if mode in {"radio", "track", "playlist"}:
        uri = _text(raw.get("uri"), "action.uri", 600)
        match = URI_PATTERN.fullmatch(uri)
        if not match or match.group(1) != mode:
            raise ValueError("action.uri must be an MA URI of the selected media type")
        action["uri"] = uri
    elif "uri" in raw:
        raise ValueError("action.uri is not used for this mode")
    if mode == "random":
        for fieldname in ("artist", "genre", "title"):
            if fieldname in raw:
                action[fieldname] = _text(raw[fieldname], fieldname)
        if "match_duration" in raw:
            if type(raw["match_duration"]) is not bool:
                raise ValueError("match_duration must be boolean")
            action["match_duration"] = raw["match_duration"]
        if "blocked_duration_seconds" in raw:
            value = raw["blocked_duration_seconds"]
            if type(value) is not int or not 0 <= value <= 7200:
                raise ValueError("blocked_duration_seconds must be 0..7200")
            action["blocked_duration_seconds"] = value
    elif any(key in raw for key in ("artist", "genre", "title", "match_duration", "blocked_duration_seconds")):
        raise ValueError("Random-only options used for a different mode")
    if "shuffle" in raw:
        if mode != "playlist" or type(raw["shuffle"]) is not bool:
            raise ValueError("shuffle is only supported for playlists")
        action["shuffle"] = raw["shuffle"]
    if return_mode == "one_song" and mode not in {"track", "random", "playlist"}:
        raise ValueError("one_song requires track, random or playlist replacement")
    return action


@dataclass
class Rule:
    """Global or station-scoped music/text/schedule filter."""

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
        """Parse a rule and reject potentially hostile or surprising inputs."""
        if not isinstance(data, dict):
            raise ValueError("Each rule must be a JSON object")
        if set(data) - {
            "kind", "pattern", "station", "action", "days", "start",
            "end", "monitor_url", "max_seconds",
        }:
            raise ValueError("Unknown rule option")
        kind = data.get("kind")
        if kind not in ALLOWED_KINDS:
            raise ValueError("Unknown rule kind")
        action = validate_action(data.get("action", {"mode": "mute"}))
        pattern = _text(data.get("pattern", ""), "pattern")
        if kind != "schedule" and not pattern:
            raise ValueError("Non-schedule rules need a pattern")
        days = data.get("days", [])
        if (
            not isinstance(days, list)
            or len(days) > 7
            or any(type(day) is not int or day not in range(7) for day in days)
        ):
            raise ValueError("days must contain at most 7 weekday indexes (0..6)")
        start, end = _text(data.get("start", ""), "start"), _text(data.get("end", ""), "end")
        if kind == "schedule" and (not TIME_PATTERN.fullmatch(start) or not TIME_PATTERN.fullmatch(end)):
            raise ValueError("Schedules require HH:MM start and end")
        if kind != "schedule" and (start or end or days):
            raise ValueError("Time options require a schedule rule")
        max_seconds = data.get("max_seconds", 300)
        if type(max_seconds) is not int or not 15 <= max_seconds <= 3600:
            raise ValueError("max_seconds must be 15..3600")
        return cls(
            kind=kind,
            pattern=pattern,
            station=_text(data.get("station", ""), "station", 512),
            action=action,
            days=days,
            start=start,
            end=end,
            monitor_url=validate_monitor_url(data.get("monitor_url", "")),
            max_seconds=max_seconds,
        )

    def applies_to(self, station_name: str, station_uri: str) -> bool:
        """Accept global rules or rules matching a specific station."""
        return not self.station or (
            normalize(self.station) == normalize(station_name) or self.station == station_uri
        )

    def matches(self, artist: str, title: str, text: str, now: datetime) -> bool:
        """Match metadata or a timezone-aware schedule, including overnight windows."""
        pattern = normalize(self.pattern)
        if self.kind == "artist":
            return bool(artist and normalize(artist) == pattern)
        if self.kind == "song":
            return bool(title and (
                normalize(title) == pattern or normalize(f"{artist} - {title}") == pattern
            ))
        if self.kind == "text":
            return pattern in normalize(text)
        minute = now.hour * 60 + now.minute
        hour1, min1 = map(int, self.start.split(":"))
        hour2, min2 = map(int, self.end.split(":"))
        start, end = hour1 * 60 + min1, hour2 * 60 + min2
        if start == end:
            return False
        if start < end:
            return (not self.days or now.weekday() in self.days) and start <= minute < end
        return (
            (minute >= start and (not self.days or now.weekday() in self.days))
            or (minute < end and (not self.days or (now.weekday() - 1) % 7 in self.days))
        )


def load_rules(
    raw: str, artists: str = "", songs: str = "",
    default_action: dict[str, Any] | None = None,
) -> list[Rule]:
    """Parse bounded JSON rules and global newline-separated blacklists."""
    if not all(isinstance(item, str) and len(item.encode("utf-8")) <= MAX_CONFIG_BYTES
               for item in (raw, artists, songs)):
        raise ValueError("Radio Filter configuration exceeds size limit")
    data = json.loads(raw or "[]")
    if not isinstance(data, list):
        raise ValueError("Rules must be a JSON array")
    if len(data) + len(artists.splitlines()) + len(songs.splitlines()) > MAX_RULES:
        raise ValueError(f"Maximum number of rules is {MAX_RULES}")
    validated_default = validate_action(default_action if default_action is not None else {"mode": "mute"})
    result = [Rule.from_dict(item) for item in data]
    for kind, source in (("artist", artists), ("song", songs)):
        for entry in source.splitlines():
            if entry.strip():
                result.append(Rule.from_dict({
                    "kind": kind, "pattern": entry, "action": validated_default,
                }))
    return sorted(result, key=lambda rule: bool(rule.station), reverse=True)
