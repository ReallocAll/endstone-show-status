from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from endstone_show_status.show_status import ShowStatus, _metric


class HUDTest(unittest.TestCase):
    def test_metrics_and_colors_without_spark_dependency(self):
        fake = SimpleNamespace(server=SimpleNamespace(average_tps=19.8, average_mspt=21.4))
        self.assertIn("19.8", ShowStatus._base_text(fake))
        self.assertIn("21.4", ShowStatus._base_text(fake))
        self.assertEqual(_metric(float("nan")), 0)

    def test_ping_message(self):
        fake_player = SimpleNamespace(ping=33, send_tip=Mock())
        ShowStatus._send_tip(fake_player, "BASE")
        self.assertIn("33ms", fake_player.send_tip.call_args.args[0])
