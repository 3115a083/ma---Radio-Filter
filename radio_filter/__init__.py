"""Radio Filter plugin provider for Music Assistant internet radio playback."""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.enums import ConfigEntryType, MediaType, PlaybackState, QueueOption
from music_assistant.models.plugin import PluginProvider

from .icy import IcyMonitor
from .rules import Rule, load_rules, normalize, split_title

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ProviderConfig
    from music_assistant_models.provider import ProviderManifest
    from music_assistant.mass import MusicAssistant
    from music_assistant.models import ProviderInstanceType

CONF_ARTISTS = "blocked_artists"
CONF_SONGS = "blocked_songs"
CONF_RULES = "rules_json"
CONF_DEFAULT_ACTION = "default_action_json"
CONF_TIMEZONE = "timezone"
CONF_POLL = "poll_interval"
DEFAULT_ACTION = '{"mode":"mute"}'


@dataclass
class Muted:
    """Original volume/mute state for a temporarily filtered player."""

    original_mute: bool
    volume: int | None = None
    started: float = 0.0
    title: str = ""


@dataclass
class Replacement:
    """Information required to return to a previously playing internet radio."""

    original_uri: str
    station: str
    original_text: str
    rule: Rule
    target_uri: str
    mode: str
    return_mode: str
    started: float
    monitor: IcyMonitor | None = None
    first_track_uri: str = ""
    first_track_seen: bool = False


async def setup(
    mass: MusicAssistant, manifest: ProviderManifest, config: ProviderConfig
) -> ProviderInstanceType:
    """Set up the Radio Filter provider."""
    return RadioFilter(mass, manifest, config)


