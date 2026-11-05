from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from endstone_show_status.config import load_config


class HUDConfigTest(unittest.TestCase):
    def test_fresh_config_is_created_and_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as folder:
            config, error = load_config(Path(folder))
            self.assertIsNone(error)
            self.assertTrue(config.tip_enabled)
            self.assertEqual(config.default_interval_ticks, 0)
            self.assertTrue((Path(folder) / "hud.toml").exists())

    def test_invalid_config_does_not_get_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "hud.toml"
            original = "[hud]\ntip_enabled = 'false'\n"
            path.write_text(original)
            _, error = load_config(Path(folder))
            self.assertIn("Invalid", error)
            self.assertEqual(path.read_text(), original)

    def test_unknown_config_fails_loudly(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "hud.toml").write_text("[hud]\ntip_enabled=true\nextraneous=true\n")
            _, error = load_config(Path(folder))
            self.assertIn("unknown", error)
