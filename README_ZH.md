# Endstone Show Status

[English](README.md) · [独立状态 API](https://github.com/ReallocAll/endstone-status-api)

Endstone 游戏内 TPS、MSPT、PING HUD 插件。**0.3.0 起不再提供 HTTP、网页、聊天采集或 psutil 系统监控**；如需公开 JSON API，请独立安装 `endstone-status-api`。

## 安装和使用

要求 Python 3.10+、Endstone 0.11+。将发布的 wheel 安装至 Endstone 使用的 Python 环境，重启后玩家使用 `/showstatus` 调整显示频率，支持每 5 tick 持续显示、1～60 秒间隔或关闭。

配置位于 `plugins/show_status/hud.toml`：

```toml
[hud]
tip_enabled = true
default_interval_ticks = 0
```

`tip_enabled` 为全局开关，`default_interval_ticks=0` 表示未保存个人偏好的玩家默认不显示。正数支持 5～1200 ticks。

## 从 0.2.x 升级

玩家原有 `player_settings.json` 继续使用，不会被覆盖。旧版 `config.toml` 不再读取，请将 HUD 全局配置改写到 `hud.toml`。原 HTTP/API 和静态网页已移除，旧版 API 不提供兼容。需要公共接口请安装独立的 `endstone-status-api`。避免让两个旧/新 HTTP 服务竞争同一端口。

## 测试

`python -m unittest discover -s tests -v`

许可证：GPL-3.0-only。
