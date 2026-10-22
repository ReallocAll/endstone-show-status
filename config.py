from __future__ import annotations

import os
import math
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, TypeVar

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]


@dataclass(slots=True)
class HTTPConfig:
    host: str = "0.0.0.0"
    port: int = 0
    max_connections: int = 64
    per_ip_connections: int = 6
    socket_timeout_seconds: int = 5
    rate_limit_per_second: float = 10.0
    rate_limit_burst: int = 40
    temporary_block_seconds: int = 30
    max_tracked_clients: int = 4096
    allow_indexing: bool = False
    auth_username: str = "status"
    auth_password: str = ""


@dataclass(slots=True)
class StatusConfig:
    snapshot_interval_ticks: int = 20
    tip_enabled: bool = True
    tip_interval_ticks: int = 0
    system_interval_seconds: float = 2.0
    history_seconds: int = 300
    chat_entries: int = 100
    expose_chat: bool = True
    expose_players: bool = True


@dataclass(slots=True)
class UIConfig:
    server_name: str = "Bedrock Server"
    server_address: str = ""
    language: str = "zh-CN"
    default_theme: str = "deepslate"


@dataclass(slots=True)
class PluginConfig:
    http: HTTPConfig
    status: StatusConfig
    ui: UIConfig


_DEFAULT_CONFIG = """# Endstone Show Status
# This page is intentionally public and read-only. Abuse controls below protect it
# without requiring players to log in.

[http]
host = "0.0.0.0"
# 0 means Bedrock server port + 2.
port = 0
max_connections = 64
per_ip_connections = 6
socket_timeout_seconds = 5
rate_limit_per_second = 10.0
rate_limit_burst = 40
temporary_block_seconds = 30
max_tracked_clients = 4096
# Keep false unless you explicitly want search engines to index the page.
allow_indexing = false
# Empty keeps the entire page public. These fields preserve the optional 0.1.x Basic Auth behavior.
auth_username = "status"
auth_password = ""

[status]
snapshot_interval_ticks = 20
tip_enabled = true
# Default for players without a personal preference: 0 disables display; positive values are tick intervals.
tip_interval_ticks = 0
system_interval_seconds = 2.0
history_seconds = 300
chat_entries = 100
expose_chat = true
expose_players = true

[ui]
server_name = "Bedrock Server"
# Example: play.example.com:19132. Empty hides the copy button.
server_address = ""
language = "zh-CN"
# deepslate or grass
default_theme = "deepslate"
"""

T = TypeVar("T")


def _coerce(value: Any, current: T) -> T:
    if isinstance(current, bool):
        if isinstance(value, bool):
            return value  # type: ignore[return-value]
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True  # type: ignore[return-value]
            if normalized in {"0", "false", "no", "off"}:
                return False  # type: ignore[return-value]
        raise ValueError("Expected a boolean")
    if isinstance(current, int) and not isinstance(current, bool):
        return int(value)  # type: ignore[return-value]
    if isinstance(current, float):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Expected a finite number")
        return result  # type: ignore[return-value]
    return str(value)  # type: ignore[return-value]


def _apply_section(instance: T, values: dict[str, Any]) -> T:
    if not isinstance(values, dict):
        raise ValueError("Configuration section must be a table")
    for item in fields(instance):
        if item.name not in values:
            continue
        current = getattr(instance, item.name)
        value = values[item.name]
        if type(value) is not type(current) and not (type(current) is float and type(value) is int):
            raise ValueError(f"Invalid type for configuration field {item.name}")
        setattr(instance, item.name, _coerce(value, current))
    return instance


