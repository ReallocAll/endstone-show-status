from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Final

DEFAULT_TIP_INTERVAL_SECONDS: Final[int] = 1
TIP_INTERVAL_OPTIONS: Final[tuple[tuple[str, int | None], ...]] = (
    ("持续显示", 1),
    ("每 2 秒", 2),
    ("每 3 秒", 3),
    ("每 5 秒", 5),
    ("每 10 秒", 10),
    ("每 15 秒", 15),
    ("每 30 秒", 30),
    ("每 60 秒", 60),
    ("不显示", None),
)
_ALLOWED_INTERVALS: Final[frozenset[int | None]] = frozenset(value for _, value in TIP_INTERVAL_OPTIONS)


def tip_interval_option_index(interval: int | None) -> int:
    for index, (_, value) in enumerate(TIP_INTERVAL_OPTIONS):
        if value == interval:
            return index
    if isinstance(interval, int) and not isinstance(interval, bool):
        numeric = [
            (index, value)
            for index, (_, value) in enumerate(TIP_INTERVAL_OPTIONS)
            if value is not None
        ]
        return min(numeric, key=lambda item: abs(item[1] - interval))[0]
    return 0


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
                if "tip_interval_seconds" not in values:
                    continue
                interval = values["tip_interval_seconds"]
                if interval is None or (
                    isinstance(interval, int)
                    and not isinstance(interval, bool)
                    and interval in _ALLOWED_INTERVALS
                ):
                    self._tip_intervals[player_id] = interval
            return None

    def get_tip_interval(self, player_id: str, default: int = DEFAULT_TIP_INTERVAL_SECONDS) -> int | None:
        with self._lock:
            return self._tip_intervals.get(player_id, default)

    def set_tip_interval(self, player_id: str, interval: int | None) -> None:
        if interval is not None and (
            not isinstance(interval, int)
            or isinstance(interval, bool)
            or interval not in _ALLOWED_INTERVALS
        ):
            raise ValueError(f"Unsupported tip interval: {interval!r}")
        with self._lock:
            self._tip_intervals[player_id] = interval
            self._write_locked()

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "players": {
                player_id: {"tip_interval_seconds": interval}
                for player_id, interval in sorted(self._tip_intervals.items())
            },
        }
        temp_path = self.path.with_name(f"{self.path.name}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp_path, self.path)
