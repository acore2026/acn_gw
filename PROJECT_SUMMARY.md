# Agent GW - Project Summary

**Agent GW** is a Python backend gateway for managing autonomous agents in distributed systems. It provides three core services for agent registration, real-time communication, and media streaming.

## Architecture Overview

```
┌─────────────────┐
│     Agents      │
└────────┬────────┘
         │ WebSocket
         ▼
┌─────────────────┐     WebSocket      ┌─────────────────┐
│  ACF (Port 9002)│◄──────────────────►│  ARF (Port 9001)│
│  - Connections  │                    │  - HTTP API     │
│  - Forwarding   │                    │  - Discovery    │
└────────┬────────┘                    └────────┬────────┘
         │                                      │
         │          ┌─────────────────┐        │ QUIC
         │          │  MOQT Relay     │        │ (MOQT)
         └─────────►│  (Port 9003)    │◄───────┘
                    │  - Pub/Sub      │
                    │  - Object Relay │
                    │  - Caching      │
                    └─────────────────┘
```

## Core Services

### ARF - Agent Repository Function (Port 9001)
HTTP REST API for agent lifecycle management.

**Endpoints:**
- `POST /arf/v1/agent-cards` - Register agent with Verifiable Credentials
- `POST /arf/v1/agent-discoveries` - Discover agents by required capabilities

### ACF - Agent Communication Function (Port 9002)
WebSocket server for real-time agent messaging.

**Message Types:**
- `SETUP` - Agent connection initialization
- `TASK_REQUEST_COLLABORATION` - Request agent collaboration
- `TASK_ACCEPT_COLLABORATION` - Accept collaboration request
- `DISCOVER_RESULT` - Discovery results
- `ROUTE` - Message routing

### MOQT Relay (Port 9003)
Media over QUIC Transport relay for streaming data.

**Implementation**: Uses [moq-py](https://github.com/DineshAdhi/moq-go) library (draft-ietf-moq-transport-17)

**Features:**
- QUIC transport with connection migration
- Object caching (memory + disk)
- Publisher/subscriber management
- Full track namespace support
- Standard MOQT protocol implementation

**Cache Configuration:**
- Memory cache: 100MB default
- Disk cache: 1GB default
- Cache directory: `.relay_cache/`

## Quick Start Guide

### 1. Environment Setup

```bash
# Using Makefile (Recommended)
make setup

# Or manually
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Running Services

```bash
# Run all services
make run

# Or individually
make run-arf      # ARF only
make run-acf      # ACF only
make run-moqt     # MOQT Relay only
```

### 3. Register an Agent

```bash
curl -X POST http://localhost:9001/arf/v1/agent-cards \
  -H "Content-Type: application/json" \
  -d '{
    "body": {
      "agent_id": "did:acn:agent:001",
      "priority": 2,
      "vc_list": [{
        "claims": {
          "agent_name": "Camera Bot",
          "agent_id": "did:acn:agent:001",
          "agent_attribute": "camera"
        }
      }]
    }
  }'
```

### 4. Discover Agents

```bash
curl -X POST http://localhost:9001/arf/v1/agent-discoveries \
  -H "Content-Type: application/json" \
  -d '{
    "body": {
      "agent_id": "did:acn:agent:001",
      "task_id": "task-123",
      "required_capabilities": ["camera", "radar"]
    }
  }'
```

### 5. Connect via WebSocket (Python Example)

```python
import asyncio
import websockets
import json

async def connect_agent():
    async with websockets.connect("ws://localhost:9002") as ws:
        # Send SETUP message
        await ws.send(json.dumps({
            "type": "SETUP",
            "timestamp": "2025-01-01T00:00:00Z",
            "payload": {"src_agent_id": "did:acn:agent:001"}
        }))
        
        # Listen for messages
        while True:
            message = await ws.recv()
            data = json.loads(message)
            print(f"Received: {data}")

asyncio.run(connect_agent())
```

## Testing

```bash
# Run all tests
make test

# Run specific test categories
make test-unit         # Unit tests only
make test-int          # Integration tests only
make coverage          # With coverage report

# Run single test file
pytest tests/test_models.py -v

