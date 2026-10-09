"""Native Music Assistant form fields for editing Radio Filter rules without JSON."""

from __future__ import annotations

from typing import Any

from .rules import Rule

MAX_GUI_RULES = 12
COUNT_KEY = "gui_rule_count"
DEFAULT_COUNT = 2

KINDS = (
    ("off", "Disabled"),
    ("artist", "Artist"),
    ("song", "Song"),
    ("text", "Radio text contains"),
    ("schedule", "Time schedule"),
)
MODES = (
    ("mute", "Mute"),
    ("radio", "Switch to radio"),
    ("track", "Play a particular song"),
    ("playlist", "Play a playlist"),
    ("random", "Random library song"),
)
RETURN_OPTIONS = (
    ("when_clear", "When original radio is clear"),
    ("one_song", "After one replacement song"),
    ("timeout", "After time limit"),
)
WEEKDAYS = (
    ("0", "Monday"), ("1", "Tuesday"), ("2", "Wednesday"), ("3", "Thursday"),
    ("4", "Friday"), ("5", "Saturday"), ("6", "Sunday"),
)


def key(slot: int, name: str) -> str:
    """Return a stable Music Assistant config key."""
    if not 1 <= slot <= MAX_GUI_RULES:
        raise ValueError("Rule slot out of bounds")
    return f"rule_{slot}_{name}"


def rules_from_form(values: dict[str, Any], count: int) -> list[Rule]:
    """Convert native form values to safely validated rules."""
    if type(count) is not int or not 0 <= count <= MAX_GUI_RULES:
        raise ValueError("Invalid number of rules")
    result: list[Rule] = []
    for number in range(1, count + 1):
        read = lambda name, fallback="": values.get(key(number, name), fallback)
        kind = read("kind", "off")
        if kind == "off":
            continue
        mode = read("mode", "mute")
        return_mode = read("return", "when_clear")
        action: dict[str, Any] = {"mode": mode, "return_mode": return_mode}
        if mode == "radio":
            action["uri"] = read("target_radio")
        elif mode == "playlist":
            action["uri"] = read("target_playlist")
            action["shuffle"] = read("shuffle", False)
        elif mode == "track":
            target = read("target_track")
            if target:
                action["uri"] = target
            else:
                # A typed song name is searched in the library at playback time.
                mode = "random"
                action["mode"] = mode
                action["title"] = read("track_name")
                if not action["title"]:
                    raise ValueError(f"Rule {number}: select or enter a song")
        elif mode == "random":
            action["artist"] = read("random_artist")
            action["genre"] = read("random_genre")
        if mode == "random":
            if action.get("title"):
                action["artist"] = read("random_artist")
            action["match_duration"] = read("match_duration", False)
            action["blocked_duration_seconds"] = read("duration", 0)
        day_values = read("days", [])
        if not isinstance(day_values, list):
            raise ValueError(f"Rule {number}: days must be selected from the form")
        result.append(Rule.from_dict({
            "kind": kind,
            "pattern": read("pattern"),
            "station": read("station"),
            "action": action,
            "days": [int(day) for day in day_values] if kind == "schedule" else [],
            "start": read("start") if kind == "schedule" else "",
            "end": read("end") if kind == "schedule" else "",
            "monitor_url": read("monitor_url"),
            "max_seconds": read("max_seconds", 300),
        }))
    return result


