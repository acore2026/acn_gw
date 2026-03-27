# Agent GW - Backend Application

## Overview

Agent Gateway backend program with three functional entities:
- **ARF** (Agent Repository Function): HTTP server on port 9001
- **ACF** (Agent Communication Function): WebSocket server on port 9002
- **MOQT Relay**: MOQT protocol server on port 9003 (QUIC transport)

## Requirements

- Python 3.8+
- pip
- Virtual environment (recommended)

## Quick Start

### Option 1: Using Setup Script (Recommended)

```bash
# Clone the repository
git clone <repository-url>
cd acn_gw

# Run setup script (creates venv and installs dependencies)
./setup.sh

# Activate virtual environment
source venv/bin/activate

# Start the application
python main.py
```

### Option 2: Using Makefile

```bash
# Setup environment
make setup

# Run all services
make run

# Run tests
make test
```

### Option 3: Manual Setup

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

## Project Structure

```
.
├── moqt/                   # MOQT protocol implementation
│   ├── encoding/          # Encoding utilities (varint, kv-pairs)
│   ├── messages/          # Control and data messages
│   └── transport/         # QUIC transport layer
├── tests/                 # Test suite
│   ├── test_models.py
│   ├── test_arf_api.py
│   ├── test_acf_server.py
│   ├── test_moqt_relay.py
│   └── test_integration.py
├── models.py              # Database models (Agent, Task, Track)
├── arf_server.py          # ARF HTTP server (port 9001)
├── acf_server.py          # ACF WebSocket server (port 9002)
├── moqt_relay.py          # MOQT Relay server (port 9003)
├── main.py                # Main entry point
├── setup.sh               # Environment setup script
├── Makefile               # Common tasks automation
├── requirements.txt       # Python dependencies
└── README.md              # This file
```

## Available Commands

### Using Makefile

```bash
# Setup
make setup        # Create venv and install dependencies
make venv         # Create virtual environment only
make install      # Install dependencies in existing venv

# Development
make run          # Start all services (ARF, ACF, MOQT Relay)
make run-arf      # Start ARF server only (port 9001)
make run-acf      # Start ACF server only (port 9002)
make run-moqt     # Start MOQT Relay only (port 9003)

# Testing
make test         # Run all tests
make test-unit    # Run unit tests only
make test-int     # Run integration tests only
make coverage     # Run tests with coverage report

# Maintenance
make clean        # Remove venv and cache files
make clean-pyc    # Remove Python cache files only
make lint         # Run code linting
```

### Manual Commands (after activating venv)

```bash
# Start all services
python main.py

# Start individual services
python arf_server.py    # ARF on port 9001
python acf_server.py    # ACF on port 9002
python moqt_relay.py    # MOQT Relay on port 9003

# Run tests
python run_tests.py

# Run with coverage
pytest --cov=. --cov-report=html
```

## Virtual Environment

The project uses Python virtual environment to isolate dependencies.

### Activating Virtual Environment

```bash
# Linux/Mac
source venv/bin/activate

# Windows (Git Bash)
source venv/Scripts/activate

# Windows (CMD)
venv\Scripts\activate.bat

# Windows (PowerShell)
venv\Scripts\Activate.ps1
```

### Deactivating Virtual Environment

```bash
deactivate
```

### Updating Dependencies

```bash
# Activate venv first
source venv/bin/activate

# Update dependencies
pip install -r requirements.txt

# If you add new dependencies
pip freeze > requirements.txt
```

## Services

### ARF - Agent Repository Function (Port 9001)

HTTP REST API endpoints:

#### POST /arf/v1/agent-cards
Register agent credentials. Validates with IDM before storing.

**Request:**
```json
{
    "method": "POST",
    "url": "/idm/v1/vc-verifications",
    "headers": {
        "Content-Type": "application/json"
    },
    "body": {
        "agent_id": "...",
        "priority": 2,
        "timestamp": "2024-03-23T12:00:00Z",
        "signature": "...",
        "vc_list": [...]
    }
}
```