# Run single test
pytest tests/test_models.py::TestAgentModel::test_create_agent -v
```

## Database Schema

SQLite database (`agent_gw.db`) with three tables:

### Agent Table
- `agent_id` (PK): Unique agent identifier (DID format)
- `agent_name`: Human-readable name
- `agent_capability`: JSON array of capabilities
- `agent_auth`: Authentication token
- `agent_status`: online/offline
- `priority`: Integer priority level

### Task Table
- `id` (PK): Auto-increment ID
- `agent_id`: Foreign key to Agent
- `task_id`: Task identifier
- `task_description`: Task details

### Track Table
- `id` (PK): Auto-increment ID
- `task_id`: Associated task
- `track_list`: JSON array of track data

## Project Structure

```
acn_gw/
├── moq-py/                    # MOQT protocol implementation (external)
│   ├── moq/                  # Core MOQT modules
│   │   ├── relay/            # Relay implementation
│   │   ├── pub/              # Publisher
│   │   ├── sub/              # Subscriber
│   │   ├── encoding/         # VarInt, KV pairs, Location
│   │   ├── messages/         # Control and data messages
│   │   └── transport/        # QUIC transport layer
│   └── examples/             # Usage examples
├── moqt_old/                  # Legacy MOQT implementation (backup)
├── moqt_relay_old.py          # Legacy relay (backup)
├── tests/                    # Test suite
│   ├── conftest.py           # Shared pytest fixtures
│   ├── test_models.py        # Database model tests
│   ├── test_arf_api.py       # ARF HTTP API tests
│   ├── test_acf_server.py    # ACF WebSocket tests
│   ├── test_moqt_relay.py    # MOQT tests
│   └── test_integration.py   # Integration tests
├── models.py                 # SQLAlchemy models
├── arf_server.py             # ARF HTTP server
├── acf_server.py             # ACF WebSocket server
├── moqt_relay.py             # MOQT Relay adapter (using moq-py)
├── test_moq_py_migration.py  # Migration compatibility tests
├── use_moq-py.md             # MOQ-PY migration report
├── main.py                   # Entry point (all services)
├── logger_config.py          # Logging configuration
├── run_tests.py              # Test runner script
├── Makefile                  # Common commands
├── requirements.txt          # Python dependencies
├── setup.sh                  # Environment setup
└── AGENTS.md                 # AI coding guidelines
```

## Available Commands

### Setup & Development
```bash
make setup        # Create venv and install dependencies
make install      # Install/update dependencies
make run          # Start all services
make stop         # Stop all services
```

### Testing
```bash
make test         # Run all tests
make test-unit    # Unit tests only
make test-int     # Integration tests only
make coverage     # Run with coverage report
```

### Maintenance
```bash
make lint              # Run code linting
make clean             # Remove venv and cache files
make clean-pyc         # Remove Python cache only
make clean-moq-cache   # Remove MOQ relay cache only
```

## Dependencies

### Core
- **fastapi** (0.109.0) - HTTP framework
- **uvicorn** (0.27.0) - ASGI server
- **websockets** (12.0) - WebSocket support
- **sqlalchemy** (2.0.25) - Database ORM
- **aiosqlite** (0.19.0) - Async SQLite
- **pydantic** (2.5.3) - Data validation
- **httpx** (0.26.0) - HTTP client

### MOQT
- **moq-py** - MOQT protocol implementation (draft-ietf-moq-transport-17)
- **aioquic** (>=0.9.0) - QUIC transport
- **cryptography** (>=41.0.0) - Encryption

### Testing
- **pytest** (7.4.4) - Testing framework
- **pytest-asyncio** (0.21.1) - Async test support
- **pytest-cov** (4.1.0) - Coverage reporting

## Configuration

### Ports
- **9001**: ARF HTTP API
- **9002**: ACF WebSocket
- **9003**: MOQT Relay (QUIC)

### Database
- **Type**: SQLite
- **File**: `agent_gw.db`
- **Auto-created**: On first startup

### Logging
- **Directory**: `logs/`
- **Files**:
  - `arf.log` - ARF service
  - `acf.log` - ACF service
  - `moqt.log` - MOQT Relay (adapter + moq-py unified)
  - `agent_gw.log` - Main application
- **Format**: Timestamp - Level - [File:Line] - Message
- **Note**: MOQT logs include both adapter layer and moq-py internal logs

### IDM Integration
- **URL**: `http://10.0.18.210:9020/idm/v1/vc-verifications`
- **Purpose**: VC (Verifiable Credential) validation

## Troubleshooting

### Port Already in Use
```bash
# Kill processes on specific ports
lsof -ti:9001 | xargs kill -9
lsof -ti:9002 | xargs kill -9
lsof -ti:9003 | xargs kill -9
```

### Database Locked
```bash
# Remove and recreate database
rm agent_gw.db
```

### Virtual Environment Issues
```bash
# Recreate environment
make clean
make setup
```

## Use Cases

1. **Multi-Agent Systems**: Coordinate multiple autonomous agents
2. **IoT Device Management**: Register and discover IoT devices
3. **Media Streaming**: Stream data via MOQT protocol
4. **Task Distribution**: Assign tasks to capable agents
5. **Real-time Communication**: WebSocket-based messaging

## License

MIT License