async def build_form(provider) -> tuple:
    """Create MA-native input fields, radio/track/playlist selectors and add/remove buttons."""
    from music_assistant_models.config_entries import ConfigEntry, ConfigValueOption
    from music_assistant_models.enums import ConfigEntryType

    def select_options(items, include_all=False):
        """Convert library entries into a bounded set of dropdown choices."""
        options = [ConfigValueOption("", "All radio stations" if include_all else "Select an item")]
        seen = set()
        for media in items:
            uri = str(getattr(media, "uri", ""))
            if uri and uri not in seen:
                seen.add(uri)
                options.append(ConfigValueOption(uri, str(getattr(media, "name", uri))[:90]))
        return options

    async def items(controller, limit):
        try:
            return await controller.library_items(limit=limit)
        except Exception as exc:
            provider.logger.warning("Radio Filter: library selectors unavailable: %s", type(exc).__name__)
            return []

    radios = await items(provider.mass.music.radio, 300)
    tracks = await items(provider.mass.music.tracks, 300)
    playlists = await items(provider.mass.music.playlists, 300)
    radio_options = select_options(radios, include_all=True)
    track_options = select_options(tracks)
    playlist_options = select_options(playlists)

    entries = [
        ConfigEntry(
            key=COUNT_KEY, type=ConfigEntryType.INTEGER, default_value=DEFAULT_COUNT,
            hidden=True, required=True,
        ),
        ConfigEntry(
            key="gui_add_rule", type=ConfigEntryType.ACTION, action="add_rule",
            action_label="Add another rule", required=False, label="Add rule",
            description="Save current changes before adding a rule.",
        ),
        ConfigEntry(
            key="gui_remove_rule", type=ConfigEntryType.ACTION, action="remove_rule",
            action_label="Remove last rule", required=False, label="Remove last rule",
            description="Deletes the last rule; save before editing other rules.",
        ),
    ]

    def add(slot, name, type_, label, *, default=None, options=None,
            depends=None, depends_value=None, description=None, multi=False, advanced=False):
        entries.append(ConfigEntry(
            key=key(slot, name), type=type_, label=label, required=False,
            default_value=default, options=options or [],
            depends_on=key(slot, depends) if depends else None,
            depends_on_value=depends_value, multi_value=multi,
            category=f"radio_filter_rule_{slot}", advanced=advanced,
            description=description,
        ))

    opts = lambda pairs: [ConfigValueOption(value, title) for value, title in pairs]
    count = max(0, min(MAX_GUI_RULES, int(provider.get_config_value(COUNT_KEY, DEFAULT_COUNT))))
    for slot in range(1, count + 1):
        add(slot, "kind", ConfigEntryType.STRING, f"Rule {slot}: Trigger", default="off", options=opts(KINDS))
        add(slot, "pattern", ConfigEntryType.STRING, "Artist / song / keyword",
            default="", description="Artist name, song title, or word to find in radiotext. Not used for schedules.")
        add(slot, "station", ConfigEntryType.STRING, "Apply to radio station",
            default="", options=radio_options,
            description="Leave 'All radio stations' for a global rule.")
        add(slot, "days", ConfigEntryType.STRING, "Days of week (empty means every day)",
            default=[], options=opts(WEEKDAYS), multi=True,
            depends="kind", depends_value="schedule")
        add(slot, "start", ConfigEntryType.STRING, "Start time (HH:MM)",
            default="12:00", depends="kind", depends_value="schedule")
        add(slot, "end", ConfigEntryType.STRING, "End time (HH:MM)",
            default="12:05", depends="kind", depends_value="schedule")
        add(slot, "mode", ConfigEntryType.STRING, "When blocked",
            default="mute", options=opts(MODES))
        add(slot, "target_radio", ConfigEntryType.STRING, "Replacement radio",
            default="", options=radio_options,
            depends="mode", depends_value="radio")
        add(slot, "target_track", ConfigEntryType.STRING, "Replacement song (library)",
            default="", options=track_options, depends="mode", depends_value="track")
        add(slot, "track_name", ConfigEntryType.STRING, "Song name (if not in selector)",
            default="", depends="mode", depends_value="track",
            description="Exact song title in your library. Takes effect if no track is selected.")
        add(slot, "target_playlist", ConfigEntryType.STRING, "Replacement playlist",
            default="", options=playlist_options, depends="mode", depends_value="playlist")
        add(slot, "shuffle", ConfigEntryType.BOOLEAN, "Shuffle playlist",
            default=False, depends="mode", depends_value="playlist")
        add(slot, "random_artist", ConfigEntryType.STRING, "Replacement artist (optional)",
            default="", description="Use for random songs or song-name lookup.")
        add(slot, "random_genre", ConfigEntryType.STRING, "Random-song genre (optional)", default="")
        add(slot, "match_duration", ConfigEntryType.BOOLEAN, "Find similar song duration",
            default=False)
        add(slot, "duration", ConfigEntryType.INTEGER, "Blocked song duration, seconds (0 = lookup)",
            default=0)
        add(slot, "return", ConfigEntryType.STRING, "Return to original radio",
            default="when_clear", options=opts(RETURN_OPTIONS))
        add(slot, "max_seconds", ConfigEntryType.INTEGER, "Maximum interruption, seconds",
            default=300, description="Safety fallback: 15 to 3600 seconds.")
        add(slot, "monitor_url", ConfigEntryType.STRING, "Original ICY stream URL (optional)",
            default="", advanced=True,
            description="Use an HTTPS direct public stream URL for precise return; no redirects or local IPs.")
    return tuple(entries)
