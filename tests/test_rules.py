"""Unit tests for Radio Filter's dependency-free rule engine."""

import importlib.util
import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

spec = importlib.util.spec_from_file_location(
    "radio_filter_rules", Path(__file__).resolve().parents[1] / "radio_filter" / "rules.py"
)
rules = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = rules
spec.loader.exec_module(rules)


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.time = datetime(2026, 10, 9, 12, 3, tzinfo=ZoneInfo("Europe/Berlin"))

    def test_artist_case_and_punctuation(self):
        rule = rules.Rule.from_dict({"kind": "artist", "pattern": "Example Artist"})
        self.assertTrue(rule.matches("example artist", "Other Song", "", self.time))
        self.assertFalse(rule.matches("Different Artist", "", "", self.time))

    def test_song_title_and_artist(self):
        rule = rules.Rule.from_dict({"kind": "song", "pattern": "Example Artist - Bad Song"})
        self.assertTrue(rule.matches("Example Artist", "Bad Song", "", self.time))
        self.assertFalse(rule.matches("Other Artist", "Bad Song", "", self.time))

    def test_radiotext(self):
        rule = rules.Rule.from_dict({"kind": "text", "pattern": "WERBUNG"})
        self.assertTrue(rule.matches("", "", "Jetzt: Werbung!", self.time))

    def test_schedule_weekdays(self):
        rule = rules.Rule.from_dict({
            "kind": "schedule", "start": "12:00", "end": "12:05", "days": [4]
        })
        self.assertTrue(rule.matches("", "", "", self.time))
        self.assertFalse(rule.matches("", "", "", self.time.replace(hour=12, minute=5)))
        self.assertFalse(rule.matches("", "", "", self.time.replace(day=10)))

    def test_overnight_schedule(self):
        rule = rules.Rule.from_dict({
            "kind": "schedule", "start": "23:00", "end": "01:00", "days": [4]
        })
        self.assertTrue(rule.matches("", "", "", self.time.replace(hour=23, minute=10)))
        self.assertTrue(rule.matches("", "", "", self.time.replace(day=10, hour=0, minute=30)))

    def test_station_priority(self):
        entries = '[{"kind":"text","pattern":"news"},{"kind":"text","pattern":"news","station":"My Radio","action":{"mode":"track","uri":"library://track/1"}}]'
        found = rules.load_rules(entries)
        self.assertEqual(found[0].station, "My Radio")
        self.assertTrue(found[0].applies_to("My Radio", "x"))
        self.assertFalse(found[0].applies_to("Other", "x"))

    def test_invalid_action(self):
        with self.assertRaises(ValueError):
            rules.Rule.from_dict({"kind": "text", "pattern": "news", "action": {"mode": "track"}})

    def test_split_metadata(self):
        self.assertEqual(rules.split_title("Artist - Song"), ("Artist", "Song"))
        self.assertEqual(rules.split_title("News"), ("", "News"))


if __name__ == "__main__":
    unittest.main()
