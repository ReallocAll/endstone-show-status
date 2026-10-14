from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from endstone_show_status.config import load_config
from endstone_show_status.player_settings import PlayerSettingsStore
from endstone_show_status.show_status import ShowStatus


class DefaultTipIntervalTest(unittest.TestCase):
    def test_new_configuration_defaults_to_disabled_with_manual_enable_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config, _, error = load_config(Path(temp_dir))
            self.assertIsNone(error)
            self.assertTrue(config.status.tip_enabled)
            self.assertEqual(config.status.tip_interval_ticks, 0)
            plugin = SimpleNamespace(_plugin_config=config)
            self.assertIsNone(ShowStatus._default_tip_interval_ticks(plugin))

            settings = PlayerSettingsStore(Path(temp_dir) / "player_settings.json")
            self.assertIsNone(settings.get_tip_interval_ticks("new", default=None))
            settings.set_tip_interval_ticks("opted-in", 5)
            self.assertEqual(settings.get_tip_interval_ticks("opted-in", default=None), 5)

    def test_existing_positive_interval_remains_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "config.toml").write_text(
                "[status]\ntip_interval_ticks = 20\n",
                encoding="utf-8",
            )
            config, _, error = load_config(folder)
            self.assertIsNone(error)
            self.assertEqual(config.status.tip_interval_ticks, 20)
            plugin = SimpleNamespace(_plugin_config=config)
            self.assertEqual(ShowStatus._default_tip_interval_ticks(plugin), 20)

    def test_zero_is_preserved_when_explicitly_configured(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "config.toml").write_text(
                "[status]\ntip_interval_ticks = 0\n",
                encoding="utf-8",
            )
            config, _, error = load_config(folder)
            self.assertIsNone(error)
            self.assertEqual(config.status.tip_interval_ticks, 0)


if __name__ == "__main__":
    unittest.main()
