"""Regression tests for untrusted configuration, URLs and GUI rule forms."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
PACKAGE = types.ModuleType("radio_filter")
PACKAGE.__path__ = [str(BASE / "radio_filter")]
sys.modules.setdefault("radio_filter", PACKAGE)


def load_part(name):
    spec = importlib.util.spec_from_file_location(
        f"radio_filter.{name}", BASE / "radio_filter" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rules = load_part("rules")
gui = load_part("gui")


class SecurityTests(unittest.TestCase):
    def test_private_network_urls(self):
        for url in (
            "http://127.0.0.1/stream", "http://10.0.0.1:8095/",
            "http://169.254.169.254/latest/meta-data",
            "http://192.168.1.100", "http://[::1]/",
            "http://localhost", "http://foo.local/stream",
            "http://metadata.google.internal/", "file:///etc/passwd",
            "https://user:password@example.org/stream",
            "http://example.org:0/stream",
            "http://example.org#frag",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                rules.validate_monitor_url(url)

    def test_valid_public_stream_urls(self):
        self.assertEqual(
            rules.validate_monitor_url("https://example.org:443/radio.mp3?token=abc"),
            "https://example.org:443/radio.mp3?token=abc",
        )

    def test_unsafe_action_uri(self):
        for uri in ("file:///etc/passwd", "http://host/track/test",
                    "spotify://track/../../etc/passwd\nnew",
                    "spotify://radio/test", "spotify://track/"):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                rules.validate_action({"mode": "track", "uri": uri})

    def test_valid_music_assistant_uri(self):
        action = rules.validate_action({"mode": "track", "uri": "spotify://track/123"})
        self.assertEqual(action["uri"], "spotify://track/123")

    def test_unexpected_rule_fields(self):
        with self.assertRaises(ValueError):
            rules.Rule.from_dict({"kind": "song", "pattern": "x", "shell": "rm"})

    def test_unexpected_action_fields(self):
        with self.assertRaises(ValueError):
            rules.validate_action({"mode": "mute", "code": "__import__('os')"})

    def test_rule_limit(self):
        many = "\n".join("artist" for _ in range(rules.MAX_RULES + 1))
        with self.assertRaises(ValueError):
            rules.load_rules("[]", artists=many)

    def test_config_size_limit(self):
        with self.assertRaises(ValueError):
            rules.load_rules(" " * (rules.MAX_CONFIG_BYTES + 1))

    def test_bad_duration(self):
        with self.assertRaises(ValueError):
            rules.validate_action({
                "mode": "random", "blocked_duration_seconds": 999999
            })

    def test_form_track_selection(self):
        data = {
            "rule_1_kind": "song", "rule_1_pattern": "Bad Song",
            "rule_1_mode": "track", "rule_1_target_track": "spotify://track/123",
            "rule_1_return": "one_song", "rule_1_max_seconds": 240,
        }
        loaded = gui.rules_from_form(data, 1)
        self.assertEqual(loaded[0].action["uri"], "spotify://track/123")
        self.assertEqual(loaded[0].action["return_mode"], "one_song")

    def test_form_typed_song_selection(self):
        data = {
            "rule_1_kind": "artist", "rule_1_pattern": "Blocked Artist",
            "rule_1_mode": "track", "rule_1_track_name": "A Good Song",
        }
        loaded = gui.rules_from_form(data, 1)
        self.assertEqual(loaded[0].action["mode"], "random")
        self.assertEqual(loaded[0].action["title"], "A Good Song")

    def test_form_disabled_rule(self):
        self.assertEqual(gui.rules_from_form({"rule_1_kind": "off"}, 1), [])

    def test_untrusted_form_url_rejected(self):
        with self.assertRaises(ValueError):
            gui.rules_from_form({
                "rule_1_kind": "text", "rule_1_pattern": "news",
                "rule_1_monitor_url": "http://127.0.0.1/admin"
            }, 1)


if __name__ == "__main__":
    unittest.main()