#### POST /arf/v1/agent-discoveries
Discover agents based on required capabilities.

**Request:**
```json
{
    "method": "POST",
    "url": "/arf/v1/agent-discoveries",
    "headers": {
        "Content-Type": "application/json"
    },
    "body": {
        "task_id": "task-12345",
        "agent_id": "did:acn:agent:111111111",
        "required_capabilities": ["camera", "radar", "four_legs"],
        "timestamp": "2024-03-23T12:00:00Z"
    }
}
```

### ACF - Agent Communication Function (Port 9002)

WebSocket server for agent communication.

**Message Types:**

#### SETUP
```json
{
    "type": "SETUP",
    "timestamp": "2025-01-01T00:00:00Z",
    "payload": {
        "src_agent_id": "did:acn:agent:111111111"
    }
}
```

#### TASK_REQUEST_COLLABORATION
```json
{
    "type": "TASK_REQUEST_COLLABORATION",
    "timestamp": "2025-01-01T00:00:00Z",
    "payload": {
        "src_agent_id": "ARF",
        "dst_agent_id": "did:acn:agent:987654321",
        "task_id": "task-12345",
        "task_description": "Collaboration task",
        "agent_card": {
            "agent_id": "...",
            "skill": ["capability1", "capability2"]
        }
    }
}
```

#### TASK_ACCEPT_COLLABORATION
```json
{
    "type": "TASK_ACCEPT_COLLABORATION",
    "timestamp": "2025-01-01T00:00:00Z",
    "payload": {
        "src_agent_id": "did:acn:agent:987654321",
        "dst_agent_id": "ARF",
        "task_id": "task-12345",
        "result": "OK"
    }
}
```

### MOQT Relay (Port 9003)

MOQT (Media over QUIC Transport) relay server with full protocol implementation.

**Control Messages:**
- `SUBSCRIBE` - Subscribe to a track
- `SUBSCRIBE_OK` - Subscription confirmation
- `PUBLISH` - Publish a track
- `PUBLISH_OK` - Publication confirmation
- `FETCH` - Request specific objects
- `FETCH_OK` - Fetch confirmation

**Data Messages:**
- `OBJECT_DATAGRAM` - Object sent as QUIC datagram
- Binary encoding using VarInt and proper MOQT format

**Features:**
- QUIC transport with connection migration support
- Object caching for FETCH operations
- Full track names with namespace support
- Publisher/subscriber management

## Database Schema

SQLite database (`agent_gw.db`) with three tables:

### Agent Table
- `agent_id` (PK): Agent unique identifier
- `agent_name`: Agent name
- `agent_capability`: List of capabilities (JSON)
- `agent_auth`: Authentication info
- `agent_status`: online/offline
- `priority`: Priority level (integer)

### Task Table
- `id` (PK): Auto-increment ID
- `agent_id`: Foreign key to Agent
- `task_id`: Task identifier
- `task_description`: Task description

### Track Table
- `id` (PK): Auto-increment ID
- `task_id`: Task identifier
- `track_list`: List of tracks (JSON)

## Architecture

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

## Testing

Run the test suite:

```bash
# Run all tests
make test

# Run specific test types
make test-unit      # Unit tests only
make test-int       # Integration tests only
make coverage       # With coverage report

# Or manually
python run_tests.py -v
python run_tests.py unit -v
python run_tests.py integration -v
```

## Troubleshooting

### Port Already in Use

```bash
# Find and kill process using port 9001, 9002, or 9003
lsof -ti:9001 | xargs kill -9
lsof -ti:9002 | xargs kill -9
lsof -ti:9003 | xargs kill -9
```

### Virtual Environment Issues

```bash
# Remove and recreate venv
rm -rf venv
./setup.sh
# or
make setup
```

### Database Locked

```bash
# Remove database file
rm agent_gw.db
```

## IDM Integration

ARF forwards agent card registration to IDM for VC verification:
- URL: `http://10.0.18.210:9020/idm/v1/vc-verifications`

## License

MIT
