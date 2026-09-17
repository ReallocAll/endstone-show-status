from __future__ import annotations

import json
import sys
import threading
import types
import unittest
from collections import deque
from types import SimpleNamespace
from unittest import mock

from endstone_show_status.show_status import ShowStatus
from endstone_show_status.spark_papi import SparkPapiClient


class FakePlaceholderAPI:
    def __init__(
        self,
        values: dict[str, str] | None = None,
        *,
        active: bool = True,
        registered: bool = True,
    ) -> None:
        self.active = active
        self.registered = registered
        self.values = values or {}
        self.requests: list[tuple[object | None, str]] = []

    @staticmethod
    def load(service_manager: FakeServiceManager) -> object | None:
        return service_manager.load("PlaceholderAPI")

    def is_registered(self, identifier: str) -> bool:
        return self.registered and identifier == "spark"

    def set_placeholders(self, player: object | None, text: str) -> str:
        self.requests.append((player, text))
        return self.values.get(text, text)


class FakeServiceManager:
    def __init__(self, service: object | None) -> None:
        self.service = service
        self.loads = 0

    def load(self, name: str) -> object | None:
        self.loads += 1
        return self.service if name == "PlaceholderAPI" else None


class FakeServer:
    def __init__(self, service: object | None) -> None:
        self.service_manager = FakeServiceManager(service)


class FakeSystemMetricsCollector:
    def get_snapshot(self) -> SimpleNamespace:
        return SimpleNamespace(
            to_dict=lambda: {
                "sampled_at_ms": 123,
                "process_cpu_percent": 3.0,
                "process_rss_bytes": 456,
                "logical_cpu_count": 1,
                "cpu_average_percent": 5.0,
                "cpu_max_core_percent": 6.0,
                "memory_used_bytes": 100,
                "memory_total_bytes": 200,
                "memory_percent": 50.0,
                "disk_used_bytes": 300,
                "disk_total_bytes": 400,
                "disk_percent": 75.0,
                "network_receive_bytes_per_second": 1.0,
                "network_send_bytes_per_second": 2.0,
            }
        )


class FakeShowStatus(ShowStatus):
    @property
    def server(self) -> FakeServer:
        return self._test_server


