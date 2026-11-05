from __future__ import annotations

import json
import math
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, ClassVar

from endstone import Player
from endstone.command import Command, CommandSender
from endstone.form import ModalForm, StepSlider
from endstone.plugin import Plugin

from .config import load_config
from .player_settings import PlayerSettingsStore, TIP_INTERVAL_OPTIONS, tip_interval_option_index


def _metric(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, number) if math.isfinite(number) else 0.0


class ShowStatus(Plugin):
    api_version = "0.11"
    commands: ClassVar[dict[str, dict[str, Any]]] = {
        "showstatus": {
            "description": "Configure the in-game TPS/MSPT/PING HUD.",
            "usages": ["/showstatus"],
            "permissions": ["show_status.command.settings"],
        }
    }
    permissions: ClassVar[dict[str, dict[str, Any]]] = {
        "show_status.command.settings": {
            "description": "Allow players to configure their HUD.",
            "default": True,
        }
    }

    def on_load(self) -> None:
        folder = Path(str(self.data_folder)) if self.data_folder else Path("plugins/show_status")
        self._config, self._config_error = load_config(folder)
        self._player_settings = PlayerSettingsStore(folder / "player_settings.json")
        self._settings_error = self._player_settings.load()
        self._task: Any | None = None
        self._next_tip_send: dict[str, float] = {}

    def on_enable(self) -> None:
        if self._config_error:
            self.logger.error(self._config_error)
            return
        if self._settings_error:
            self.logger.error(self._settings_error + "; HUD disabled to preserve existing preferences")
            return
        if self._config.tip_enabled and self._task is None:
            self._task = self.server.scheduler.run_task(self, self.send_player_tips, delay=5, period=5)

    def on_disable(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            with suppress(Exception):
                task.cancel()
        self._next_tip_send.clear()

    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        if command.name != "showstatus":
            return False
        if not isinstance(sender, Player):
            sender.send_message("This command can only be used by a player.")
            return True
        self.open_tip_settings(sender)
        return True

    def open_tip_settings(self, player: Player) -> None:
        interval = self._player_settings.get_tip_interval_ticks(
            str(player.unique_id), default=self._default_interval()
        )
        player.send_form(ModalForm(
            title="状态显示设置",
            controls=[StepSlider(
                label="TPS / MSPT / PING 显示频率",
                options=[label for label, _ in TIP_INTERVAL_OPTIONS],
                default_index=tip_interval_option_index(interval),
            )],
            submit_button="保存",
            on_submit=self._save_tip_settings,
        ))

    def _default_interval(self) -> int | None:
        return self._config.default_interval_ticks or None

    def _save_tip_settings(self, player: Player, data: Any) -> None:
        try:
            values = json.loads(data) if isinstance(data, str) else data
            if not isinstance(values, (tuple, list)) or len(values) != 1:
                raise ValueError("invalid form values")
            index = values[0]
            if type(index) is not int:
                raise ValueError("invalid slider index")
            label, interval = TIP_INTERVAL_OPTIONS[index]
            if index < 0:
                raise ValueError("invalid slider index")
        except (ValueError, TypeError, IndexError, json.JSONDecodeError):
            player.send_error_message("无法读取状态显示设置，请重试。")
            return
        try:
            player_id = str(player.unique_id)
            self._player_settings.set_tip_interval_ticks(player_id, interval)
        except (OSError, ValueError) as exc:
            self.logger.error(f"Unable to save HUD preference: {exc}")
            player.send_error_message("状态显示设置保存失败，请联系管理员。")
            return

        self._next_tip_send.pop(player_id, None)
        player.send_message("§a状态显示已关闭。" if interval is None else f"§a状态显示频率已设置为：§f{label}")
        if interval is not None and self._config.tip_enabled:
            with suppress(Exception):
                self._send_tip(player, self._base_text())
                self._next_tip_send[player_id] = time.monotonic() + interval / 20.0

    def _base_text(self) -> str:
        tps = _metric(self.server.average_tps)
        mspt = _metric(self.server.average_mspt)
        tps_color = "§a" if tps >= 19.5 else "§e" if tps >= 18.0 else "§c"
        mspt_color = "§a" if mspt <= 40 else "§e" if mspt <= 50 else "§c"
        return f"§fTPS {tps_color}{tps:.1f} §8| §fMSPT {mspt_color}{mspt:.1f}ms"

    @staticmethod
    def _send_tip(player: Player, base: str) -> None:
        ping = max(0, min(9999, int(getattr(player, "ping", 0))))
        color = "§a" if ping < 100 else "§e" if ping < 180 else "§c"
        player.send_tip(f"{base} §8| §fPING {color}{ping}ms")

    def send_player_tips(self) -> None:
        now = time.monotonic()
        active: set[str] = set()
        base: str | None = None
        for player in list(self.server.online_players):
            player_id = str(player.unique_id)
            active.add(player_id)
            interval = self._player_settings.get_tip_interval_ticks(player_id, self._default_interval())
            if interval is None:
                self._next_tip_send.pop(player_id, None)
                continue
            if now < self._next_tip_send.get(player_id, 0.0):
                continue
            try:
                if base is None:
                    base = self._base_text()
                self._send_tip(player, base)
                self._next_tip_send[player_id] = now + interval / 20.0
            except (AttributeError, RuntimeError, OSError, TypeError, ValueError):
                # A player may disconnect between enumeration and send_tip.
                continue

        for player_id in self._next_tip_send.keys() - active:
            self._next_tip_send.pop(player_id, None)
