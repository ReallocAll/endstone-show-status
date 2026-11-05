from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


@dataclass(frozen=True, slots=True)
class HUDConfig:
    tip_enabled: bool = True
    default_interval_ticks: int = 0


_DEFAULT = """# Endstone Show Status: in-game HUD only
[hud]
tip_enabled = true
# 0: off for players without saved preferences; positive: tick interval.
default_interval_ticks = 0
"""


def load_config(folder: Path) -> tuple[HUDConfig, str | None]:
    path = folder / "hud.toml"
    if not path.exists():
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path.write_text(_DEFAULT, encoding="utf-8")
        except OSError as exc:
            return HUDConfig(), f"Unable to create HUD configuration: {exc}"

    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        if set(data) != {"hud"} or not isinstance(data["hud"], dict):
            raise ValueError("expected a single [hud] table")
        values = data["hud"]
        if unknown := set(values) - {"tip_enabled", "default_interval_ticks"}:
            raise ValueError(f"unknown HUD settings: {', '.join(sorted(unknown))}")
        enabled = values.get("tip_enabled", True)
        ticks = values.get("default_interval_ticks", 0)
        if type(enabled) is not bool or type(ticks) is not int:
            raise ValueError("tip_enabled must be boolean and default_interval_ticks must be integer")
        if ticks != 0 and not 5 <= ticks <= 1200:
            raise ValueError("default_interval_ticks must be 0 or between 5 and 1200")
        return HUDConfig(enabled, ticks), None
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        return HUDConfig(), f"Invalid {path}: {exc}"