class SparkPapiClientTest(unittest.TestCase):
    def setUp(self) -> None:
        module = types.ModuleType("endstone_papi")
        module.PlaceholderAPI = FakePlaceholderAPI
        self.module_patch = mock.patch.dict(sys.modules, {"endstone_papi": module})
        self.module_patch.start()

    def tearDown(self) -> None:
        self.module_patch.stop()

    def test_reads_real_public_placeholder_results(self) -> None:
        fallback = {
            "tps": 7.25,
            "mspt": 77.5,
            "process_cpu": 4.0,
            "system_cpu": 11.0,
        }
        service = FakePlaceholderAPI(
            {
                "{spark:tps_5s}": "§a*20.0",
                "{spark:tickduration_10s}": "§a1.2§7/§a2.3§7/§e40.0§7/§c55.0",
                "{spark:cpu_process_10s}": "§e67%",
                "{spark:cpu_system_1m}": "§e83%",
            }
        )
        server = FakeServer(service)

        metrics = SparkPapiClient().read(server)

        self.assertTrue(metrics.available)
        self.assertEqual(metrics.tps_5s, 20.0)
        self.assertEqual(metrics.mspt_10s_median, 2.3)
        self.assertEqual(metrics.process_cpu_10s_percent, 67.0)
        self.assertEqual(metrics.system_cpu_1m_percent, 83.0)
        self.assertNotEqual(metrics.tps_5s, fallback["tps"])
        self.assertNotEqual(metrics.mspt_10s_median, fallback["mspt"])
        self.assertNotEqual(metrics.process_cpu_10s_percent, fallback["process_cpu"])
        self.assertNotEqual(metrics.system_cpu_1m_percent, fallback["system_cpu"])
        self.assertEqual(
            service.requests,
            [
                (None, "{spark:tps_5s}"),
                (None, "{spark:tickduration_10s}"),
                (None, "{spark:cpu_process_10s}"),
                (None, "{spark:cpu_system_1m}"),
            ],
        )

    def test_absent_inactive_unregistered_and_unresolved_are_safe(self) -> None:
        self.assertFalse(SparkPapiClient().read(FakeServer(None)).available)
        self.assertFalse(
            SparkPapiClient()
            .read(FakeServer(FakePlaceholderAPI(active=False)))
            .available
        )
        self.assertFalse(
            SparkPapiClient()
            .read(FakeServer(FakePlaceholderAPI(registered=False)))
            .available
        )

        unresolved = SparkPapiClient().read(FakeServer(FakePlaceholderAPI()))
        self.assertTrue(unresolved.available)
        self.assertIsNone(unresolved.tps_5s)
        self.assertIsNone(unresolved.mspt_10s_median)
        self.assertIsNone(unresolved.process_cpu_10s_percent)
        self.assertIsNone(unresolved.system_cpu_1m_percent)

    def test_final_status_uses_papi_values_over_fallbacks(self) -> None:
        service = FakePlaceholderAPI(
            {
                "{spark:tps_5s}": "§a*19.75",
                "{spark:tickduration_10s}": "§a1.0§7/§a31.25§7/§e40.0§7/§c55.0",
                "{spark:cpu_process_10s}": "§e66%",
                "{spark:cpu_system_1m}": "§e88%",
            }
        )
        server = FakeServer(service)
        server.average_tps = 8.25
        server.average_mspt = 91.5
        server.average_tick_usage = 0.9
        server.online_players = []
        server.max_players = 20

        plugin = FakeShowStatus.__new__(FakeShowStatus)
        plugin.is_running = True
        plugin._test_server = server
        plugin._spark_papi = SparkPapiClient()
        plugin._endstone_version = "0.11-test"
        plugin._plugin_version = "test"
        plugin._last_snapshot_error_at = 0.0
        plugin._last_snapshot_error_text = ""
        plugin._plugin_config = SimpleNamespace(
            status=SimpleNamespace(
                expose_chat=True,
                expose_players=True,
                snapshot_interval_ticks=20,
                history_seconds=300,
            ),
            ui=SimpleNamespace(
                server_name="Test",
                server_address="localhost",
                language="en",
                default_theme="dark",
            ),
        )
        plugin.metrics_collector = FakeSystemMetricsCollector()
        plugin._minecraft_version = "test"
        plugin._process_started_at = 0.0
        plugin.http_server = None
        plugin.chat_lock = threading.Lock()
        plugin.chat_log = []
        plugin.snapshot_lock = threading.Lock()
        plugin.history = deque()
        plugin._cache_lock = threading.Lock()
        plugin._revision = 0
        plugin.status_text = ""

        plugin.update_status()

        payload = json.loads(plugin.get_cached_status_response().body)
        self.assertEqual(payload["server"]["tps"], 19.75)
        self.assertEqual(payload["server"]["mspt"], 31.25)
        self.assertEqual(payload["process"]["host_share_percent"], 66.0)
        self.assertEqual(payload["system"]["cpu_average_percent"], 88.0)
        self.assertEqual(payload["spark"]["tps_5s"], 19.75)
        self.assertEqual(payload["spark"]["mspt_10s_median"], 31.25)
        self.assertEqual(payload["spark"]["process_cpu_10s_percent"], 66.0)
        self.assertEqual(payload["spark"]["system_cpu_1m_percent"], 88.0)
        self.assertNotEqual(payload["server"]["tps"], server.average_tps)
        self.assertNotEqual(payload["server"]["mspt"], server.average_mspt)
        self.assertNotEqual(payload["process"]["host_share_percent"], 3.0)
        self.assertNotEqual(payload["system"]["cpu_average_percent"], 5.0)
        self.assertNotEqual(payload["spark"]["system_cpu_1m_percent"], 5.0)
        self.assertEqual(
            service.requests,
            [
                (None, "{spark:tps_5s}"),
                (None, "{spark:tickduration_10s}"),
                (None, "{spark:cpu_process_10s}"),
                (None, "{spark:cpu_system_1m}"),
            ],
        )

    def test_reloads_after_retained_service_becomes_inactive(self) -> None:
        old = FakePlaceholderAPI({"{spark:tps_5s}": "§a19.9"})
        server = FakeServer(old)
        client = SparkPapiClient()
        self.assertEqual(client.read(server).tps_5s, 19.9)

        old.active = False
        replacement = FakePlaceholderAPI({"{spark:tps_5s}": "§a18.5"})
        server.service_manager.service = replacement
        self.assertEqual(client.read(server).tps_5s, 18.5)
        self.assertGreaterEqual(server.service_manager.loads, 2)

        client.close()
        self.assertIsNone(client._service)


if __name__ == "__main__":
    unittest.main()
