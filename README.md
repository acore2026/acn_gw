# Agent GW

Agent GW 是一个 Python 后端应用，包含三个运行实体：

- ARF（Agent Repository Function）：FastAPI HTTP 服务，默认端口 `9001`
- ACF（Agent Communication Function）：WebSocket 服务，默认端口 `9002`
- MOQT Relay：基于 QUIC 的 MOQT Relay 服务，默认端口 `9003`

根目录的 `agent_gw.py` 是统一启动入口，实际业务代码在 `agent_gw/`。

注意：MOQT 协议实现来自外部依赖库，运行时需要在项目根目录准备本地 `moq/`
目录，但该目录已在 `.gitignore` 中忽略，不随当前仓库上传。

## 快速启动

```bash
./setup.sh
source venv/bin/activate
./start_agent_gw.sh start
```

查看状态和日志：

```bash
./start_agent_gw.sh status
./start_agent_gw.sh log
```

前台运行：

```bash
python3 agent_gw.py
```

停止后台服务：

```bash
./start_agent_gw.sh stop
```

## 目录结构

```text
.
├── agent_gw.py              # 根目录启动入口，调用 agent_gw.main.run()
├── start_agent_gw.sh        # 后台启动/停止/重启/查看日志脚本
├── setup.sh                 # 初始化虚拟环境并安装依赖
├── requirements.txt         # Python 运行依赖和测试依赖
├── AGENTS.md                # AI coding agent 工作规范
├── agent_gw/                # Agent GW 应用代码
│   ├── main.py              # 同时启动 ARF、ACF、MOQT Relay
│   ├── arf_server.py        # ARF HTTP API
│   ├── acf_server.py        # ACF WebSocket 服务
│   ├── models.py            # SQLAlchemy 模型和 SQLite 配置
│   └── logger_config.py     # 日志配置
├── docs/                    # 项目文档
└── tests/                   # 测试代码
```

本地运行时可能还会看到以下目录或文件，它们不属于当前仓库上传内容：

```text
.
├── moq/                     # 本地外部 MOQT 依赖库，运行 MOQT Relay 必需
├── logs/                    # 根目录启动日志
├── agent_gw/logs/           # 应用日志
├── agent_gw/agent_gw.db     # 本地 SQLite 数据库
├── venv/                    # 本地 Python 虚拟环境
├── .agent_gw.pid            # 后台进程 PID 文件
├── .pytest_cache/           # pytest 缓存
├── .ruff_cache/             # ruff 缓存
└── .relay_cache/            # Relay 缓存
```

## 运行时必需文件

最小运行需要保留：

- `agent_gw.py`
- `agent_gw/`
- `requirements.txt`
- `start_agent_gw.sh`（如果使用后台管理脚本）
- `setup.sh`（仅初始化环境时需要，运行中不直接依赖）
- 本地 `moq/` 外部依赖目录（不随当前仓库上传）

说明：

- `agent_gw/main.py` 会把根目录下的 `moq/` 加入 `sys.path`，所以 `moq/` 不能删除，否则 MOQT Relay 无法启动。
- `moq/` 是外部依赖库的本地副本；克隆当前仓库后，需要额外复制或克隆该目录到项目根目录。
- `agent_gw/models.py` 默认在 `agent_gw/agent_gw.db` 使用 SQLite 数据库；数据库文件可以不存在，程序会按模型初始化创建。
- `agent_gw/logs/` 和根目录 `logs/` 可不存在，启动时会按日志配置和启动脚本创建。

## 运行时非必需文件

以下内容不影响生产运行，可以不打包到运行环境；是否删除取决于是否还需要本地开发、测试或追溯历史。

