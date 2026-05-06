# Agent GW

Agent GW 是一个 Python 后端应用，包含三个运行实体：

- ARF（Agent Repository Function）：FastAPI HTTP 服务，默认端口 `9001`
- ACF（Agent Communication Function）：WebSocket 服务，默认端口 `9002`
- MOQT Relay：基于 QUIC 的 MOQT Relay 服务，默认端口 `9003`

根目录的 `agent_gw.py` 是统一启动入口，实际业务代码在 `agent_gw/`，MOQT 协议实现以 vendored package 的形式放在 `moq/`。

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
├── moq/                     # MOQT 协议库和 Relay 实现，运行 MOQT 必需
│   ├── encoding/            # VarInt、KV、Location 等编码工具
│   ├── messages/            # MOQT 控制消息和数据消息
│   ├── pub/                 # Publisher 相关实现
│   ├── relay/               # MOQRelay 实现
│   ├── session/             # Session、Role、订阅/发布状态
│   ├── sub/                 # Subscriber 相关实现
│   └── transport/           # QUIC transport
├── docs/                    # 项目文档
├── tests/                   # 测试代码和测试夹带的样例/复制代码
├── logs/                    # 运行日志，启动后生成
├── venv/                    # 本地 Python 虚拟环境，setup.sh 生成
└── moq-backup/              # 备份/历史残留目录，当前运行不依赖
```

## 运行时必需文件

最小运行需要保留：

- `agent_gw.py`
- `agent_gw/`
- `moq/`
- `requirements.txt`
- `start_agent_gw.sh`（如果使用后台管理脚本）
- `setup.sh`（仅初始化环境时需要，运行中不直接依赖）

说明：

- `agent_gw/main.py` 会把根目录下的 `moq/` 加入 `sys.path`，所以 `moq/` 不能删除，否则 MOQT Relay 无法启动。
- `agent_gw/models.py` 默认在 `agent_gw/agent_gw.db` 使用 SQLite 数据库；数据库文件可以不存在，程序会按模型初始化创建。
- `agent_gw/logs/` 和根目录 `logs/` 可不存在，启动时会按日志配置和启动脚本创建。

## 运行时非必需文件

以下内容不影响生产运行，可以不打包到运行环境；是否删除取决于是否还需要本地开发、测试或追溯历史。

| 路径 | 类型 | 说明 |
| --- | --- | --- |
| `tests/` | 测试 | pytest 测试代码；其中还包含 `tests/agent_gw/`、`tests/moq/`、`tests/docs/` 等测试夹带内容，不作为正式运行入口 |
| `docs/` | 文档 | 项目说明、测试说明和总结文档；运行服务不依赖 |
| `AGENTS.md` | 开发规范 | 给 AI coding agent 使用的工作说明；运行服务不依赖 |
| `moq-backup/` | 备份/历史残留 | 当前 `agent_gw/main.py` 不引用该目录；不是运行必需 |
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

## 清理建议

只清理运行产物和缓存时可以使用：

```bash
rm -rf .pytest_cache .ruff_cache .relay_cache
rm -rf agent_gw/.relay_cache agent_gw/logs logs
find . -name '__pycache__' -type d -prune -exec rm -rf {} +
find . -name '*.pyc' -delete
```

如果要准备一个更小的部署包，通常保留 `agent_gw.py`、`agent_gw/`、`moq/`、`requirements.txt` 和必要启动脚本即可；`tests/`、`docs/`、缓存、日志、数据库文件和本地工具状态都可以不包含。
