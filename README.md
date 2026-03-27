# Agent GW - Backend Application

## Overview

Agent Gateway backend program with three functional entities:
- **ARF** (Agent Repository Function): HTTP server on port 9001
- **ACF** (Agent Communication Function): WebSocket server on port 9002
- **MOQT Relay**: MOQT protocol server on port 9003

## Project Structure

```
.
├── requirements.txt      # Python dependencies
├── models.py            # Database models (Agent, Task, Track)
├── arf_server.py        # ARF HTTP server
├── acf_server.py        # ACF WebSocket server
├── moqt_relay.py        # MOQT Relay server
├── main.py              # Main entry point
└── readme               # Original requirements document
```

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the application:
```bash
python main.py
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

#### WebSocket /ws
ACF connects to ARF via WebSocket for message exchange.

### ACF - Agent Communication Function (Port 9002)

WebSocket server for agent communication.

**Message Types:**

#### SETUP
Sent when agent establishes WebSocket connection.
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
Request collaboration from another agent.
```json
{
    "type": "TASK_REQUEST_COLLABORATION",
    "timestamp": "2025-01-01T00:00:00Z",
    "payload": {
        "src_agent_id": "ARF",
        "dst_agent_id": "did:acn:agent:987654321",
        "task_id": "task-12345",
        "task_description": "危险区域协同巡检",
        "agent_card": {
            "agent_id": "...",
            "skill": ["声光驱离", "四足机器狗"]
        }
    }
}
```

#### TASK_ACCEPT_COLLABORATION
Accept collaboration request.
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

#### DISCOVER_RESULT
Discovery result message.
```json
{
    "type": "DISCOVER_RESULT",
    "timestamp": "2025-01-01T00:00:00Z",
    "payload": {
        "src_agent_id": "ARF",
        "dst_agent_id": "did:acn:agent:111111111",
        "discover_result": ["did:acn:agent:987654321"]
    }
}
```

### MOQT Relay (Port 9003)

MOQT (Media over QUIC Transport) relay server.

**Message Types:**

#### SUBSCRIBE
Subscribe to a track.
```json
{
    "type": "SUBSCRIBE",
    "track_id": "track-123"
}
```

#### PUBLISH
Publish a track.
```json
{
    "type": "PUBLISH",
    "track_id": "track-123"
}
```

#### OBJECT
Publish an object to a track.
```json
{
    "type": "OBJECT",
    "track_id": "track-123",
    "data": {...}
}
```

#### UNSUBSCRIBE
Unsubscribe from a track.
```json
{
    "type": "UNSUBSCRIBE",
    "track_id": "track-123"
}
```

## Database Schema

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
         │          ┌─────────────────┐        │ HTTP
         │          │  MOQT Relay     │        │
         └─────────►│  (Port 9003)    │◄───────┘
                    │  - Pub/Sub      │
                    │  - Object Relay │
                    └─────────────────┘
```

## Agent Discovery Flow

1. Agent sends discovery request to ARF `/arf/v1/agent-discoveries`
2. ARF returns 200 OK immediately
3. ARF asynchronously:
   - Filters online agents not in tasks
   - Matches capabilities
   - Sorts by priority
   - Sends `TASK_REQUEST_COLLABORATION` via ACF
4. Target agent receives message and responds with `TASK_ACCEPT_COLLABORATION`
5. ACF forwards to ARF
6. ARF updates Task table and sends `DISCOVER_RESULT`

## IDM Integration

ARF forwards agent card registration to IDM for VC verification:
- URL: `http://10.0.18.210:9020/idm/v1/vc-verifications`

## License

MIT
