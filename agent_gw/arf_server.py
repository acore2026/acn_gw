#!/usr/bin/env python3
"""
ARF - Agent Repository Function
HTTP server on port 9001
Handles agent registration, discovery, and task lifecycle
"""

import asyncio
import json
from datetime import datetime
from typing import List

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .logger_config import arf_logger
from .models import Agent, Task, Track, get_db


app = FastAPI(title="ARF - Agent Repository Function")

IDM_URL = "http://10.0.18.210:9020/idm/v1/vc-verifications"
ELEMENT_LOGS_URL = "http://localhost:9005/acn/v3/element-logs"
ACF_DISCOVERIES_URL = "http://localhost:9002/acf/v1/discoveries"
ACF_TASK_EXECUTIONS_URL = "http://localhost:9002/acn-agent/v1/task-executions"
ACF_CLEAR_URL = "http://localhost:9002/clear"
ACF_AGENT_DELETIONS_URL = "http://localhost:9002/acn-agent/v1/agent-deletions"
ACF_TASK_TERMINATION_URL = "http://localhost:9002/acf/v1/task-termination"
ACN_AGENT_CLEAR_URL = "http://localhost:9010/clear"


def _create_http_client():
    """Create an HTTP client that ignores ambient proxy settings by default."""
    return httpx.AsyncClient(trust_env=False)


