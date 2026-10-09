# Radio Filter

**Radio Filter** is an experimental Music Assistant plugin for **internet radio only**. It detects blocked artists, individual songs, radiotext keywords (e.g. advertisements/news) and scheduled segments, then mutes or plays replacement music before returning to the original live radio.

## Features

- Native **graphical rule editor in Music Assistant's plugin settings**. No JSON or programming required. Click **Add another rule**, select the artist/song/radiotext/schedule trigger, optionally select a particular radio station, and choose the blocking action.
- Radio, track and playlist dropdowns use your Music Assistant library. You may alternatively enter a song title; random track filters support artist/genre text fields.
- Replacement choices: **mute**, **different radio**, **one specific track**, **playlist with optional shuffle**, or **random library song**.
- Automatic return when the original ICY stream is clear, after one replacement song, or after a safety timeout. Approximate blocked-song-duration matching is available.
- Weekday/overnight time rules, station priority, bounded metadata monitoring and safe player-state cleanup.

## Install as a Home Assistant OS App (recommended for HAOS)

**The stock Music Assistant App cannot load third-party Python providers directly from a GitHub URL.** This repository therefore includes a separate **Music Assistant with Radio Filter** Home Assistant App, which contains the plugin within its own Music Assistant server image.

1. **Make a full Home Assistant backup** including the existing Music Assistant App. Save/export your Music Assistant configuration before proceeding. The new App has *separate data storage* and does **not** automatically migrate existing libraries/settings.
2. In Home Assistant, open **Settings → Apps → App store → three dots (⋮) → Repositories**.
3. Add this URL: `https://github.com/3115a083/ma---Radio-Filter` and confirm.
4. Refresh the App store, find **Music Assistant with Radio Filter** and choose **Install**. Home Assistant will build the custom App from its included Dockerfile using the version-tagged Music Assistant server image. This may require storage and build time.
5. **Stop the original Music Assistant App** so two servers do not compete on the same host/port. Start **Music Assistant with Radio Filter** and select **Open Web UI**.
6. In the new Music Assistant Web UI, go to **Settings → Plugins → Add a plugin → Radio Filter**. Open its configuration and create the rules using dropdowns and input fields. Any Home Assistant Music Assistant integration connected to the previous server may need to be reconfigured.

To revert, stop the custom App and restart your original Music Assistant App. Restore its backup if required.

**Important:** This Home Assistant App variant is experimental and is **not** an update to the official App. It has not yet been tested on a live Home Assistant OS system. Upstream Music Assistant server is pinned to version `2.10.6` in `radio_filter_app/Dockerfile`; review updates carefully. For App-specific details, see [App docs](radio_filter_app/DOCS.md).

## Install into a standalone Music Assistant server (Docker / developer install)

1. Download or clone this repository.
2. Copy `radio_filter/` into the server's installed Python package at `music_assistant/providers/radio_filter/`. The exact site-packages path is image dependent. For Docker, use a controlled immutable custom image rather than modifying running containers.
3. Restart Music Assistant, open **Settings → Plugins → Add plugin → Radio Filter**.
4. Add rules via the GUI.

The plugin is **not** a HACS Home Assistant integration and cannot be installed under `custom_components`.

## Configure rules through the GUI

In **Radio Filter → Settings**, each numbered rule has the following fields:

- **Trigger:** Artist, Song, Radiotext contains, or Time schedule. Use *Disabled* to turn off a rule.
- **Artist / song / keyword:** Text to match. For schedules, choose weekdays and HH:MM start/end in the configured timezone.
- **Apply to radio station:** Choose a station from the library or select *All radio stations*.
- **When blocked:** Mute, switch to radio, play song, play playlist, or random library song.
- **Replacement:** Select a radio/track/playlist in a dropdown, or enter the exact library song name. Optionally specify random artist/genre, shuffle and similar duration.
- **Return:** When original radio is clear, after one replacement song, or after the interruption timeout.
- **Maximum interruption:** Limits how long a rule can remain active (15 to 3600 seconds).
- **Original ICY stream URL (advanced, optional):** A direct, public HTTP(S) ICY stream URL for the original radio, used to detect when a song/ad ends despite replacement playback.

Start with one or two rules. Press **Save** before adding another rule. There are up to 12 GUI rule slots. Global artist/song lists or legacy JSON config from early versions can still be loaded internally but no JSON is needed for new rules.

## Security and limitations

The plugin **never executes radio text or configuration as code**. Rule sizes and media URI schemes are validated. ICY monitors use a separate, time-limited connection without HTTP redirects, cookies or proxies, and DNS lookups must resolve exclusively to public IP addresses. Log messages avoid exposing stream URLs. See [SECURITY.md](SECURITY.md).

Ads, news and football broadcasts can only be detected if supplied radiotext, station metadata or times match. There is **no** audio fingerprinting or speech recognition. ICY metadata may be late or missing. Return after one replacement track may happen while the blocked original content is still live. Matching track length is an approximation, not a guarantee. Monitoring opens another upstream radio connection. Playback switches can create audible gaps.

The GUI currently lists at most 300 library radios/tracks/playlists in dropdowns. Tracks outside that list can be chosen by typing their exact name. Random song selection searches up to 500 library tracks. This app and plugin require full integration testing before production use.

## Tests

CI compiles the Python sources, runs rule/security regression tests, checks for prohibited dynamic-code execution, and verifies that the Home Assistant App contains the same provider code as the standalone plugin. External Action versions are pinned by commit SHA. See [GitHub Actions](https://github.com/3115a083/ma---Radio-Filter/actions).

**Repository rulesets/branch protection must still be enabled by the repository administrator** under GitHub Settings. See [SECURITY.md](SECURITY.md).
