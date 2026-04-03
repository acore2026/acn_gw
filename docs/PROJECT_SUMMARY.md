# Agent GW - Project Summary

**Agent GW** is a Python backend gateway for managing autonomous agents in distributed systems. It provides three core services for agent registration, real-time communication, and media streaming.

## Architecture Overview

```text
┌─────────────────┐
│     Agents      │
└────────┬────────┘
         │ WebSocket
         ▼
┌─────────────────┐      HTTP       ┌─────────────────┐
│  ACF (Port 9002)│◄────────────────►│  ARF (Port 9001)│
│  - Connections  │                  │  - HTTP API     │
│  - Forwarding   │                  │  - Discovery    │
│  - Track State  │                  │  - Repository   │
└────────┬────────┘                  └────────┬────────┘
         │                                    │
         │                QUIC                │
         └──────────────►┌─────────────────┐◄─┘
                         │  MOQT Relay     │
                         │  (Port 9003)    │
                         │  - Pub/Sub      │
                         │  - Object Relay │
                         │  - Caching      │
                         └─────────────────┘
```

## Core Services

### ARF - Agent Repository Function

Port: `9001`

Responsibilities:

- Register agent cards and validate VC data through IDM
- Maintain local `Agent`, `Task`, and `Track` records
- Select collaboration candidates by availability, capability match, and priority
- Forward discovery, task execution, clear, and deletion events to ACF

Primary endpoints:

- `POST /arf/v1/agent-cards`
- `POST /arf/v1/agent-discoveries`
- `POST /acn-agent/v1/task-executions`
- `POST /acn-agent/v1/task-execution-terminations`
- `POST /acn-agent/v1/agent-deletions`
- `POST /clear`

### ACF - Agent Communication Function

Port: `9002`

Responsibilities:

- Maintain online agent WebSocket connections
- Receive agent upstream messages and dispatch by message type
- Receive ARF HTTP callbacks and forward messages to target agents
- Persist task-to-track mapping for later subscription

Primary endpoints:

- `WS /acf/ws`
- `POST /acf/v1/discoveries`
- `POST /acn-agent/v1/task-executions`
- `POST /acn-agent/v1/agent-deletions`
- `POST /clear`

### MOQT Relay

Port: `9003`

Responsibilities:

- Provide QUIC-based MOQT relay capability
- Support publish/subscribe object forwarding
- Maintain relay cache state

Implementation notes:

- Uses the local `moq/` implementation in this repository
- Cache directory: `agent_gw/.relay_cache/`

## Data Model

SQLite database: `agent_gw/agent_gw.db`

### Agent

- `agent_id`: primary key
- `agent_name`: display name
- `agent_capability`: JSON array of capabilities
- `agent_auth`: auth field, currently unused by business logic
- `agent_status`: `online` or `offline`
- `priority`: larger value means higher priority

### Task

- `id`: auto increment primary key
- `agent_id`: foreign key to `Agent`
- `task_id`: task identifier
- `task_description`: task description

Constraint:

- unique on `(agent_id, task_id)`

### Track

- `id`: auto increment primary key
- `src_agent_id`: publishing agent id
- `task_id`: task identifier
- `track_list`: JSON array of `{namespace, track}`

Constraint:

- unique on `task_id`

Implementation note:

- Track state is aggregated per `task_id`, not per publisher row.

## ARF Message Flow And Processing

### Agent Card Registration

Endpoint:

- `POST /arf/v1/agent-cards`

Current behavior:

1. Read request JSON and log inbound HTTP message.
2. Forward the original payload to `IDM_URL` for VC verification.
3. If `idm_result.valid` is false, return `400`.
4. Read `agent_id` from the request top level.
5. Read `vc_list` and `priority` from `body`.
6. Extract `agent_name` and deduplicated `agent_attribute` values from VC claims.
7. Upsert the `Agent` row and default new rows to `agent_status='offline'`.
8. Return `200 {"status": "OK"}`.

Database effect:

- insert or update `Agent`

### Agent Discovery

Endpoint:

- `POST /arf/v1/agent-discoveries`

Current request fields:

- `data["body"]["agent_id"]`
- `data["body"]["task_id"]`
- `data["body"]["required_capabilities"]`

Current behavior:

