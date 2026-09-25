# Endstone Show Status

[![CI](https://github.com/ReallocAll/endstone-show-status/actions/workflows/build.yml/badge.svg)](https://github.com/ReallocAll/endstone-show-status/actions/workflows/build.yml)
[![许可证](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)
[English](README.md) | [简体中文](README_ZH.md)

这是一个面向 [Endstone](https://github.com/EndstoneMC/endstone) Minecraft
基岩版专用服务器的轻量、只读公共状态页面。

插件提供内置网页界面和 JSON API，可显示服务器健康状态、在线玩家、近期聊天、TPS/MSPT、进程和系统资源用量、短期历史数据以及可选的 Spark 指标。HTTP
服务器在 BDS 主线程之外运行；游戏状态快照在 Endstone 服务器线程上创建。

## 功能

- 提供内置 HTML/CSS/JavaScript 资源的公共状态页面。
- 显示 TPS、MSPT、在线人数、运行时间、Minecraft/Endstone/插件版本。
- 显示进程 CPU/RSS，以及主机 CPU、内存、磁盘和网络吞吐量。
- 可选显示在线玩家列表和近期聊天。
- 提供用于图表的短期滚动历史数据。
- 限流、每 IP 连接数限制、有上限的客户端跟踪和临时封禁。
- 可选 HTTP Basic Authentication。
- 安全响应头和限制性内容安全策略（CSP）。
- 可选集成 Spark + PlaceholderAPI，读取 Spark 的滚动 TPS/MSPT、进程 CPU 和系统 CPU 指标。
- 不硬性依赖 PlaceholderAPI 或 Spark。

## 环境要求

- Python 3.10+
- Endstone `>=0.11`
- `psutil>=5`
- Python 3.10 使用 `tomli>=2` 解析 TOML。

如需 Spark 指标，请安装兼容版本的以下插件：

- Endstone PlaceholderAPI（`papi`）
- 支持 `spark` expansion 的 Endstone Spark

集成使用 PAPI 的冒号命名空间语法：

```text
{spark:tps_5s}
{spark:tickduration_10s}
{spark:cpu_process_10s}
{spark:cpu_system_1m}
```

如果 PAPI 缺失、未启用，或者没有注册 `spark` expansion，状态页面仍可正常工作，并回退到 Endstone/psutil 数据。

## 安装

按照下面的说明构建 wheel，然后将 `dist/` 中生成的
`endstone_show_status-*.whl` 文件复制到服务器的 `plugins/` 目录，并重启 Endstone。

插件首次启动时会在插件数据目录中创建配置文件。

## 构建

这是一个纯 Python Endstone 插件，不需要 C/C++ 编译器；“构建”操作会把源代码和内置网页资源打包成 wheel。

### Windows / PowerShell

在项目根目录执行：

```powershell
python -m pip install --upgrade build
python -m build --wheel
```

wheel 会写入：

```text
dist/endstone_show_status-0.2.1-py3-none-any.whl
```

同时构建 wheel 和源码分发包：

```powershell
python -m build
```

### Linux

在项目根目录执行：

```bash
python3 -m pip install --upgrade build
python3 -m build --wheel
```

同时构建两种分发格式：

```bash
python3 -m build
```

### 不使用 `build` 前端构建

如果本地环境已经包含构建后端依赖，也可以直接使用 pip 创建 wheel：

```bash
python -m pip wheel . --no-deps --no-build-isolation -w dist
```

## 开发与测试

以 editable 模式安装项目：

```bash
python -m pip install -e .
```

运行单元测试：

```bash
python -m unittest discover -s tests -v
```

进行发布式验证：

```bash
python -m pip install --upgrade build
python -m build --wheel
python -m unittest discover -s tests -v
```

Release 工作流支持手动运行时设置 `dry_run=true` 进行验证：它会检出指定提交，
检查标签与项目版本，构建 wheel 并上传为 artifact，但不会创建 GitHub Release。
正常手动发布时保持 `dry_run=false`；推送 `v*` 标签时仍保持原有发布行为。

## PlaceholderAPI / Spark 集成

`SparkPapiClient` 首先加载原生 `PlaceholderAPI` 服务，并检查 `spark` expansion 是否已注册，然后读取以下值：

| 占位符                       | 用途                        |
| ---------------------------- | --------------------------- |
| `{spark:tps_5s}`           | 5 秒 TPS                    |
| `{spark:tickduration_10s}` | 10 秒 MSPT 分布，使用中位数 |
| `{spark:cpu_process_10s}`  | 10 秒 Spark/BDS 进程 CPU    |
| `{spark:cpu_system_1m}`    | 1 分钟 Spark/系统 CPU       |

数值解析前会移除 Minecraft 颜色代码。

插件要求使用冒号分隔的 PAPI 命名空间语法。不支持 `{spark.tps_5s}` 和 `{spark_tps_5s}` 等旧的点号或下划线分隔写法。

## 配置

插件会在其数据目录中创建 `config.toml`。

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

`port = 0` 会选择基岩服务器端口加 2。如果无法读取服务器端口，则使用 `19134`。

保持 `auth_password` 为空时页面保持公开。设置 `auth_username` 和 `auth_password` 后启用 HTTP Basic Authentication。

### 状态采集

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

### 用户界面

```toml
[ui]
server_name = "Bedrock Server"
server_address = ""
language = "zh-CN"
default_theme = "deepslate"
```

支持的语言为 `zh-CN` 和 `en-US`，支持的主题为 `deepslate` 和 `grass`。

## 环境变量

以下环境变量会覆盖对应的配置值：

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

## HTTP 端点

只接受 `GET` 和 `HEAD` 请求。

| 端点                    | 说明           |
| ----------------------- | -------------- |
| `/`                   | 内置状态页面   |
| `/api/v1/status`      | 当前 JSON 快照 |
| `/api/v1/history`     | 滚动历史 JSON  |
| `/data`               | 旧版状态数据   |
| `/healthz`            | 插件健康探针   |
| `/robots.txt`         | 搜索引擎策略   |
| `/assets/app.css`     | 内置样式表     |
| `/assets/app.js`      | 内置前端脚本   |
| `/assets/favicon.svg` | 内置 favicon   |

## 打包布局

wheel 提供以下 Endstone entry point：

```text
show_status = endstone_show_status:ShowStatus
```

内置的 `webui/*.html`、`*.css`、`*.js` 和 `*.svg` 文件会作为包数据包含在内。

## 安全说明

页面设计为只读，但公开访问仍可能暴露配置中启用的数据。将 HTTP 端口暴露到互联网前，请特别检查 `expose_players`、`expose_chat`、`server_address` 和 Basic Auth 设置。

内置请求保护会限制全局及每 IP 并发，并使用令牌桶限流。将服务放在反向代理之后仍是公开部署时的合理做法。

## 许可证

本项目使用 [GNU GPL-3.0](LICENSE) 许可证。
