from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

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


class SparkPapiClientTest(unittest.TestCase):
    def setUp(self) -> None:
        module = types.ModuleType("endstone_papi")
        module.PlaceholderAPI = FakePlaceholderAPI
        self.module_patch = mock.patch.dict(sys.modules, {"endstone_papi": module})
        self.module_patch.start()

    def tearDown(self) -> None:
        self.module_patch.stop()

    def test_reads_real_public_placeholder_results(self) -> None:
        service = FakePlaceholderAPI(
            {
                "{spark.tps_5s}": "§a*20.0",
                "{spark.tickduration_10s}": "§a1.2§7/§a2.3§7/§e40.0§7/§c55.0",
                "{spark.cpu_process_10s}": "§e67%",
            }
        )
        server = FakeServer(service)

        metrics = SparkPapiClient().read(server)

        self.assertTrue(metrics.available)
        self.assertEqual(metrics.tps_5s, 20.0)
        self.assertEqual(metrics.mspt_10s_median, 2.3)
        self.assertEqual(metrics.process_cpu_10s_percent, 67.0)
        self.assertEqual(
            service.requests,
            [
                (None, "{spark.tps_5s}"),
                (None, "{spark.tickduration_10s}"),
                (None, "{spark.cpu_process_10s}"),
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

    def test_reloads_after_retained_service_becomes_inactive(self) -> None:
        old = FakePlaceholderAPI({"{spark.tps_5s}": "§a19.9"})
        server = FakeServer(old)
        client = SparkPapiClient()
        self.assertEqual(client.read(server).tps_5s, 19.9)

        old.active = False
        replacement = FakePlaceholderAPI({"{spark.tps_5s}": "§a18.5"})
        server.service_manager.service = replacement
        self.assertEqual(client.read(server).tps_5s, 18.5)
        self.assertGreaterEqual(server.service_manager.loads, 2)

        client.close()
        self.assertIsNone(client._service)


if __name__ == "__main__":
    unittest.main()