1. Return `200 {"status": "OK"}` immediately.
2. Schedule `process_discovery(...)` asynchronously.
3. In the background, query all agents already assigned in `Task`.
4. Select candidates where:
   - `agent_status == 'online'`
   - agent is not already in `Task`
   - agent is not the requester
5. Score each candidate by overlap between `agent_capability` and `required_capabilities`.
6. Drop candidates with zero overlap.
7. Sort by:
   - higher `priority` first
   - then more matching capabilities
8. Choose the first candidate and send a discovery request to `ACF /acf/v1/discoveries`.

HTTP payload sent from ARF to ACF:

```json
{
  "method": "POST",
  "url": "/acf/v1/discoveries",
  "headers": {
    "Content-Type": "application/json"
  },
  "body": {
    "src_agent_id": "ARF",
    "dst_agent_id": "<selected_agent_id>",
    "task_id": "<task_id>",
    "task_description": "Collaboration task",
    "agent_card": {
      "agent_id": "<selected_agent_id>",
      "skill": ["capability_a", "capability_b"]
    },
    "timestamp": "<utc iso8601>"
  }
}
```

Implementation note:

- In current code, `agent_card.agent_id` is the selected collaborator itself, not the requester.

### Task Execution

Endpoint:

- `POST /acn-agent/v1/task-executions`

Current request fields:

- `body.agent_id`
- `body.task_id`
- `body.description`

Current behavior:

1. Log inbound HTTP message.
2. Upsert `Task` using `(agent_id, task_id)`.
3. Forward the original payload to `ACF /acn-agent/v1/task-executions`.
4. If forwarding fails, only log the failure.
5. Return `200 {"status": "OK"}`.

Database effect:

- insert or update `Task`

### Task Execution Termination

Endpoint:

- `POST /acn-agent/v1/task-execution-terminations`

Current behavior:

1. Read `body.agent_id` and `body.task_id`.
2. Delete the matching `Task` row if it exists.
3. If not found, only log.
4. Return `200 {"status": "OK"}`.

Database effect:

- delete `Task`

### Agent Deletion

Endpoint:

- `POST /acn-agent/v1/agent-deletions`

Current request field:

- `data.get("agent_id")`

Current behavior:

1. Delete local `Task` rows for the agent.
2. Delete local `Agent` row.
3. Forward the original payload to `ACF /acn-agent/v1/agent-deletions`.
4. Return `200 {"status": "OK"}`.

Database effect:

- delete `Task`
- delete `Agent`

Implementation note:

- This endpoint currently reads `agent_id` from the request top level, not from `body`.

### Clear

Endpoint:

- `POST /clear`

Current behavior:

1. Clear local `Task`, `Track`, and `Agent`.
2. Send the following fixed payload to `ACF /clear`:

```json
{
  "method": "POST",
  "url": "/clear",
  "body": {}
}
```

3. Return `200 {"status": "OK"}`.

Database effect:

- clear `Task`
- clear `Track`
- clear `Agent`

## ACF Message Flow And Processing

### Connection Management

ACF stores online agent connections in `ACFServer.connections`:

- key: `agent_id`
- value: WebSocket object

Lifecycle:

1. Agent connects to `WS /acf/ws`.
2. Agent sends `SETUP`.
3. ACF stores the WebSocket under `payload.src_agent_id`.
4. ACF updates `Agent.agent_status` to `online`.
5. On disconnect or `DISCONNECTION`:
   - remove the connection
   - mark `Agent.agent_status` as `offline`
   - if explicit `DISCONNECTION`, also delete that agent's `Track` rows

### WebSocket Dispatcher

Entry point:

- `WS /acf/ws`

Dispatch target:

- `SETUP` -> `handle_setup`
- `PUBLISH_TRACK` -> `handle_publish_track`
- `START_TASK` -> `handle_start_task`
- `DISCONNECTION` -> `handle_disconnection`
- `TASK_REQUEST_COLLABORATION` -> `handle_task_request_collaboration`
- `TASK_ACCEPT_COLLABORATION` -> `handle_task_accept_collaboration`
- `DISCOVER_RESULT` -> `handle_discover_result`
- `ROUTE` -> `handle_route`

Error behavior:

- invalid JSON: log only
- unknown type: log only
- handler error: log only

### SETUP

Direction:

- Agent -> ACF

Example:

