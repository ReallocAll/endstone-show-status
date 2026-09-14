# Endstone Show Status

[![CI](https://github.com/ReallocAll/endstone-show-status/actions/workflows/build.yml/badge.svg)](https://github.com/ReallocAll/endstone-show-status/actions/workflows/build.yml)
[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)
[English](README.md) | [简体中文](README_ZH.md)

A lightweight, read-only public status page for an
[Endstone](https://github.com/EndstoneMC/endstone) Minecraft Bedrock Dedicated
Server.

The plugin serves a small embedded web UI and JSON APIs with server health,
players, recent chat, TPS/MSPT, process/system resource usage, short history, and
optional Spark metrics. The HTTP server runs outside the BDS main thread; game
state snapshots are created on the Endstone server thread.

## Features

- Public status page with bundled HTML/CSS/JavaScript assets.
- TPS, MSPT, player count, uptime, Minecraft/Endstone/plugin versions.
- Process CPU/RSS plus host CPU, memory, disk, and network throughput.
- Optional player list and recent chat.
- Short rolling history for charts.
- Rate limiting, per-IP connection limits, bounded client tracking, and temporary
  blocking.
- Optional HTTP Basic Authentication.
- Security headers and restrictive Content Security Policy.
- Optional Spark + PlaceholderAPI integration for Spark's rolling TPS/MSPT/process
  and system CPU metrics.
- No hard dependency on PlaceholderAPI or Spark.

## Requirements

- Python 3.11+
- Endstone `>=0.12,<0.13`
- `psutil>=5`

For optional Spark metrics, install compatible builds of:

- Endstone PlaceholderAPI (`papi`)
- Spark for Endstone with the `spark` expansion

The integration uses PAPI's colon-separated namespace syntax:

```text
{spark:tps_5s}
{spark:tickduration_10s}
{spark:cpu_process_10s}
{spark:cpu_system_1m}
```

If PAPI is absent, inactive, or the `spark` expansion is not registered, the
status page continues to work and falls back to Endstone/psutil data.

## Installation

Build the wheel as described below, then copy the generated
`endstone_show_status-*.whl` file from `dist/` into the server's `plugins/`
directory and restart Endstone.

The plugin creates its configuration under the plugin data directory on first
startup.

## Building

This project is a pure-Python Endstone plugin. It does not require a C/C++
compiler; "building" packages the source and bundled web assets into a wheel.

### Windows / PowerShell

From the project root:

```powershell
python -m pip install --upgrade build
python -m build --wheel
```

The wheel is written to:

```text
dist/endstone_show_status-0.2.0-py3-none-any.whl
```

To build both a wheel and source distribution:

```powershell
python -m build
```

### Linux

From the project root:

```bash
python3 -m pip install --upgrade build
python3 -m build --wheel
```

To build both distribution formats:

```bash
python3 -m build
```

### Build without the `build` frontend

If the local environment already contains the build backend requirements, pip can
also create the wheel directly:

```bash
python -m pip wheel . --no-deps --no-build-isolation -w dist
```

## Development and tests

Install the project in editable mode:

```bash
python -m pip install -e .
```

Run the unit tests:

```bash
python -m unittest discover -s tests -v
```

For a release-style verification:

```bash
python -m pip install --upgrade build
python -m build --wheel
python -m unittest discover -s tests -v
```

## PlaceholderAPI / Spark integration

`SparkPapiClient` first loads the native `PlaceholderAPI` service and checks that
the `spark` expansion is registered. It then reads:

| Placeholder                  | Used for                                        |
| ---------------------------- | ----------------------------------------------- |
| `{spark:tps_5s}`           | 5-second TPS                                    |
| `{spark:tickduration_10s}` | 10-second MSPT distribution; the median is used |
| `{spark:cpu_process_10s}`  | 10-second Spark/BDS process CPU                 |
| `{spark:cpu_system_1m}`    | 1-minute Spark/system CPU                       |

Minecraft color codes are stripped before numeric parsing.

The plugin requires the colon-separated PAPI namespace syntax. Legacy dot- and
underscore-separated tokens such as `{spark.tps_5s}` and `{spark_tps_5s}` are not
supported.

## Configuration

The plugin creates `config.toml` in its data directory.

### HTTP

```toml
[http]
host = "0.0.0.0"
port = 0
max_connections = 64
per_ip_connections = 6
socket_timeout_seconds = 5
rate_limit_per_second = 10.0
rate_limit_burst = 40
temporary_block_seconds = 30
max_tracked_clients = 4096
allow_indexing = false
auth_username = "status"
auth_password = ""
```

`port = 0` selects the Bedrock server port plus 2. If the server port cannot be
read, the fallback is `19134`.

Leaving `auth_password` empty keeps the page public. Set both
`auth_username`/`auth_password` to enable HTTP Basic Authentication.

### Status collection

```toml
[status]
snapshot_interval_ticks = 20
tip_enabled = true
tip_interval_ticks = 20
system_interval_seconds = 2.0
history_seconds = 300
chat_entries = 100
expose_chat = true
expose_players = true
```

### UI

```toml
[ui]
server_name = "Bedrock Server"
server_address = ""
language = "zh-CN"
default_theme = "deepslate"
```

Supported languages are `zh-CN` and `en-US`. Supported themes are `deepslate`
and `grass`.

## Environment variables

The following environment variables override matching configuration values:

```text
ENDSTONE_SHOW_STATUS_HOST
ENDSTONE_SHOW_STATUS_PORT
ENDSTONE_SHOW_STATUS_MAX_CONNECTIONS
ENDSTONE_SHOW_STATUS_PER_IP_CONNECTIONS
ENDSTONE_SHOW_STATUS_SOCKET_TIMEOUT
ENDSTONE_SHOW_STATUS_RATE_LIMIT
ENDSTONE_SHOW_STATUS_RATE_BURST
ENDSTONE_SHOW_STATUS_BLOCK_SECONDS
ENDSTONE_SHOW_STATUS_USERNAME
ENDSTONE_SHOW_STATUS_PASSWORD
ENDSTONE_SHOW_STATUS_EXPOSE_CHAT
ENDSTONE_SHOW_STATUS_EXPOSE_PLAYERS
ENDSTONE_SHOW_STATUS_TIP_ENABLED
ENDSTONE_SHOW_STATUS_SERVER_NAME
ENDSTONE_SHOW_STATUS_SERVER_ADDRESS
```

## HTTP endpoints

Only `GET` and `HEAD` are accepted.

| Endpoint                | Description             |
| ----------------------- | ----------------------- |
| `/`                   | Embedded status page    |
| `/api/v1/status`      | Current JSON snapshot   |
| `/api/v1/history`     | Rolling history JSON    |
| `/data`               | Legacy status payload   |
| `/healthz`            | Plugin health probe     |
| `/robots.txt`         | Search-engine policy    |
| `/assets/app.css`     | Bundled stylesheet      |
| `/assets/app.js`      | Bundled frontend script |
| `/assets/favicon.svg` | Bundled favicon         |

## Packaging layout

The wheel exposes the Endstone entry point:

```text
show_status = endstone_show_status:ShowStatus
```

Bundled `webui/*.html`, `*.css`, `*.js`, and `*.svg` files are included as package
data.

## Security notes

The page is designed to be read-only, but public exposure still reveals whatever
you enable in the configuration. In particular, review `expose_players`,
`expose_chat`, `server_address`, and Basic Auth settings before exposing the HTTP
port to the Internet.

The built-in request guard limits global and per-IP concurrency and applies a
token-bucket rate limit. It is still reasonable to place the service behind a
reverse proxy when exposing it publicly.

## License

This project is licensed under the [GNU GPL-3.0](LICENSE).