def _format_log_payload(data):
    """Serialize payloads for structured message logging."""
    try:
        return json.dumps(data, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(data)


def _log_http_message(direction, source, target, data):
    """Log HTTP traffic to and from surrounding components."""
    arf_logger.info(f"{direction} {source} -> {target}: {_format_log_payload(data)}")


def _serialize_agent(agent: Agent):
    """Build a compact log-friendly snapshot for an agent row."""
    return {
        "agent_id": agent.agent_id,
        "agent_name": agent.agent_name,
        "agent_status": agent.agent_status,
        "agent_capability": agent.agent_capability or [],
        "priority": agent.priority,
    }


def _serialize_agent_log(agent: Agent):
    """Build the element-log content for an agent row."""
    return {
        "agent_name": agent.agent_name,
        "agent_id": agent.agent_id,
        "agent_capability": agent.agent_capability or [],
        "agent_status": agent.agent_status,
        "priority": agent.priority,
        "consent": {
            "need_consumer_ue_authorization": False,
            "need_producer_authorization": True,
            "support_producer_ue_authorization": False,
        },
    }


def _serialize_track(track: Track):
    """Build a compact snapshot for a track row before deletion."""
    return {
        "src_agent_id": track.src_agent_id,
        "task_id": track.task_id,
        "track_list": track.track_list or [],
    }


def _serialize_task(task: Task):
    """Build a compact snapshot for a task row."""
    return {
        "agent_id": task.agent_id,
        "task_id": task.task_id,
        "task_description": task.task_description,
    }


def _build_agent_info_response(agent: Agent):
    """Build the /arf/v1/agent-info response payload."""
    return {
        "agent_id": agent.agent_id,
        "agent_name": agent.agent_name,
        "agent_status": agent.agent_status,
        "agent_capabilities": agent.agent_capability or [],
        "priority": agent.priority,
    }


def _build_agent_log_request(log_type, agent_snapshot):
    """Build a PublishAgent/DeleteAgent element log request."""
    return {
        "method": "POST",
        "url": "/acn/v3/element-logs",
        "headers": {
            "Content-Type": "application/json",
        },
        "body": {
            "element_id": "AgentGW",
            "log_type": log_type,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "content": agent_snapshot,
        },
    }


def _build_task_log_request(log_type, task_snapshot):
    """Build a TaskExecution/TaskExecutionTermination element log request."""
    return {
        "method": "POST",
        "url": "/acn/v3/element-logs",
        "headers": {
            "Content-Type": "application/json",
        },
        "body": {
            "element_id": "AgentGW",
            "log_type": log_type,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "content": {
                "agent_id": task_snapshot["agent_id"],
                "task_id": task_snapshot["task_id"],
                "task_description": task_snapshot["task_description"],
            },
        },
    }


def _build_publisher_track_log_request(log_type, track_snapshot):
    """Build a PublisherTrackAdd/PublisherTrackDel element log request."""
    return {
        "method": "POST",
        "url": "/acn/v3/element-logs",
        "headers": {
            "Content-Type": "application/json",
        },
        "body": {
            "element_id": "AgentGW",
            "log_type": log_type,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "content": {
                "src_agent_id": track_snapshot["src_agent_id"],
                "task_id": track_snapshot["task_id"],
                "track_list": track_snapshot["track_list"],
            },
        },
    }


async def _send_agent_log(log_type, agent_snapshot):
    """Send an agent table element log without failing the main flow."""
    agent_log = _build_agent_log_request(log_type, agent_snapshot)
    try:
        async with _create_http_client() as client:
            _log_http_message("HTTP SEND", "ARF", ELEMENT_LOGS_URL, agent_log)
            response = await client.post(ELEMENT_LOGS_URL, json=agent_log)
            _log_http_message(
                "HTTP RECV",
                ELEMENT_LOGS_URL,
                "ARF",
                {"status_code": response.status_code},
            )
            arf_logger.info(
                f"Sent {log_type} for agent_id={agent_snapshot['agent_id']}: "
                f"{response.status_code}"
            )
    except Exception as e:
        arf_logger.info(
            f"Error sending {log_type} for agent_id={agent_snapshot['agent_id']}: {e}"
        )


async def _send_agent_del_logs(agent_snapshots):
    for agent_snapshot in agent_snapshots:
        await _send_agent_log("DeleteAgent", agent_snapshot)


async def _send_task_log(log_type, task_snapshot):
    """Send a task lifecycle element log without failing the main flow."""
    task_log = _build_task_log_request(log_type, task_snapshot)
    try:
        async with _create_http_client() as client:
            _log_http_message("HTTP SEND", "ARF", ELEMENT_LOGS_URL, task_log)
            response = await client.post(ELEMENT_LOGS_URL, json=task_log)
            _log_http_message(
                "HTTP RECV",
                ELEMENT_LOGS_URL,
                "ARF",
                {"status_code": response.status_code},
            )
            arf_logger.info(
                f"Sent {log_type} for task={task_snapshot['task_id']} "
                f"agent_id={task_snapshot['agent_id']}: {response.status_code}"
            )
    except Exception as e:
        arf_logger.info(
            f"Error sending {log_type} for task={task_snapshot['task_id']} "
            f"agent_id={task_snapshot['agent_id']}: {e}"
        )


async def _send_task_del_logs(task_snapshots):
    for task_snapshot in task_snapshots:
        await _send_task_log("TaskExecutionTermination", task_snapshot)


def _get_agent_card_body(data):
    """Support both wrapped and flat agent-card payloads."""
    body = data.get("body")
    return body if isinstance(body, dict) else data


def _get_request_body(data):
    """Support both wrapped and flat request payloads."""
    body = data.get("body")
    return body if isinstance(body, dict) else data


def cleanup_dirty_data():
    """Remove persisted rows that break discovery semantics."""
    db = get_db()
    try:
        deleted_null_task_agents = (
            db.query(Task)
            .filter(Task.agent_id.is_(None))
            .delete(synchronize_session=False)
        )
        db.commit()
        arf_logger.info(
            f"Initialization cleanup removed {deleted_null_task_agents} task rows with null agent_id"
        )
    finally:
        db.close()


@app.on_event("startup")
async def startup_cleanup():
    """Clean persisted dirty data before serving requests."""
    cleanup_dirty_data()


@app.post("/arf/v1/agent-cards")
async def register_agent_card(request: Request):
    """Register agent card - receives agent credentials and validates with IDM."""
    try:
        data = await request.json()
        _log_http_message("HTTP RECV", "client", "ARF /arf/v1/agent-cards", data)

        async with _create_http_client() as client:
            _log_http_message("HTTP SEND", "ARF", IDM_URL, data)
            response = await client.post(IDM_URL, json=data)
            idm_result = response.json()
            _log_http_message(
                "HTTP RECV",
                IDM_URL,
                "ARF",
                {"status_code": response.status_code, "body": idm_result},
            )

        is_valid = idm_result.get("valid", False)
        arf_logger.info(f"IDM verification result for agent card: {is_valid}")

        if not is_valid:
            return JSONResponse(
                status_code=400,
                content={"error": "VC verification failed"},
            )

        agent_id = data.get("agent_id")
        body = _get_agent_card_body(data)
        vc_list = body.get("vc_list", [])
        agent_name = None
        capabilities = []
        priority = body.get("priority", 0)

        for vc in vc_list:
            claims = vc.get("claims", {})
            if not agent_name:
                agent_name = claims.get("agent_name")

            agent_attr = claims.get("agent_attribute")
            if agent_attr and agent_attr not in capabilities:
                capabilities.append(agent_attr)

        if not agent_id:
            arf_logger.info("Agent card missing agent_id")
            return JSONResponse(
                status_code=400,
                content={"error": "agent_id is required"},
            )

        db = get_db()
        agent_snapshot = None
        try:
            existing_agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()

            if existing_agent:
                existing_agent.agent_name = agent_name
                existing_agent.agent_capability = capabilities
                existing_agent.priority = priority
                existing_agent.agent_status = existing_agent.agent_status or "offline"
                agent_snapshot = _serialize_agent_log(existing_agent)
            else:
                new_agent = Agent(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    agent_capability=capabilities,
                    agent_status="offline",
                    priority=priority,
                )
                db.add(new_agent)
                agent_snapshot = _serialize_agent_log(new_agent)

            db.commit()
        finally:
            db.close()

        arf_logger.info(
            f"Agent {agent_id} registered with capabilities: {capabilities}"
        )

        await _send_agent_log("PublishAgent", agent_snapshot)

        return JSONResponse(status_code=200, content={"status": "OK"})
    except Exception as e:
        arf_logger.info(f"Error registering agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/arf/v1/agent-discoveries")
async def discover_agents(request: Request):
    """Discover agents based on required capabilities."""
    try:
        data = await request.json()
        _log_http_message("HTTP RECV", "client", "ARF /arf/v1/agent-discoveries", data)
        body = _get_request_body(data)

        requester_agent_id = body.get("agent_id")
        task_id = body.get("task_id")
        required_capabilities = body.get("required_capabilities", [])

        arf_logger.info(
            f"Discovery request from {requester_agent_id} for task {task_id}"
        )

        asyncio.create_task(
            process_discovery(requester_agent_id, task_id, required_capabilities)
        )

        return JSONResponse(status_code=200, content={"status": "OK"})
    except Exception as e:
        arf_logger.info(f"Error in discovery: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/arf/v1/agent-info")
async def get_agent_info(request: Request):
    """Return locally stored agent info for the requested agent_id."""
    try:
        data = await request.json()
        _log_http_message("HTTP RECV", "client", "ARF /arf/v1/agent-info", data)
        body = _get_request_body(data)
        agent_id = body.get("agent_id")

        if not agent_id:
            arf_logger.info("Agent info request missing agent_id")
            return JSONResponse(status_code=200, content={})

        db = get_db()
        try:
            agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
        finally:
            db.close()

        if not agent:
            arf_logger.info(f"Agent info not found for {agent_id}")
            return JSONResponse(status_code=200, content={})

        response_payload = _build_agent_info_response(agent)
        _log_http_message("HTTP SEND", "ARF", "client", response_payload)
        return JSONResponse(status_code=200, content=response_payload)
    except Exception as e:
        arf_logger.info(f"Error getting agent info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/acn-agent/v1/task-executions")
async def handle_task_executions(request: Request):
    """Record task execution notifications from remote agents."""
    try:
        data = await request.json()
        _log_http_message(
            "HTTP RECV",
            "client",
            "ARF /acn-agent/v1/task-executions",
            data,
        )
        body = _get_request_body(data)

        agent_id = body.get("agent_id")
        task_id = body.get("task_id")
        description = body.get("description")

        arf_logger.info(f"Received task execution from {agent_id} for task {task_id}")

        db = get_db()
        task_snapshot = None
        try:
            existing_task = (
                db.query(Task)
                .filter(
                    Task.agent_id == agent_id,
                    Task.task_id == task_id,
                )
                .first()
            )

            if existing_task:
                existing_task.task_description = description
                task_snapshot = _serialize_task(existing_task)
            else:
                new_task = Task(
                    agent_id=agent_id,
                    task_id=task_id,
                    task_description=description,
                )
                db.add(new_task)
                task_snapshot = _serialize_task(new_task)

            db.commit()
        finally:
            db.close()

        await _send_task_log("TaskExecution", task_snapshot)

        try:
            async with _create_http_client() as client:
                _log_http_message("HTTP SEND", "ARF", ACF_TASK_EXECUTIONS_URL, data)
                response = await client.post(ACF_TASK_EXECUTIONS_URL, json=data)
                _log_http_message(
                    "HTTP RECV",
                    ACF_TASK_EXECUTIONS_URL,
                    "ARF",
                    {"status_code": response.status_code},
                )
                arf_logger.info(
                    f"Forwarded task execution to ACF for {agent_id}: {response.status_code}"
                )
        except Exception as e:
            arf_logger.info(f"Error forwarding task execution to ACF: {e}")

        return JSONResponse(status_code=200, content={"status": "OK"})
    except Exception as e:
        arf_logger.info(f"Error handling task execution: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/acn-agent/v1/task-execution-terminations")
async def handle_task_execution_terminations(request: Request):
    """Remove task execution records when a remote agent reports termination."""
    try:
        data = await request.json()
        _log_http_message(
            "HTTP RECV",
            "client",
            "ARF /acn-agent/v1/task-execution-terminations",
            data,
        )
        body = _get_request_body(data)

        agent_id = body.get("agent_id")
        task_id = body.get("task_id")

        arf_logger.info(
            f"Received task execution termination from {agent_id} for task {task_id}"
        )

        db = get_db()
        task_snapshot = None
        try:
            existing_task = (
                db.query(Task)
                .filter(
                    Task.agent_id == agent_id,
                    Task.task_id == task_id,
                )
                .first()
            )

            if existing_task:
                task_snapshot = _serialize_task(existing_task)
                db.delete(existing_task)
                db.commit()
            else:
                arf_logger.info(
                    f"No task record found for termination: agent_id={agent_id}, task_id={task_id}"
                )
        finally:
            db.close()

        if task_snapshot:
            await _send_task_log("TaskExecutionTermination", task_snapshot)

        return JSONResponse(status_code=200, content={"status": "OK"})
    except Exception as e:
        arf_logger.info(f"Error handling task termination: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/acn-agent/v1/task-termination-broadcasts")
async def handle_task_termination_broadcasts(request: Request):
    """Receive task termination broadcast and forward to ACF."""
    try:
        data = await request.json()
        _log_http_message(
            "HTTP RECV",
            "client",
            "ARF /acn-agent/v1/task-termination-broadcasts",
            data,
        )
        body = _get_request_body(data)

        task_id = body.get("task_id")
        agent_id = body.get("agent_id")
        reason = body.get("reason", "")

        arf_logger.info(
            f"Received task termination broadcast from {agent_id} for task {task_id}"
        )

        db = get_db()
        try:
            task_snapshots = [
                _serialize_task(task)
                for task in db.query(Task).filter(Task.task_id == task_id).all()
            ]
            db.query(Task).filter(Task.task_id == task_id).delete(
                synchronize_session=False
            )
            db.commit()
            arf_logger.info(f"Deleted task records for task_id={task_id}")
        finally:
            db.close()

        await _send_task_del_logs(task_snapshots)

        try:
            termination_request = {
                "method": "POST",
                "url": "/acf/v1/task-termination",
                "headers": {
                    "Content-Type": "application/json",
                },
                "body": {
                    "src_agent_id": agent_id,
                    "terminated_agents": [],
                    "task_id": task_id,
                    "task_description": reason,
                    "timestamp": body.get(
                        "timestamp", datetime.utcnow().isoformat() + "Z"
                    ),
                },
            }
            async with _create_http_client() as client:
                _log_http_message(
                    "HTTP SEND", "ARF", ACF_TASK_TERMINATION_URL, termination_request
                )
                response = await client.post(
                    ACF_TASK_TERMINATION_URL,
                    json=termination_request,
                )
                _log_http_message(
                    "HTTP RECV",
                    ACF_TASK_TERMINATION_URL,
                    "ARF",
                    {"status_code": response.status_code},
                )
                arf_logger.info(
                    f"Forwarded task termination to ACF for task {task_id}: {response.status_code}"
                )
        except Exception as e:
            arf_logger.info(f"Error forwarding task termination to ACF: {e}")

        return JSONResponse(status_code=200, content={"status": "OK"})
    except Exception as e:
        arf_logger.info(f"Error handling task termination broadcast: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/acn-agent/v1/agent-deletions")
async def handle_agent_deletions(request: Request):
    """Delete agent information locally and forward the request to ACF."""
    try:
        data = await request.json()
        _log_http_message(
            "HTTP RECV",
            "client",
            "ARF /acn-agent/v1/agent-deletions",
            data,
        )
        body = _get_request_body(data)
        agent_id = body.get("agent_id")

        arf_logger.info(f"Received agent deletion for {agent_id}")

        db = get_db()
        try:
            agent_snapshots = [
                _serialize_agent_log(agent)
                for agent in db.query(Agent).filter(Agent.agent_id == agent_id).all()
            ]
            task_snapshots = [
                _serialize_task(task)
                for task in db.query(Task).filter(Task.agent_id == agent_id).all()
            ]
            db.query(Task).filter(Task.agent_id == agent_id).delete(
                synchronize_session=False
            )
            db.query(Agent).filter(Agent.agent_id == agent_id).delete(
                synchronize_session=False
            )
            db.commit()
        finally:
            db.close()

        await _send_task_del_logs(task_snapshots)
        await _send_agent_del_logs(agent_snapshots)

        try:
            async with _create_http_client() as client:
                _log_http_message("HTTP SEND", "ARF", ACF_AGENT_DELETIONS_URL, data)
                response = await client.post(ACF_AGENT_DELETIONS_URL, json=data)
                _log_http_message(
                    "HTTP RECV",
                    ACF_AGENT_DELETIONS_URL,
                    "ARF",
                    {"status_code": response.status_code},
                )
                arf_logger.info(
                    f"Forwarded agent deletion to ACF for {agent_id}: {response.status_code}"
                )
        except Exception as e:
            arf_logger.info(f"Error forwarding agent deletion to ACF: {e}")

        return JSONResponse(status_code=200, content={"status": "OK"})
    except Exception as e:
        arf_logger.info(f"Error handling agent deletion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/clear")
async def clear_environment(request: Request):
    """Clear local state and forward the clear request to ACF."""
    try:
        data = await request.json()
        _log_http_message("HTTP RECV", "client", "ARF /clear", data)
        _get_request_body(data)
        arf_logger.info("Received clear request")

        db = get_db()
        try:
            agent_snapshots = [
                _serialize_agent_log(agent)
                for agent in db.query(Agent).filter(Agent.agent_id.isnot(None)).all()
            ]
            task_snapshots = [
                _serialize_task(task)
                for task in db.query(Task).filter(Task.id.isnot(None)).all()
            ]
            track_snapshots = [
                _serialize_track(track)
                for track in db.query(Track).filter(Track.id.isnot(None)).all()
            ]
            db.query(Task).filter(Task.id.isnot(None)).delete(synchronize_session=False)
            db.query(Track).filter(Track.id.isnot(None)).delete(
                synchronize_session=False
            )
            db.query(Agent).filter(Agent.agent_id.isnot(None)).delete(
                synchronize_session=False
            )
            db.commit()
        finally:
            db.close()

        await _send_task_del_logs(task_snapshots)
        await _send_agent_del_logs(agent_snapshots)

        for track_snapshot in track_snapshots:
            try:
                async with _create_http_client() as client:
                    track_log = _build_publisher_track_log_request(
                        "PublisherTrackDel",
                        track_snapshot,
                    )
                    _log_http_message("HTTP SEND", "ARF", ELEMENT_LOGS_URL, track_log)
                    response = await client.post(ELEMENT_LOGS_URL, json=track_log)
                    _log_http_message(
                        "HTTP RECV",
                        ELEMENT_LOGS_URL,
                        "ARF",
                        {"status_code": response.status_code},
                    )
                    arf_logger.info(
                        "Sent PublisherTrackDel for "
                        f"task={track_snapshot['task_id']} "
                        f"src_agent_id={track_snapshot['src_agent_id']}: "
                        f"{response.status_code}"
                    )
            except Exception as e:
                arf_logger.info(
                    "Error sending PublisherTrackDel for "
                    f"task={track_snapshot['task_id']} "
                    f"src_agent_id={track_snapshot['src_agent_id']}: {e}"
                )

        try:
            async with _create_http_client() as client:
                clear_request = {"method": "POST", "url": "/clear", "body": {}}
                _log_http_message("HTTP SEND", "ARF", ACF_CLEAR_URL, clear_request)
                response = await client.post(
                    ACF_CLEAR_URL,
                    json=clear_request,
                )
                _log_http_message(
                    "HTTP RECV",
                    ACF_CLEAR_URL,
                    "ARF",
                    {"status_code": response.status_code},
                )
                arf_logger.info(
                    f"Forwarded clear request to ACF: {response.status_code}"
                )
        except Exception as e:
            arf_logger.info(f"Error forwarding clear request to ACF: {e}")

        try:
            async with _create_http_client() as client:
                clear_request = {"method": "POST", "url": "/clear", "body": {}}
                _log_http_message(
                    "HTTP SEND", "ARF", ACN_AGENT_CLEAR_URL, clear_request
                )
                response = await client.post(
                    ACN_AGENT_CLEAR_URL,
                    json=clear_request,
                )
                _log_http_message(
                    "HTTP RECV",
                    ACN_AGENT_CLEAR_URL,
                    "ARF",
                    {"status_code": response.status_code},
                )
                arf_logger.info(
                    f"Forwarded clear request to ACN Agent: {response.status_code}"
                )
        except Exception as e:
            arf_logger.info(f"Error forwarding clear request to ACN Agent: {e}")

        return JSONResponse(status_code=200, content={"status": "OK"})
    except Exception as e:
        arf_logger.info(f"Error handling clear request: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def process_discovery(
    requester_agent_id: str,
    task_id: str,
    required_capabilities: List[str],
):
    """Process discovery asynchronously."""
    db = get_db()

    try:
        _log_http_message(
            "TASK START",
            "ARF",
            "discovery processor",
            {
                "requester_agent_id": requester_agent_id,
                "task_id": task_id,
                "required_capabilities": required_capabilities,
            },
        )
        agents_in_tasks = (
            db.query(Task.agent_id).filter(Task.agent_id.isnot(None)).distinct().all()
        )
        agents_in_tasks = [agent_id for (agent_id,) in agents_in_tasks]

        candidates = (
            db.query(Agent)
            .filter(
                Agent.agent_status == "online",
                Agent.agent_id.notin_(agents_in_tasks) if agents_in_tasks else True,
                Agent.agent_id != requester_agent_id,
            )
            .all()
        )

        if not candidates:
            saved_agents = db.query(Agent).order_by(Agent.agent_id).all()
            discovery_snapshot = {
                "requester_agent_id": requester_agent_id,
                "task_id": task_id,
                "required_capabilities": required_capabilities,
                "agents_in_tasks": agents_in_tasks,
                "saved_agents": [_serialize_agent(agent) for agent in saved_agents],
            }
            arf_logger.info(
                "No available agents found for discovery: "
                f"{_format_log_payload(discovery_snapshot)}"
            )
            return

        scored_agents = []
        for agent in candidates:
            if agent.agent_capability:
                matching_caps = set(agent.agent_capability) & set(required_capabilities)
                score = len(matching_caps)
                if score > 0:
                    scored_agents.append((agent, score))

        if not scored_agents:
            arf_logger.info("No agents with matching capabilities found")
            return

        scored_agents.sort(key=lambda item: (-item[0].priority, -item[1]))
        selected_agent = scored_agents[0][0]
        requester_agent = (
            db.query(Agent).filter(Agent.agent_id == requester_agent_id).first()
        )

        arf_logger.info(f"Selected agent {selected_agent.agent_id} for collaboration")

        collab_msg = {
            "method": "POST",
            "url": "/acf/v1/discoveries",
            "headers": {
                "Content-Type": "application/json",
            },
            "body": {
                "src_agent_id": requester_agent_id,
                "dst_agent_id": selected_agent.agent_id,
                "task_id": task_id,
                "task_description": "Collaboration task",
                "agent_card": {
                    "agent_id": requester_agent_id,
                    "skill": (
                        requester_agent.agent_capability if requester_agent else []
                    )
                    or [],
                },
                "timestamp": datetime.utcnow().isoformat() + "Z",
            },
        }

        async with _create_http_client() as client:
            _log_http_message("HTTP SEND", "ARF", ACF_DISCOVERIES_URL, collab_msg)
            response = await client.post(ACF_DISCOVERIES_URL, json=collab_msg)
            _log_http_message(
                "HTTP RECV",
                ACF_DISCOVERIES_URL,
                "ARF",
                {"status_code": response.status_code},
            )
            arf_logger.info(
                f"Sent discovery request to ACF for {selected_agent.agent_id}: {response.status_code}"
            )
    except Exception as e:
        arf_logger.info(f"Error processing discovery: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9001)