```json
{
  "type": "SETUP",
  "timestamp": "2025-01-01T00:00:00Z",
  "payload": {
    "src_agent_id": "did:acn:agent:001"
  }
}
```

Behavior:

1. Save connection under `payload.src_agent_id`.
2. Mark agent `online`.
3. Reply with:

```json
{
  "type": "SETUP",
  "timestamp": "<utc iso8601>",
  "payload": {
    "status": "OK"
  }
}
```

### PUBLISH_TRACK

Direction:

- Agent -> ACF

Current request fields:

- `payload.src_agent_id`
- `payload.task_id`
- `payload.track_list`

Behavior:

1. If `task_id` is missing, log and stop.
2. Deduplicate incoming track items by `(namespace, track)`.
3. Load `Track` by `task_id`.
4. Insert a new row or merge with existing `track_list`.
5. Update `src_agent_id`.

Database effect:

- insert or update `Track`

### START_TASK

Direction:

- Agent -> ACF
- ACF -> target agent

Current request field:

- `payload.dst_agent_id`

Behavior:

1. If `dst_agent_id` is missing, log and stop.
2. If the destination is online, forward the message as-is.
3. Otherwise only log.

### DISCONNECTION

Direction:

- Agent -> ACF

Current request field:

- `payload.src_agent_id`

Behavior:

1. Close the WebSocket.
2. Delete all `Track` rows where `src_agent_id` matches the disconnecting agent.
3. Remove the connection from memory.
4. Mark the agent `offline`.

Database effect:

- delete `Track`
- update `Agent.agent_status`

### TASK_REQUEST_COLLABORATION

Sources:

- `ARF` via `POST /acf/v1/discoveries`
- an agent via WebSocket

HTTP entry behavior:

1. Read `data["body"]`.
2. Call `forward_discovery(body)`.
3. Return `200 {"status": "OK"}`.

`forward_discovery(body)` builds this WebSocket message:

```json
{
  "type": "TASK_REQUEST_COLLABORATION",
  "timestamp": "<body.timestamp or current time>",
  "payload": {
    "...": "body copied as-is"
  }
}
```

Forwarding behavior:

1. Read `body.dst_agent_id`.
2. If missing, log and stop.
3. If the destination is online, send the message.
4. Otherwise only log.

### TASK_ACCEPT_COLLABORATION

Direction:

- Agent -> ACF
- ACF -> target agent

Current request fields:

- `payload.src_agent_id`
- `payload.dst_agent_id`
- `payload.task_id`

Behavior:

1. Receive the collaborator acceptance.
2. Build a new `DISCOVER_RESULT` message:

```json
{
  "type": "DISCOVER_RESULT",
  "timestamp": "<utc iso8601>",
  "payload": {
    "src_agent_id": "ARF",
    "dst_agent_id": "<payload.dst_agent_id>",
    "discover_result": ["<payload.src_agent_id>"]
  }
}
```

3. Forward it to the online agent in `dst_agent_id`.

Implementation notes:

- `task_id` is read but not included in the generated message.
- In current code, ACF generates this `DISCOVER_RESULT` on behalf of ARF.

### DISCOVER_RESULT

Direction:

- Agent or ACF internal flow -> target agent

Behavior:

1. Read `payload.dst_agent_id`.
2. If online, forward the message as-is.
3. Otherwise only log.

### ROUTE

Direction:

- Agent -> ACF
- ACF -> target agent

Current request field:

- `payload.dst_agent_id`

Behavior:

1. Read destination agent id.
2. If online, forward the full message as-is.
3. Otherwise only log.

Implementation note:

- `ROUTE` does not validate or rewrite payload content and does not touch the database.

### HTTP Task Execution Callback

Endpoint:

- `POST /acn-agent/v1/task-executions`

Source:

- forwarded by ARF

Current request fields:

- `data["body"]["task_id"]`
- `data["body"]["agent_id"]`

Behavior:

1. Query `Track` by `task_id`.
2. If no track exists, return success.
3. Treat `body.agent_id` as the destination agent.
4. If destination agent is offline, return success.
5. Send `SUBSCRIBE_TRACK` to that agent:

```json
{
  "type": "SUBSCRIBE_TRACK",
  "timestamp": "<utc iso8601>",
  "payload": {
    "src_agent_id": "ACF",
    "task_id": "<task_id>",
    "track_list": [
      {
        "namespace": "...",
        "track": "..."
      }
    ]
  }
}
```