| 路径 | 类型 | 说明 |
| --- | --- | --- |
| `tests/` | 测试 | pytest 测试代码；运行服务不依赖，但建议在开发仓库中保留 |
| `docs/` | 文档 | 项目说明、测试说明和总结文档；运行服务不依赖 |
| `AGENTS.md` | 开发规范 | 给 AI coding agent 使用的工作说明；运行服务不依赖 |
| `moq/` | 外部依赖 | 当前仓库不跟踪；运行 MOQT Relay 前需要本地准备 |
| `moq-backup/` | 备份/历史残留 | 当前仓库不跟踪；运行服务不依赖 |
| `venv/` | 本地环境 | 可重新通过 `setup.sh` 或 `python3 -m venv venv` 生成；部署时通常重建环境 |
| `.pytest_cache/`、`.ruff_cache/` | 工具缓存 | pytest/ruff 生成的缓存 |
| `__pycache__/`、`*.pyc` | Python 缓存 | Python 自动生成，可删除 |
| `logs/`、`agent_gw/logs/`、`*.log` | 运行日志 | 运行时生成，可清理或由日志系统接管 |
| `.relay_cache/`、`agent_gw/.relay_cache/`、`moq/.relay_cache/`、`moq/.moq_cache/` | Relay/MOQ 缓存 | 运行或测试时生成，可清理 |
| `.agent_gw.pid` | 进程文件 | `start_agent_gw.sh` 后台启动时生成 |
| `agent_gw/agent_gw.db`、`*.db`、`*.sqlite3` | 数据库文件 | SQLite 运行数据，不属于源码；删除会丢失本地数据 |
| `.git/`、`moq/.git/` | Git 元数据 | 源码版本管理需要；运行服务不依赖 |
| `moq/.playwright-cli/`、`moq/.codex`、`.codex`、`.agents/` | 工具状态 | 本地工具或 agent 会话状态，运行服务不依赖 |

## 常用命令

安装依赖：

```bash
./setup.sh
source venv/bin/activate
```

准备 MOQT 外部依赖：

```bash
# 将 MOQT 依赖库复制或克隆到项目根目录，最终路径应为 ./moq
# 目录内需要能提供 `from moq import MOQRelay` 所需的 Python package。
```

启动全部服务：

```bash
python3 agent_gw.py
```

后台管理：

```bash
./start_agent_gw.sh start
./start_agent_gw.sh restart
./start_agent_gw.sh status
./start_agent_gw.sh log
./start_agent_gw.sh stop
```

单独启动服务：

```bash
python -m agent_gw.arf_server
python -m agent_gw.acf_server
```

运行测试：

```bash
pytest
pytest tests/test_models.py -v
pytest tests/test_arf_api.py -v
pytest tests/test_acf_server.py -v
pytest tests/test_moqt_relay.py -v
```

## 服务端口

| 服务 | 端口 | 协议 |
| --- | --- | --- |
| ARF | `9001` | HTTP / FastAPI |
| ACF | `9002` | WebSocket |
| MOQT Relay | `9003` | QUIC / MOQT |

## `element-logs` 上报

ARF 和 ACF 都会把运行中的 agent 状态上报到 `element-logs` 服务。当前默认地址是：

```text
https://localhost:9005/acn/v3/element-logs
```

可以通过环境变量覆盖：

```bash
export ELEMENT_LOGS_URL="https://your-element-logs-host:9005/acn/v3/element-logs"
```

当前 HTTP 客户端会使用系统代理环境变量，并且不校验证书。

### 上报格式

外层请求是统一的包裹结构：

```json
{
  "method": "POST",
  "url": "/acn/v3/element-logs",
  "headers": {
    "Content-Type": "application/json"
  },
  "body": {
    "element_id": "AgentGW",
    "log_type": "PublishAgent",
    "timestamp": "2026-05-09T12:00:00Z",
    "content": {}
  }
}
```

`PublishAgent` 的 `content` 字段目前两边基本一致，都会包含：

- `agent_id`
- `agent_name`
- `agent_capability`
- `agent_status`
- `setup_at`
- `priority`
- `consent`

### ARF 和 ACF 的区别

- ARF 在 agent card 注册成功后上报 `PublishAgent`，通常 `agent_status` 是 `offline`，`setup_at` 为空。
- ACF 在 agent `SETUP` 成功后上报 `PublishAgent`，通常 `agent_status` 是 `online`，`setup_at` 是实际连接时间。
- 两边的请求格式相同，差异主要在触发时机和字段值。

## 清理建议

只清理运行产物和缓存时可以使用：

```bash
rm -rf .pytest_cache .ruff_cache .relay_cache
rm -rf agent_gw/.relay_cache agent_gw/logs logs
find . -name '__pycache__' -type d -prune -exec rm -rf {} +
find . -name '*.pyc' -delete
```

如果要准备一个更小的部署包，通常保留当前仓库中的 `agent_gw.py`、`agent_gw/`、
`requirements.txt` 和必要启动脚本，并在部署环境额外准备 `moq/` 外部依赖即可；
`tests/`、`docs/`、缓存、日志、数据库文件和本地工具状态都可以不包含。
