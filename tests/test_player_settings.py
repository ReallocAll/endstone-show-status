from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from endstone_show_status.player_settings import (
    CONTINUOUS_TIP_INTERVAL_TICKS,
    DEFAULT_TIP_INTERVAL_TICKS,
    PlayerSettingsStore,
    TIP_INTERVAL_OPTIONS,
    tip_interval_option_index,
)


class PlayerSettingsStoreTest(unittest.TestCase):
    def test_missing_file_uses_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PlayerSettingsStore(Path(temp_dir) / "player_settings.json")
            self.assertIsNone(store.load())
            self.assertEqual(store.get_tip_interval_ticks("player"), DEFAULT_TIP_INTERVAL_TICKS)

    def test_settings_are_persisted_by_player_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "player_settings.json"
            store = PlayerSettingsStore(path)
            store.set_tip_interval_ticks("uuid-a", 100)
            store.set_tip_interval_ticks("uuid-b", None)

            loaded = PlayerSettingsStore(path)
            self.assertIsNone(loaded.load())
            self.assertEqual(loaded.get_tip_interval_ticks("uuid-a"), 100)
            self.assertIsNone(loaded.get_tip_interval_ticks("uuid-b"))

            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["schema_version"], 2)
            self.assertEqual(raw["players"]["uuid-a"]["tip_interval_ticks"], 100)
            self.assertIsNone(raw["players"]["uuid-b"]["tip_interval_ticks"])

    def test_invalid_interval_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PlayerSettingsStore(Path(temp_dir) / "player_settings.json")
            with self.assertRaises(ValueError):
                store.set_tip_interval_ticks("player", 7)

    def test_invalid_entries_are_ignored_on_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "player_settings.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "players": {
                            "valid": {"tip_interval_ticks": 200},
                            "invalid": {"tip_interval_ticks": 7},
                        },
                    }
                ),
                encoding="utf-8",
            )
            store = PlayerSettingsStore(path)
            self.assertIsNone(store.load())
            self.assertEqual(store.get_tip_interval_ticks("valid"), 200)
            self.assertEqual(store.get_tip_interval_ticks("invalid"), DEFAULT_TIP_INTERVAL_TICKS)

    def test_v023_continuous_setting_migrates_to_five_ticks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "player_settings.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "players": {
                            "continuous": {"tip_interval_seconds": 1},
                            "five-seconds": {"tip_interval_seconds": 5},
                            "disabled": {"tip_interval_seconds": None},
                        },
                    }
                ),
                encoding="utf-8",
            )
            store = PlayerSettingsStore(path)
            self.assertIsNone(store.load())
            self.assertEqual(
                store.get_tip_interval_ticks("continuous"),
                CONTINUOUS_TIP_INTERVAL_TICKS,
            )
            self.assertEqual(store.get_tip_interval_ticks("five-seconds"), 100)
            self.assertIsNone(store.get_tip_interval_ticks("disabled"))

    def test_step_slider_order_keeps_continuous_left_and_disabled_right(self) -> None:
        self.assertEqual(
            TIP_INTERVAL_OPTIONS[0],
            ("持续显示", CONTINUOUS_TIP_INTERVAL_TICKS),
        )
        self.assertEqual(TIP_INTERVAL_OPTIONS[1], ("每 1 秒", 20))
        self.assertEqual(TIP_INTERVAL_OPTIONS[-1], ("不显示", None))
        self.assertEqual(tip_interval_option_index(100), 4)
        self.assertEqual(tip_interval_option_index(None), len(TIP_INTERVAL_OPTIONS) - 1)


if __name__ == "__main__":
    unittest.main()
