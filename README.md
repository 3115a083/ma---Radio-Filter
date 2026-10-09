# Radio Filter

Experimental **Music Assistant plugin** for filtering **internet radio played inside Music Assistant**.

## Features

- Global artist and song blacklists and station-specific rules.
- Match ICY radiotext, song/artist or local-time schedules (for ads, news and sports segments when metadata/schedules permit).
- Mute or temporarily play a different radio station, one track, a playlist, or a random library track filtered by artist/genre.
- `one_song`: return after one replacement song. `match_duration`: choose a library song with approximately the blocked song's length.
- `when_clear`: monitor the original direct ICY stream independently to return when metadata changes to allowed content.
- Maximum interruption duration, user playback override, original volume restoration and weekday/overnight schedules.

## Installation

1. Download or clone this repository.
2. Copy the whole `radio_filter/` directory (including `manifest.json`) into your Music Assistant server Python package at `music_assistant/providers/radio_filter/`, next to its built-in provider folders. On Docker use a persistent bind mount of this directory. This is **not** a Home Assistant `custom_components` integration.
3. Restart Music Assistant. Go to **Settings → Plugins → Add a plugin → Radio Filter** and configure the plugin options.

**Important:** Music Assistant does not currently provide a standard GitHub-URL plugin installer. The stock Home Assistant OS Music Assistant app may require a custom/dev server image to load third-party code. Verify your provider folder location for your specific server installation.

## Rules

Enter blocked artists and songs on separate lines (`Artist - Title` is supported). `default_action_json` determines the replacement for those global lists; default is `{ "mode": "mute" }`.

Advanced overrides are a JSON array in `rules_json`:

```json
[
  {
    "station": "Example FM", "kind": "text", "pattern": "advertisement",
    "action": {"mode": "radio", "uri": "builtin://radio/REPLACE_ME"},
    "monitor_url": "https://example.org/direct-icy-stream", "max_seconds": 300
  },
  {
    "station": "Example FM", "kind": "schedule", "days": [0,1,2,3,4],
    "start": "12:00", "end": "12:05",
    "action": {"mode": "playlist", "uri": "spotify://playlist/REPLACE_ME", "shuffle": true}
  },
  {
    "kind": "artist", "pattern": "Example Artist",
    "action": {"mode": "random", "genre": "Rock", "return_mode": "one_song",
               "match_duration": true, "blocked_duration_seconds": 215}
  }
]
```

Supported `kind`: `artist`, `song`, `text` (contains), `schedule` (HH:MM). Optional `station` matches the station name or its Music Assistant URI; station rules override global rules. Schedule `days` are ISO weekdays (Monday=0), with the `timezone` setting defaulting to `Europe/Berlin`.

Supported action `mode`: `mute`, `radio`, `track`, `playlist`, `random`. The first three playback alternatives require a Music Assistant `uri`; `random` accepts `artist`, `genre`, `match_duration` and `blocked_duration_seconds`. Playlists support `shuffle`.

Supported `return_mode`: `when_clear` (default), `one_song` (intended for tracks and playlists), `timeout`. `max_seconds` defaults to 300 and is the fallback when the background monitor cannot tell when the original content ends. `one_song` can return before the blocked content finishes.

`monitor_url` must be a direct HTTP(S) **ICY stream** URL for the original station, not HLS or an M3U. Monitoring requires a second network stream; its audio is discarded. Without live ICY metadata, matching and precise automatic returns are not guaranteed. Ads and segments are recognized through the supplied text/schedule rules only, not audio fingerprinting or speech analysis.

Duration matching is approximate: radio metadata rarely contains durations. A matching track in the library or `blocked_duration_seconds` is needed. Random choices sample at most 500 library tracks. Player switches may introduce short audible gaps.

## Development

Run `python -m compileall -q radio_filter` and `python -m unittest discover -s tests -v` or check GitHub Actions. The code has not yet been validated against a live Music Assistant server.