def _env(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value is not None else None


def _apply_environment(config: PluginConfig) -> None:
    mapping: tuple[tuple[str, object, str], ...] = (
        ("ENDSTONE_SHOW_STATUS_HOST", config.http, "host"),
        ("ENDSTONE_SHOW_STATUS_PORT", config.http, "port"),
        ("ENDSTONE_SHOW_STATUS_MAX_CONNECTIONS", config.http, "max_connections"),
        ("ENDSTONE_SHOW_STATUS_PER_IP_CONNECTIONS", config.http, "per_ip_connections"),
        ("ENDSTONE_SHOW_STATUS_SOCKET_TIMEOUT", config.http, "socket_timeout_seconds"),
        ("ENDSTONE_SHOW_STATUS_RATE_LIMIT", config.http, "rate_limit_per_second"),
        ("ENDSTONE_SHOW_STATUS_RATE_BURST", config.http, "rate_limit_burst"),
        ("ENDSTONE_SHOW_STATUS_BLOCK_SECONDS", config.http, "temporary_block_seconds"),
        ("ENDSTONE_SHOW_STATUS_USERNAME", config.http, "auth_username"),
        ("ENDSTONE_SHOW_STATUS_PASSWORD", config.http, "auth_password"),
        ("ENDSTONE_SHOW_STATUS_EXPOSE_CHAT", config.status, "expose_chat"),
        ("ENDSTONE_SHOW_STATUS_EXPOSE_PLAYERS", config.status, "expose_players"),
        ("ENDSTONE_SHOW_STATUS_TIP_ENABLED", config.status, "tip_enabled"),
        ("ENDSTONE_SHOW_STATUS_SERVER_NAME", config.ui, "server_name"),
        ("ENDSTONE_SHOW_STATUS_SERVER_ADDRESS", config.ui, "server_address"),
    )
    for env_name, target, attr in mapping:
        raw = _env(env_name)
        if raw is None:
            continue
        try:
            setattr(target, attr, _coerce(raw, getattr(target, attr)))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Invalid environment setting {env_name}") from exc


def _clamp(config: PluginConfig) -> None:
    http = config.http
    status = config.status
    http.port = min(65535, max(0, http.port))
    http.max_connections = min(512, max(4, http.max_connections))
    http.per_ip_connections = min(64, max(1, http.per_ip_connections))
    http.socket_timeout_seconds = min(30, max(2, http.socket_timeout_seconds))
    http.rate_limit_per_second = min(100.0, max(1.0, http.rate_limit_per_second))
    http.rate_limit_burst = min(500, max(5, http.rate_limit_burst))
    http.temporary_block_seconds = min(3600, max(5, http.temporary_block_seconds))
    http.max_tracked_clients = min(65536, max(128, http.max_tracked_clients))
    http.auth_username = http.auth_username[:128] or "status"
    http.auth_password = http.auth_password[:1024]

    status.snapshot_interval_ticks = min(200, max(10, status.snapshot_interval_ticks))
    if status.tip_interval_ticks != 0:
        status.tip_interval_ticks = min(400, max(10, status.tip_interval_ticks))
    status.system_interval_seconds = min(30.0, max(1.0, status.system_interval_seconds))
    status.history_seconds = min(3600, max(60, status.history_seconds))
    status.chat_entries = min(500, max(0, status.chat_entries))

    config.ui.language = config.ui.language if config.ui.language in {"zh-CN", "en-US"} else "zh-CN"
    config.ui.default_theme = config.ui.default_theme if config.ui.default_theme in {"deepslate", "grass"} else "deepslate"
    config.ui.server_name = config.ui.server_name[:80] or "Bedrock Server"
    config.ui.server_address = config.ui.server_address[:160]


def load_config(data_folder: Path) -> tuple[PluginConfig, Path, str | None]:
    path = data_folder / "config.toml"
    error: str | None = None
    try:
        data_folder.mkdir(parents=True, exist_ok=True)
        if not os.path.lexists(path):
            path.write_text(_DEFAULT_CONFIG, encoding="utf-8")
    except OSError as exc:
        error = f"Unable to create {path}: {exc}"

    raw: dict[str, Any] = {}
    if os.path.lexists(path):
        try:
            with path.open("rb") as stream:
                raw = tomllib.load(stream)
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
            error = f"Unable to read {path}: {exc}"

    # A missing optional field may use its documented default. An unreadable or
    # malformed existing document must never activate a public default listener.
    config = PluginConfig(HTTPConfig(), StatusConfig(), UIConfig())
    if error is None:
        try:
            config = PluginConfig(
                http=_apply_section(HTTPConfig(), raw.get("http", {})),
                status=_apply_section(StatusConfig(), raw.get("status", {})),
                ui=_apply_section(UIConfig(), raw.get("ui", {})),
            )
            _apply_environment(config)
            _clamp(config)
        except (TypeError, ValueError, OverflowError) as exc:
            error = f"Invalid configuration in {path}: {exc}"
            config = PluginConfig(HTTPConfig(), StatusConfig(), UIConfig())
    return config, path, error