Implementation note:

- The current meaning is: once ARF records task execution, ACF looks up published tracks for that task and actively asks the executing agent to subscribe.

### Agent Deletion

Endpoint:

- `POST /acn-agent/v1/agent-deletions`

Current request field:

- `data.get("agent_id")`

Behavior:

1. Delete `Track` rows with `src_agent_id=agent_id`.
2. Delete `Task` rows with `agent_id=agent_id`.
3. Delete the `Agent` row.
4. Close and remove the WebSocket connection if present.

### Clear

Endpoint:

- `POST /clear`

Behavior:

1. Send `CLEAR` to every connected agent:

```json
{
  "type": "CLEAR",
  "timestamp": "<utc iso8601>",
  "payload": {}
}
```

2. Close every WebSocket connection.
3. Clear `connections`.
4. Clear local `Track`, `Task`, and `Agent`.

## Typical End-To-End Flows

### Registration And Online State

1. Agent calls `ARF /arf/v1/agent-cards`.
2. ARF validates VC data and stores the `Agent`.
3. Agent connects to `ACF /acf/ws`.
4. Agent sends `SETUP`.
5. ACF saves the connection and marks the agent `online`.
6. ACF replies with `SETUP(status=OK)`.

### Discovery And Collaboration

1. Requester calls `ARF /arf/v1/agent-discoveries`.
2. ARF selects an online, available, capability-matching collaborator.
3. ARF calls `ACF /acf/v1/discoveries`.
4. ACF forwards `TASK_REQUEST_COLLABORATION` to the target agent.
5. The target agent sends `TASK_ACCEPT_COLLABORATION`.
6. ACF generates and forwards `DISCOVER_RESULT` to the requester-side target.

### Task Execution And Track Subscription

1. Publishing agent sends `PUBLISH_TRACK` to ACF.
2. ACF persists aggregated track metadata by `task_id`.
3. Executing agent reports task execution to ARF.
4. ARF upserts `Task` and forwards the callback to ACF.
5. ACF looks up `Track` by `task_id`.
6. ACF sends `SUBSCRIBE_TRACK` to the executing agent.

### Disconnection And Cleanup

1. Agent sends `DISCONNECTION` or the socket breaks.
2. ACF removes the in-memory connection and marks the agent `offline`.
3. On explicit `DISCONNECTION`, ACF also deletes that agent's track rows.
4. If an external caller invokes `ARF /clear`, ARF clears local state and forwards the clear request to ACF.
5. ACF broadcasts `CLEAR`, closes all sockets, and clears all local state.

## Current Implementation Notes

### Request Body Shape Is Not Fully Consistent

Different endpoints read fields from different levels:

- some use `data["body"]`
- some use `data.get("agent_id")`

Examples:

- `ARF /acn-agent/v1/agent-deletions`
- `ACF /acn-agent/v1/agent-deletions`

External callers must follow the current code path, not a presumed unified schema.

### ACF Handles Some Business-Level Message Construction

`DISCOVER_RESULT` is currently created inside `ACF.handle_task_accept_collaboration()` instead of being returned from ARF.

### Track State Is Aggregated Per Task

Because `Track.task_id` is unique, each task ends with a single aggregated track record.

### Many Failure Paths Log And Still Return Success

Examples:

- destination agent offline
- no `Track` found for a task
- ARF forwarding to ACF failed

This implementation favors non-blocking behavior over strict failure propagation.

## Quick Start

### Environment Setup

```bash
./setup.sh

# Or manually
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Running Services

```bash
python3 agent_gw.py

# Or individually
python -m agent_gw.arf_server
python -m agent_gw.acf_server
```

### Testing

```bash
pytest
pytest tests/test_models.py
pytest tests/test_integration.py
pytest --cov=. --cov-report=html --cov-report=term
```

## Project Structure

```text
acn_gw/
├── agent_gw/                 # Business application package
│   ├── arf_server.py
│   ├── acf_server.py
│   ├── main.py
│   ├── models.py
│   └── logger_config.py
├── moq/                      # MOQT protocol implementation
├── tests/                    # Test suite
├── docs/                     # Project documentation
├── requirements.txt
├── setup.sh
└── AGENTS.md
```
