# Endstone Show Status

[简体中文](README_ZH.md) · [Status API](https://github.com/ReallocAll/endstone-status-api)

A minimal **in-game** TPS / MSPT / PING HUD for Endstone (Minecraft Bedrock Dedicated Server).

The HUD and the public HTTP API are two independent plugins. Since v0.3.0 this plugin contains **no HTTP server, web UI, chat collector, or psutil dependency**. Install [endstone-status-api](https://github.com/ReallocAll/endstone-status-api) separately if you need a public JSON API.

## Installation

Requires Python 3.10+ and Endstone 0.11+. Install the published wheel into the same Python environment as Endstone, then restart Endstone:

```bash
python -m pip install endstone_show_status-0.3.0-py3-none-any.whl
```

Run `/showstatus` in game to configure the display interval from continuous (5 ticks) through 60 seconds to off. Choices persist per player UUID.

## Configuration

The plugin creates `plugins/show_status/hud.toml`:

```toml
[hud]
tip_enabled = true
default_interval_ticks = 0
```

`tip_enabled` is a global switch. A zero default hides HUD for players without a saved setting; nonzero values from 5 through 1200 set the fallback display interval in ticks.

**Migration from 0.2.x:** The old web server and JSON API are removed. Existing `player_settings.json` is retained in place, including previously saved HUD intervals. Configure global HUD defaults in the new `hud.toml`; the old `config.toml` is left untouched, not used by this plugin. For public status endpoints install the independent API plugin. Do not run both the old HTTP plugin and the new API on the same port.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m build --wheel
```

## License

GPL-3.0-only.
