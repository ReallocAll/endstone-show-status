import math
import os
import threading
import time
from collections import deque
from contextlib import suppress
from importlib import metadata
from pathlib import Path
from typing import Any, ClassVar

import psutil
from endstone.event import PlayerChatEvent, event_handler
from endstone.plugin import Plugin

from .config import load_config
from .metrics import SystemMetricsCollector
from .spark_papi import SparkPapiClient
from .web import (
    CachedResponse,
    PublicStatusHTTPServer,
    StatusRequestHandler,
    json_response,
)


class ShowStatus(Plugin):
    api_version = "0.12"
    soft_depend: ClassVar[list[str]] = ["papi"]

    def on_load(self) -> None:
        self.is_running = False
        self.http_server: PublicStatusHTTPServer | None = None
        self.http_thread: threading.Thread | None = None
        self.status_task: Any | None = None
        self.tip_task: Any | None = None

        folder_value = getattr(self, "data_folder", None)
        self._data_folder_path = Path(str(folder_value)) if folder_value else Path("plugins/show_status")
        # Plugin.config is an Endstone-owned read-only property; keep typed settings private.
        self._plugin_config, self._config_path, config_error = load_config(self._data_folder_path)
        if config_error:
            self.log_warning(config_error)

        self.chat_lock = threading.Lock()
        self.chat_log: deque[dict[str, Any]] = deque(maxlen=self._plugin_config.status.chat_entries)
        self.snapshot_lock = threading.Lock()
        self.history: deque[dict[str, int | float]] = deque(
            maxlen=max(120, int(self._plugin_config.status.history_seconds * 2) + 10)
        )
        self._cache_lock = threading.Lock()
        self._revision = 0
        self._status_response = json_response(self._starting_payload(), 0)
        self._history_response = json_response({"schema_version": 1, "generated_at_ms": 0, "points": []}, 0)
        self._legacy_response = json_response({"status": "Plugin starting...", "chat": []}, 0)
        self.status_text = "Plugin starting..."
        self._last_game_metrics = {"tps": 0.0, "mspt": 0.0, "tick_usage": 0.0}

        self._last_snapshot_error_at = 0.0
        self._last_snapshot_error_text = ""
        self._process_started_at = self._get_process_start_time()
        self._minecraft_version = "--"
        self._endstone_version = self._package_version("endstone")
        self._plugin_version = self._package_version("endstone-show-status")
        self._spark_papi = SparkPapiClient()
        self.metrics_collector = SystemMetricsCollector(
            self._plugin_config.status.system_interval_seconds,
            disk_path=Path.cwd(),
        )

    @staticmethod
    def _package_version(name: str) -> str:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return "--"

    @staticmethod
    def _get_process_start_time() -> float:
        try:
            return float(psutil.Process(os.getpid()).create_time())
        except (OSError, psutil.Error):
            return time.time()

    def log_error(self, message: str) -> None:
        logger = getattr(self, "logger", None)
        log = getattr(logger, "error", None)
        if callable(log):
            log(message)

    def log_warning(self, message: str) -> None:
        logger = getattr(self, "logger", None)
        log = getattr(logger, "warning", None)
        if callable(log):
            log(message)

    def log_info(self, message: str) -> None:
        logger = getattr(self, "logger", None)
        log = getattr(logger, "info", None)
        if callable(log):
            log(message)

    def on_enable(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        self._minecraft_version = self._detect_minecraft_version()
        self.metrics_collector.start()
        self.register_events(self)

        self.status_task = self.server.scheduler.run_task(
            self,
            self.update_status,
            delay=0,
            period=self._plugin_config.status.snapshot_interval_ticks,
        )
        if self._plugin_config.status.tip_enabled:
            self.tip_task = self.server.scheduler.run_task(
                self,
                self.send_player_tips,
                delay=self._plugin_config.status.snapshot_interval_ticks,
                period=self._plugin_config.status.tip_interval_ticks,
            )

        http = self._plugin_config.http
        default_port = self._default_http_port()
        port = http.port or default_port
        try:
            server = PublicStatusHTTPServer(
                (http.host, port),
                StatusRequestHandler,
                plugin=self,
                max_connections=http.max_connections,
                per_ip_connections=http.per_ip_connections,
                socket_timeout=float(http.socket_timeout_seconds),
                rate_limit_per_second=http.rate_limit_per_second,
                rate_limit_burst=http.rate_limit_burst,
                temporary_block_seconds=http.temporary_block_seconds,
                max_tracked_clients=http.max_tracked_clients,
                allow_indexing=http.allow_indexing,
                auth_username=http.auth_username,
                auth_password=http.auth_password,
            )
        except OSError as exc:
            self.log_error(
                f"Unable to start public status page on {http.host}:{port}: "
                f"[{exc.errno}] {exc.strerror or exc}"
            )
            return

        self.http_server = server
        self.http_thread = threading.Thread(
            target=self._run_http_server,
            args=(server,),
            name="show-status-http",
            daemon=True,
        )
        self.http_thread.start()
        self.log_info(
            f"Public player status page listening on {http.host}:{port}; "
            f"configuration: {self._config_path}"
        )

    def _default_http_port(self) -> int:
        try:
            port = int(self.server.port) + 2
        except (AttributeError, TypeError, ValueError):
            port = 19134
        return port if 1 <= port <= 65535 else 19134

    def _run_http_server(self, http_server: PublicStatusHTTPServer) -> None:
        try:
            http_server.serve_forever(poll_interval=0.25)
        except Exception:
            if not http_server.stopping.is_set():
                http_server.report_current_exception("Public status HTTP server stopped unexpectedly")

    def _detect_minecraft_version(self) -> str:
        for name in ("minecraft_version", "version", "full_version"):
            value = getattr(self.server, name, None)
            if value is not None:
                text = self._sanitize_line(str(value), 80)
                if text:
                    return text
        return "--"

    @event_handler
    def on_player_chat(self, event: PlayerChatEvent) -> None:
        if not self._plugin_config.status.expose_chat or self._plugin_config.status.chat_entries <= 0:
            return
        entry = {
            "time_ms": int(time.time() * 1000),
            "player": self._sanitize_line(str(event.player.name), 64),
            "message": self._sanitize_line(str(event.message), 512),
        }
        with self.chat_lock:
            self.chat_log.append(entry)

    @staticmethod
    def _sanitize_line(value: str, limit: int) -> str:
        value = value.replace("\r", " ").replace("\n", " ")
        value = "".join(ch for ch in value if ch >= " " or ch == "\t")
        return value[:limit]

    @staticmethod
    def _number(value: Any, default: float = 0.0) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return default
        return result if math.isfinite(result) else default

    @staticmethod
    def _integer(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return default

    @staticmethod
    def _health(tps: float, mspt: float) -> str:
        if tps >= 19.5 and mspt <= 40.0:
            return "smooth"
        if tps >= 18.0 and mspt <= 50.0:
            return "busy"
        return "lagging"

    def update_status(self) -> None:
        """Create a public, immutable snapshot on the Endstone main thread."""
        if not self.is_running:
            return
        try:
            spark_metrics = self._spark_papi.read(self.server)
            tps = self._number(self.server.average_tps)
            tick_usage = max(0.0, self._number(self.server.average_tick_usage))
            mspt = max(0.0, self._number(self.server.average_mspt))
            if spark_metrics.tps_5s is not None:
                tps = spark_metrics.tps_5s
            if spark_metrics.mspt_10s_median is not None:
                mspt = spark_metrics.mspt_10s_median
            health = self._health(tps, mspt)

            players: list[dict[str, Any]] = []
            online_players = list(self.server.online_players)
            if self._plugin_config.status.expose_players:
                for player in online_players:
                    players.append(
                        {
                            "name": self._sanitize_line(str(player.name), 64),
                            "ping": max(0, min(9999, self._integer(getattr(player, "ping", 0)))),
                        }
                    )
                players.sort(key=lambda row: str(row["name"]).casefold())

            system_snapshot = self.metrics_collector.get_snapshot().to_dict()
            if spark_metrics.system_cpu_1m_percent is not None:
                system_snapshot["cpu_average_percent"] = spark_metrics.system_cpu_1m_percent
            now_ms = int(time.time() * 1000)
            uptime_seconds = max(0, int(time.time() - self._process_started_at))
            max_players = self._get_max_players()
            with self.chat_lock:
                chat = list(self.chat_log) if self._plugin_config.status.expose_chat else []

            guard_stats = self.http_server.guard.snapshot() if self.http_server else {
                "accepted_requests": 0,
                "rejected_requests": 0,
                "temporary_blocks": 0,
                "active_requests": 0,
                "tracked_clients": 0,
            }

            server_payload = {
                "online": True,
                "health": health,
                "tps": round(tps, 3),
                "mspt": round(mspt, 3),
                "tick_usage": round(tick_usage, 4),
                "players_online": len(online_players),
                "players_max": max_players,
                "uptime_seconds": uptime_seconds,
                "minecraft_version": self._minecraft_version,
                "endstone_version": self._endstone_version,
                "plugin_version": self._plugin_version,
            }
            process_cpu = self._number(system_snapshot.pop("process_cpu_percent", 0.0))
            logical_cpu_count = max(1, self._integer(system_snapshot.get("logical_cpu_count", 1), 1))
            host_share_percent = round(process_cpu / logical_cpu_count, 3)
            if spark_metrics.process_cpu_10s_percent is not None:
                host_share_percent = spark_metrics.process_cpu_10s_percent
            process_payload = {
                "cpu_percent": process_cpu,
                "host_share_percent": host_share_percent,
                "rss_bytes": system_snapshot.pop("process_rss_bytes", 0),
                "sampled_at_ms": system_snapshot.get("sampled_at_ms", 0),
            }
            payload = {
                "schema_version": 1,
                "generated_at_ms": now_ms,
                "stale_after_ms": max(5000, self._plugin_config.status.snapshot_interval_ticks * 200),
                "server": server_payload,
                "process": process_payload,
                "system": system_snapshot,
                "spark": spark_metrics.to_dict(),
                "players": players,
                "chat": chat,
                "features": {
                    "players": self._plugin_config.status.expose_players,
                    "chat": self._plugin_config.status.expose_chat,
                    "history": True,
                    "spark_papi": spark_metrics.available,
                },
                "ui": {
                    "server_name": self._plugin_config.ui.server_name,
                    "server_address": self._plugin_config.ui.server_address,
                    "language": self._plugin_config.ui.language,
                    "default_theme": self._plugin_config.ui.default_theme,
                },
                "web": guard_stats,
            }

            point = {
                "time_ms": now_ms,
                "tps": round(tps, 3),
                "mspt": round(mspt, 3),
                "players": len(online_players),
                "process_cpu_percent": self._number(process_payload["cpu_percent"]),
                "process_cpu_total_percent": self._number(process_payload["host_share_percent"]),
                "process_rss_bytes": self._integer(process_payload["rss_bytes"]),
                "memory_percent": self._number(system_snapshot.get("memory_percent", 0.0)),
            }
            cutoff = now_ms - self._plugin_config.status.history_seconds * 1000
            with self.snapshot_lock:
                self._last_game_metrics = {"tps": tps, "mspt": mspt, "tick_usage": tick_usage}
                self.history.append(point)
                while self.history and int(self.history[0]["time_ms"]) < cutoff:
                    self.history.popleft()
                history_points = list(self.history)

            legacy_text = self._legacy_status_text(payload)
            legacy_chat = [f"<{item['player']}> {item['message']}" for item in chat]
            self.status_text = legacy_text
            self._revision += 1
            with self._cache_lock:
                self._status_response = json_response(payload, self._revision)
                self._history_response = json_response(
                    {
                        "schema_version": 1,
                        "generated_at_ms": now_ms,
                        "history_seconds": self._plugin_config.status.history_seconds,
                        "points": history_points,
                    },
                    self._revision,
                )
                self._legacy_response = json_response(
                    {"status": legacy_text, "chat": legacy_chat},
                    self._revision,
                )
        except Exception as exc:
            self._report_snapshot_error(exc)

    def _get_max_players(self) -> int:
        for name in ("max_players", "player_limit"):
            value = getattr(self.server, name, None)
            if value is not None:
                return max(0, self._integer(value))
        return 0

    def _legacy_status_text(self, payload: dict[str, Any]) -> str:
        server = payload["server"]
        process = payload["process"]
        system = payload["system"]
        lines = [
            f"State: {server['health']}",
            f"TPS: {server['tps']:.1f} ({server['tick_usage'] * 100:.1f}%) | MSPT: {server['mspt']:.1f}",
            f"CPU: BDS {process['cpu_percent']:.1f}% | System Avg/Max Core "
            f"{self._number(system.get('cpu_average_percent')):.1f}%/{self._number(system.get('cpu_max_core_percent')):.1f}%",
            f"Memory: BDS RSS {self._integer(process['rss_bytes']) / 1024**3:.1f} GB | System "
            f"{self._integer(system.get('memory_used_bytes')) / 1024**3:.1f}/"
            f"{self._integer(system.get('memory_total_bytes')) / 1024**3:.1f} GB",
            f"Players ({server['players_online']}):",
        ]
        lines.extend(f"- {item['name']}: {item['ping']}ms" for item in payload["players"])
        return "\n".join(lines)

    def send_player_tips(self) -> None:
        if not self.is_running or not self._plugin_config.status.tip_enabled:
            return
        try:
            with self.snapshot_lock:
                metrics = dict(self._last_game_metrics)
            tps = self._number(metrics.get("tps"))
            mspt = self._number(metrics.get("mspt"))
            tps_color = "§a" if tps >= 19.5 else "§e" if tps >= 18.0 else "§c"
            mspt_color = "§a" if mspt <= 40.0 else "§e" if mspt <= 50.0 else "§c"
            base = f"§fTPS {tps_color}{tps:.1f} §8| §fMSPT {mspt_color}{mspt:.1f}ms"
            for player in list(self.server.online_players):
                try:
                    ping = max(0, min(9999, self._integer(getattr(player, "ping", 0))))
                    ping_color = "§a" if ping < 100 else "§e" if ping < 180 else "§c"
                    player.send_tip(f"{base} §8| §fPING {ping_color}{ping}ms")
                except Exception:
                    # Disconnecting between enumeration and send_tip is normal.
                    continue
        except Exception as exc:
            self._report_snapshot_error(exc)

    def _report_snapshot_error(self, exc: Exception) -> None:
        now = time.monotonic()
        text = f"{type(exc).__name__}: {exc}"
        if text == self._last_snapshot_error_text and now - self._last_snapshot_error_at < 60.0:
            return
        self._last_snapshot_error_text = text
        self._last_snapshot_error_at = now
        self.log_error(f"Failed to update public status snapshot: {text}")

    def _starting_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "generated_at_ms": 0,
            "stale_after_ms": 5000,
            "server": {
                "online": False,
                "health": "offline",
                "tps": 0.0,
                "mspt": 0.0,
                "tick_usage": 0.0,
                "players_online": 0,
                "players_max": 0,
                "uptime_seconds": 0,
                "minecraft_version": "--",
                "endstone_version": self._package_version("endstone"),
                "plugin_version": self._package_version("endstone-show-status"),
            },
            "process": {"cpu_percent": 0.0, "host_share_percent": 0.0, "rss_bytes": 0, "sampled_at_ms": 0},
            "system": {},
            "spark": {
                "available": False,
                "tps_5s": None,
                "mspt_10s_median": None,
                "process_cpu_10s_percent": None,
                "system_cpu_1m_percent": None,
            },
            "players": [],
            "chat": [],
            "features": {"players": True, "chat": True, "history": True, "spark_papi": False},
            "ui": {
                "server_name": self._plugin_config.ui.server_name,
                "server_address": self._plugin_config.ui.server_address,
                "language": self._plugin_config.ui.language,
                "default_theme": self._plugin_config.ui.default_theme,
            },
            "web": {},
        }

    def get_cached_status_response(self) -> CachedResponse:
        with self._cache_lock:
            return self._status_response

    def get_cached_history_response(self) -> CachedResponse:
        with self._cache_lock:
            return self._history_response

    def get_cached_legacy_response(self) -> CachedResponse:
        with self._cache_lock:
            return self._legacy_response

    def get_web_payload(self) -> dict[str, Any]:
        """Compatibility helper for integrations that called the old method directly."""
        import json
        return json.loads(self.get_cached_legacy_response().body)

    def on_disable(self) -> None:
        self.is_running = False
        self._spark_papi.close()
        for name in ("status_task", "tip_task"):
            task = getattr(self, name, None)
            setattr(self, name, None)
            if task is not None and hasattr(task, "cancel"):
                with suppress(Exception):
                    task.cancel()

        if not self.metrics_collector.stop(timeout=3.0):
            self.log_warning("System metrics thread did not stop within 3 seconds")

        http_server = self.http_server
        http_thread = self.http_thread
        self.http_server = None
        self.http_thread = None
        if http_server is not None:
            http_server.stopping.set()
            if http_thread is not None and http_thread.is_alive():
                with suppress(Exception):
                    http_server.shutdown()
            if http_thread is not None:
                http_thread.join(timeout=3.0)
                if http_thread.is_alive():
                    self.log_warning("Status HTTP thread did not stop within 3 seconds")
            with suppress(Exception):
                http_server.server_close()
