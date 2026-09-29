from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Final

CONTINUOUS_TIP_INTERVAL_TICKS: Final[int] = 5
DEFAULT_TIP_INTERVAL_TICKS: Final[int] = 20
TIP_INTERVAL_OPTIONS: Final[tuple[tuple[str, int | None], ...]] = (
    ("持续显示", CONTINUOUS_TIP_INTERVAL_TICKS),
    ("每 1 秒", 20),
    ("每 2 秒", 40),
    ("每 3 秒", 60),
    ("每 5 秒", 100),
    ("每 10 秒", 200),
    ("每 15 秒", 300),
    ("每 30 秒", 600),
    ("每 60 秒", 1200),
    ("不显示", None),
)
_ALLOWED_INTERVAL_TICKS: Final[frozenset[int | None]] = frozenset(
    value for _, value in TIP_INTERVAL_OPTIONS
)
_LEGACY_INTERVAL_SECONDS: Final[frozenset[int | None]] = frozenset(
    {1, 2, 3, 5, 10, 15, 30, 60, None}
)


def tip_interval_option_index(interval_ticks: int | None) -> int:
    for index, (_, value) in enumerate(TIP_INTERVAL_OPTIONS):
        if value == interval_ticks:
            return index
    if isinstance(interval_ticks, int) and not isinstance(interval_ticks, bool):
        numeric = [
            (index, value)
            for index, (_, value) in enumerate(TIP_INTERVAL_OPTIONS)
            if value is not None
        ]
        return min(numeric, key=lambda item: abs(item[1] - interval_ticks))[0]
    return 0


def _legacy_seconds_to_ticks(interval_seconds: int | None) -> int | None:
    if interval_seconds is None:
        return None
    # v0.2.3 used 1 second as the value for the "continuous" option.
    if interval_seconds == 1:
        return CONTINUOUS_TIP_INTERVAL_TICKS
    return interval_seconds * 20


class PlayerSettingsStore:
    """Persistent per-player preferences keyed by Endstone player UUID."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._tip_intervals: dict[str, int | None] = {}

    def load(self) -> str | None:
        with self._lock:
            self._tip_intervals.clear()
            if not self.path.exists():
                return None
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return f"Unable to read {self.path}: {exc}"

            if not isinstance(raw, dict):
                return f"Unable to read {self.path}: root value must be an object"

            players = raw.get("players", {})
            if not isinstance(players, dict):
                return f"Unable to read {self.path}: players must be an object"

            for player_id, values in players.items():
                if not isinstance(player_id, str) or not isinstance(values, dict):
                    continue

                if "tip_interval_ticks" in values:
                    interval = values["tip_interval_ticks"]
                    if interval is None or (
                        isinstance(interval, int)
                        and not isinstance(interval, bool)
                        and interval in _ALLOWED_INTERVAL_TICKS
                    ):
                        self._tip_intervals[player_id] = interval
                    continue

                if "tip_interval_seconds" in values:
                    legacy = values["tip_interval_seconds"]
                    if legacy is None or (
                        isinstance(legacy, int)
                        and not isinstance(legacy, bool)
                        and legacy in _LEGACY_INTERVAL_SECONDS
                    ):
                        self._tip_intervals[player_id] = _legacy_seconds_to_ticks(legacy)
            return None

    def get_tip_interval_ticks(
        self,
        player_id: str,
        default: int = DEFAULT_TIP_INTERVAL_TICKS,
    ) -> int | None:
        with self._lock:
            return self._tip_intervals.get(player_id, default)

    def set_tip_interval_ticks(self, player_id: str, interval_ticks: int | None) -> None:
        if interval_ticks is not None and (
            not isinstance(interval_ticks, int)
            or isinstance(interval_ticks, bool)
            or interval_ticks not in _ALLOWED_INTERVAL_TICKS
        ):
            raise ValueError(f"Unsupported tip interval: {interval_ticks!r}")
        with self._lock:
            self._tip_intervals[player_id] = interval_ticks
            self._write_locked()

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 2,
            "players": {
                player_id: {"tip_interval_ticks": interval}
                for player_id, interval in sorted(self._tip_intervals.items())
            },
        }
        temp_path = self.path.with_name(f"{self.path.name}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp_path, self.path)