class RadioFilter(PluginProvider):
    """Block configured internet radio content on active Music Assistant queues."""

    def __init__(self, mass, manifest, config) -> None:
        """Initialize state; provider options are loaded in handle_async_init."""
        super().__init__(mass, manifest, config)
        self._rules: list[Rule] = []
        self._tz = ZoneInfo("Europe/Berlin")
        self._interval = 2.0
        self._worker: asyncio.Task | None = None
        self._muted: dict[str, Muted] = {}
        self._replacement: dict[str, Replacement] = {}
        self._ignore_title: dict[str, str] = {}

    async def get_config_entries(self) -> tuple[ConfigEntry, ...]:
        """Expose global blacklist and station-rule editor in provider settings."""
        return (
            ConfigEntry(
                key=CONF_ARTISTS, type=ConfigEntryType.STRING, required=False,
                label="Blocked artists (one per line)", default_value="",
            ),
            ConfigEntry(
                key=CONF_SONGS, type=ConfigEntryType.STRING, required=False,
                label="Blocked songs (one per line, title or Artist - Title)", default_value="",
            ),
            ConfigEntry(
                key=CONF_DEFAULT_ACTION, type=ConfigEntryType.STRING, required=True,
                label="Default blacklist action (JSON)", default_value=DEFAULT_ACTION,
            ),
            ConfigEntry(
                key=CONF_RULES, type=ConfigEntryType.STRING, required=True,
                label="Station/radiotext/time rules (JSON array)", default_value="[]",
            ),
            ConfigEntry(
                key=CONF_TIMEZONE, type=ConfigEntryType.STRING, required=True,
                label="Schedule timezone (IANA name)", default_value="Europe/Berlin",
            ),
            ConfigEntry(
                key=CONF_POLL, type=ConfigEntryType.INTEGER, required=True,
                label="Detection interval (seconds)", default_value=2,
            ),
        )

    async def handle_async_init(self) -> None:
        """Validate configuration before enabling the filter."""
        default_action = json.loads(str(self.get_config_value(CONF_DEFAULT_ACTION, DEFAULT_ACTION)))
        if not isinstance(default_action, dict):
            raise ValueError("Default action must be a JSON object")
        self._rules = load_rules(
            str(self.get_config_value(CONF_RULES, "[]")),
            str(self.get_config_value(CONF_ARTISTS, "")),
            str(self.get_config_value(CONF_SONGS, "")),
            default_action,
        )
        self._tz = ZoneInfo(str(self.get_config_value(CONF_TIMEZONE, "Europe/Berlin")))
        self._interval = max(1.0, min(float(self.get_config_value(CONF_POLL, 2)), 30.0))
        self.logger.info("Radio Filter: %d blocking rules loaded", len(self._rules))

    async def loaded_in_mass(self) -> None:
        """Start a single asynchronous poller for active radio queues."""
        self._worker = asyncio.create_task(self._poll_loop())

    async def unload(self, is_removed: bool = False) -> None:
        """Stop monitoring and restore players muted by the plugin."""
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None
        for session in list(self._replacement.values()):
            if session.monitor:
                await session.monitor.stop()
        self._replacement.clear()
        for queue_id in list(self._muted):
            await self._unmute(queue_id)

    def _match(
        self, station: str, uri: str, radio_text: str,
    ) -> Rule | None:
        """Find the highest-priority rule for an ICY title and station."""
        artist, song = split_title(radio_text)
        now = datetime.now(self._tz)
        for rule in self._rules:
            if rule.applies_to(station, uri) and rule.matches(artist, song, radio_text, now):
                return rule
        return None

    async def _poll_loop(self) -> None:
        """Handle changing metadata, schedules and interruption endings."""
        while True:
            try:
                active = set()
                for queue in self.mass.player_queues.all():
                    queue_id = queue.queue_id
                    active.add(queue_id)
                    try:
                        await self._process_queue(queue)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        self.logger.exception("Radio Filter: error on queue %s", queue_id)
                for queue_id in set(self._muted) - active:
                    self._muted.pop(queue_id, None)
                for queue_id in set(self._replacement) - active:
                    await self._cancel_replacement(queue_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception("Radio Filter: polling failed")
            await asyncio.sleep(self._interval)

    async def _process_queue(self, queue) -> None:
        """Process one queue without interfering with normal music playback."""
        queue_id = queue.queue_id
        if queue_id in self._replacement:
            await self._check_replacement(queue)
            return
        item = getattr(queue, "current_item", None)
        media = getattr(item, "media_item", None) if item else None
        is_live_radio = (
            getattr(media, "media_type", None) == MediaType.RADIO
            and queue.state == PlaybackState.PLAYING
            and getattr(queue, "active", True)
        )
        if not is_live_radio:
            self._ignore_title.pop(queue_id, None)
            if queue_id in self._muted:
                await self._unmute(queue_id)
            return
        uri = str(media.uri)
        station = str(media.name)
        details = getattr(item, "streamdetails", None)
        radio_text = str(getattr(details, "stream_title", None) or "")
        ignore = self._ignore_title.get(queue_id)
        if ignore and normalize(radio_text) != ignore:
            self._ignore_title.pop(queue_id, None)
        if self._ignore_title.get(queue_id) == normalize(radio_text):
            if queue_id in self._muted:
                await self._unmute(queue_id)
            return
        rule = self._match(station, uri, radio_text)
        if rule is None:
            if queue_id in self._muted:
                await self._unmute(queue_id)
            return
        current_mute = self._muted.get(queue_id)
        if current_mute and current_mute.title != radio_text:
            await self._unmute(queue_id)
            current_mute = None
        if current_mute and time.monotonic() - current_mute.started >= rule.max_seconds:
            await self._unmute(queue_id)
            self._ignore_title[queue_id] = normalize(radio_text)
            return
        if current_mute:
            return
        action = rule.action
        if action.get("mode", "mute") == "mute":
            await self._mute(queue_id, radio_text)
        else:
            await self._replace(queue_id, station, uri, radio_text, rule)

    async def _mute(self, queue_id: str, title: str) -> None:
        """Mute temporarily without permanently changing user volume."""
        player = self.mass.players.get_player(queue_id)
        if not player:
            return
        old_muted = bool(getattr(player.state, "volume_muted", False))
        try:
            await self.mass.players.cmd_volume_mute(queue_id, True)
            self._muted[queue_id] = Muted(old_muted, started=time.monotonic(), title=title)
        except Exception:
            volume = getattr(player.state, "volume_level", None)
            if volume is None:
                self.logger.warning("Radio Filter: %s cannot be muted", queue_id)
                return
            try:
                await self.mass.players.cmd_volume_set(queue_id, 0)
                self._muted[queue_id] = Muted(old_muted, int(volume), time.monotonic(), title)
            except Exception:
                self.logger.exception("Radio Filter: cannot mute player %s", queue_id)

    async def _unmute(self, queue_id: str) -> None:
        """Restore only a mute/volume adjustment that this plugin made."""
        state = self._muted.pop(queue_id, None)
        if state is None:
            return
        try:
            if state.volume is not None:
                player = self.mass.players.get_player(queue_id)
                if player and getattr(player.state, "volume_level", None) == 0:
                    await self.mass.players.cmd_volume_set(queue_id, state.volume)
            elif not state.original_mute:
                await self.mass.players.cmd_volume_mute(queue_id, False)
        except Exception:
            self.logger.warning("Radio Filter: failed to restore volume on %s", queue_id)

    async def _replace(
        self, queue_id: str, station: str, uri: str, title: str, rule: Rule,
    ) -> None:
        """Play configured replacement and track the original radio in parallel."""
        action = rule.action
        mode = str(action.get("mode"))
        target = str(action.get("uri", ""))
        if mode == "random":
            target = await self._choose_random_track(action, title)
        if not target or target == uri:
            self.logger.warning("Radio Filter: replacement unavailable; muting instead")
            await self._mute(queue_id, title)
            return
        return_mode = str(action.get("return_mode", "when_clear"))
        monitor = None
        if rule.monitor_url:
            if not rule.monitor_url.startswith(("http://", "https://")):
                self.logger.warning("Radio Filter: monitor_url must be HTTP(S)")
            else:
                monitor = IcyMonitor(self.mass.http_session, rule.monitor_url, self.logger)
                monitor.start()
        session = Replacement(
            original_uri=uri, station=station, original_text=title,
            rule=rule, target_uri=target, mode=mode, return_mode=return_mode,
            started=time.monotonic(), monitor=monitor,
        )
        self._replacement[queue_id] = session
        try:
            await self.mass.player_queues.play_media(
                queue_id, target, option=QueueOption.REPLACE,
                shuffle=bool(action.get("shuffle", False)) if mode == "playlist" else None,
            )
            self.logger.info("Radio Filter: switched %s to %s", station, mode)
        except Exception:
            self.logger.exception("Radio Filter: replacement playback failed")
            await self._cancel_replacement(queue_id)
            await self._mute(queue_id, title)

    async def _choose_random_track(self, action: dict[str, Any], title: str) -> str:
        """Pick one library track, optionally matching artist/genre/duration."""
        artist_filter = normalize(str(action.get("artist", "")))
        genre_filter = normalize(str(action.get("genre", "")))
        candidates = await self.mass.music.tracks.library_items(limit=500, summary=False)
        matches = []
        for track in candidates:
            artists = getattr(track, "artists", ()) or ()
            names = [normalize(str(getattr(artist, "name", ""))) for artist in artists]
            if artist_filter and artist_filter not in names:
                continue
            metadata = getattr(track, "metadata", None)
            genres = getattr(metadata, "genres", ()) or ()
            genre_names = [normalize(str(getattr(genre, "name", genre))) for genre in genres]
            if genre_filter and genre_filter not in genre_names:
                continue
            if self._blocked_library_track(track):
                continue
            matches.append(track)
        if not matches:
            return ""
        if action.get("match_duration"):
            duration = int(action.get("blocked_duration_seconds", 0) or 0)
            if not duration:
                duration = await self._lookup_blocked_duration(title)
            if duration:
                nearest = min(abs(int(getattr(t, "duration", 0) or 0) - duration) for t in matches)
                matches = [t for t in matches if abs(int(getattr(t, "duration", 0) or 0) - duration) == nearest]
        return str(random.choice(matches).uri)

    async def _lookup_blocked_duration(self, text: str) -> int:
        """Best effort duration lookup for ICY titles, which contain no duration."""
        artist, song = split_title(text)
        if not song:
            return 0
        tracks = await self.mass.music.tracks.library_items(search=song, limit=30, summary=False)
        for track in tracks:
            if normalize(track.name) != normalize(song):
                continue
            names = [normalize(a.name) for a in (getattr(track, "artists", []) or [])]
            if not artist or normalize(artist) in names:
                return int(getattr(track, "duration", 0) or 0)
        return 0

    def _blocked_library_track(self, track) -> bool:
        """Avoid choosing a globally blacklisted replacement track."""
        artists = [a.name for a in (getattr(track, "artists", ()) or ())]
        for rule in self._rules:
            if rule.station or rule.kind not in {"artist", "song"}:
                continue
            for artist in (artists or [""]):
                if rule.matches(artist, track.name, "", datetime.now(self._tz)):
                    return True
        return False

    async def _check_replacement(self, queue) -> None:
        """Return when original content clears, one song ends or timeout occurs."""
        queue_id = queue.queue_id
        session = self._replacement[queue_id]
        elapsed = time.monotonic() - session.started
        if elapsed < 3:
            return
        current = getattr(queue, "current_item", None)
        media = getattr(current, "media_item", None)
        playing_uri = str(getattr(media, "uri", "") or "")
        source_items = getattr(queue, "source_items", ()) or ()
        sources = {str(getattr(source, "uri", "") or "") for source in source_items}
        # If the user starts something else, never hijack their next selection.
        if sources and session.target_uri not in sources:
            await self._cancel_replacement(queue_id)
            return
        if session.mode in {"track", "random"} and playing_uri and playing_uri != session.target_uri:
            if session.return_mode == "one_song":
                await self._return_to_radio(queue_id)
            else:
                await self._cancel_replacement(queue_id)
            return
        if session.return_mode == "one_song":
            if playing_uri and not session.first_track_uri:
                session.first_track_uri = playing_uri
                session.first_track_seen = True
            if session.first_track_uri and playing_uri and playing_uri != session.first_track_uri:
                await self._return_to_radio(queue_id)
                return
            if queue.state == PlaybackState.IDLE and session.first_track_seen:
                await self._return_to_radio(queue_id)
                return
        if session.return_mode == "when_clear" and session.monitor:
            monitor = session.monitor
            if monitor.revision and normalize(monitor.title) != normalize(session.original_text):
                if not self._match(session.station, session.original_uri, monitor.title):
                    await self._return_to_radio(queue_id)
                    return
        # Time-based rules can be detected even if ICY is unavailable.
        if session.return_mode == "when_clear" and session.rule.kind == "schedule":
            if not self._match(session.station, session.original_uri, session.original_text):
                await self._return_to_radio(queue_id)
                return
        if elapsed >= session.rule.max_seconds:
            await self._return_to_radio(queue_id)

    async def _cancel_replacement(self, queue_id: str) -> None:
        """Forget a replacement without changing playback (manual override)."""
        session = self._replacement.pop(queue_id, None)
        if session and session.monitor:
            await session.monitor.stop()

    async def _return_to_radio(self, queue_id: str) -> None:
        """Restore the live original stream, not a paused cached position."""
        session = self._replacement.get(queue_id)
        if not session:
            return
        await self._cancel_replacement(queue_id)
        # One-song/timeout return may happen while the blocked title is still live.
        self._ignore_title[queue_id] = normalize(session.original_text)
        try:
            await self.mass.player_queues.play_media(
                queue_id, session.original_uri, option=QueueOption.REPLACE,
            )
            self.logger.info("Radio Filter: restored original radio %s", session.station)
        except Exception:
            self.logger.exception("Radio Filter: failed to return to %s", session.station)
