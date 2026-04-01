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


app = FastAPI(title='ARF - Agent Repository Function')

IDM_URL = 'http://10.0.18.210:9020/idm/v1/vc-verifications'
ACF_DISCOVERIES_URL = 'http://localhost:9002/acf/v1/discoveries'
ACF_TASK_EXECUTIONS_URL = 'http://localhost:9002/acn-agent/v1/task-executions'
ACF_CLEAR_URL = 'http://localhost:9002/clear'
ACF_AGENT_DELETIONS_URL = 'http://localhost:9002/acn-agent/v1/agent-deletions'


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
    arf_logger.info(
        f'{direction} {source} -> {target}: {_format_log_payload(data)}'
    )


@app.post('/arf/v1/agent-cards')
async def register_agent_card(request: Request):
    """Register agent card - receives agent credentials and validates with IDM."""
    try:
        data = await request.json()
        _log_http_message('HTTP RECV', 'client', 'ARF /arf/v1/agent-cards', data)

        async with _create_http_client() as client:
            _log_http_message('HTTP SEND', 'ARF', IDM_URL, data)
            response = await client.post(IDM_URL, json=data)
            idm_result = response.json()
            _log_http_message(
                'HTTP RECV',
                IDM_URL,
                'ARF',
                {'status_code': response.status_code, 'body': idm_result},
            )

        is_valid = idm_result.get('valid', False)
        arf_logger.info(f'IDM verification result for agent card: {is_valid}')

        if not is_valid:
            return JSONResponse(
                status_code=400,
                content={'error': 'VC verification failed'},
            )

        agent_id = data.get('agent_id')
        body = data.get('body', {})
        vc_list = body.get('vc_list', [])
        agent_name = None
        capabilities = []

        for vc in vc_list:
            claims = vc.get('claims', {})
            if not agent_name:
                agent_name = claims.get('agent_name')

            agent_attr = claims.get('agent_attribute')
            if agent_attr and agent_attr not in capabilities:
                capabilities.append(agent_attr)

        if not agent_id:
            arf_logger.info('Agent card missing agent_id')
            return JSONResponse(
                status_code=400,
                content={'error': 'agent_id is required'},
            )

        db = get_db()
        try:
            existing_agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()

            if existing_agent:
                existing_agent.agent_name = agent_name
                existing_agent.agent_capability = capabilities
            else:
                new_agent = Agent(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    agent_capability=capabilities,
                    agent_status='offline',
                    priority=body.get('priority', 0),
                )
                db.add(new_agent)

            db.commit()
        finally:
            db.close()

        arf_logger.info(f'Agent {agent_id} registered with capabilities: {capabilities}')
        return JSONResponse(status_code=200, content={'status': 'OK'})
    except Exception as e:
        arf_logger.info(f'Error registering agent: {e}')
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/arf/v1/agent-discoveries')
async def discover_agents(request: Request):
    """Discover agents based on required capabilities."""
    try:
        data = await request.json()
        _log_http_message('HTTP RECV', 'client', 'ARF /arf/v1/agent-discoveries', data)
        body = data.get('body', {})

        requester_agent_id = body.get('agent_id')
        task_id = body.get('task_id')
        required_capabilities = body.get('required_capabilities', [])

        arf_logger.info(f'Discovery request from {requester_agent_id} for task {task_id}')

        asyncio.create_task(
            process_discovery(requester_agent_id, task_id, required_capabilities)
        )

        return JSONResponse(status_code=200, content={'status': 'OK'})
    except Exception as e:
        arf_logger.info(f'Error in discovery: {e}')
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/acn-agent/v1/task-executions')
async def handle_task_executions(request: Request):
    """Record task execution notifications from remote agents."""
    try:
        data = await request.json()
        _log_http_message(
            'HTTP RECV',
            'client',
            'ARF /acn-agent/v1/task-executions',
            data,
        )
        body = data.get('body', {})

        agent_id = body.get('agent_id')
        task_id = body.get('task_id')
        description = body.get('description')

        arf_logger.info(f'Received task execution from {agent_id} for task {task_id}')

        db = get_db()
        try:
            existing_task = db.query(Task).filter(
                Task.agent_id == agent_id,
                Task.task_id == task_id,
            ).first()

            if existing_task:
                existing_task.task_description = description
            else:
                db.add(Task(
                    agent_id=agent_id,
                    task_id=task_id,
                    task_description=description,
                ))

            db.commit()
        finally:
            db.close()

        try:
            async with _create_http_client() as client:
                _log_http_message('HTTP SEND', 'ARF', ACF_TASK_EXECUTIONS_URL, data)
                response = await client.post(ACF_TASK_EXECUTIONS_URL, json=data)
                _log_http_message(
                    'HTTP RECV',
                    ACF_TASK_EXECUTIONS_URL,
                    'ARF',
                    {'status_code': response.status_code},
                )
                arf_logger.info(
                    f'Forwarded task execution to ACF for {agent_id}: {response.status_code}'
                )
        except Exception as e:
            arf_logger.info(f'Error forwarding task execution to ACF: {e}')

        return JSONResponse(status_code=200, content={'status': 'OK'})
    except Exception as e:
        arf_logger.info(f'Error handling task execution: {e}')
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/acn-agent/v1/task-execution-terminations')
async def handle_task_execution_terminations(request: Request):
    """Remove task execution records when a remote agent reports termination."""
    try:
        data = await request.json()
        _log_http_message(
            'HTTP RECV',
            'client',
            'ARF /acn-agent/v1/task-execution-terminations',
            data,
        )
        body = data.get('body', {})

        agent_id = body.get('agent_id')
        task_id = body.get('task_id')

        arf_logger.info(
            f'Received task execution termination from {agent_id} for task {task_id}'
        )

        db = get_db()
        try:
            existing_task = db.query(Task).filter(
                Task.agent_id == agent_id,
                Task.task_id == task_id,
            ).first()

            if existing_task:
                db.delete(existing_task)
                db.commit()
            else:
                arf_logger.info(
                    f'No task record found for termination: agent_id={agent_id}, task_id={task_id}'
                )
        finally:
            db.close()

        return JSONResponse(status_code=200, content={'status': 'OK'})
    except Exception as e:
        arf_logger.info(f'Error handling task termination: {e}')
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/acn-agent/v1/agent-deletions')
async def handle_agent_deletions(request: Request):
    """Delete agent information locally and forward the request to ACF."""
    try:
        data = await request.json()
        _log_http_message(
            'HTTP RECV',
            'client',
            'ARF /acn-agent/v1/agent-deletions',
            data,
        )
        agent_id = data.get('agent_id')

        arf_logger.info(f'Received agent deletion for {agent_id}')

        db = get_db()
        try:
            db.query(Task).filter(Task.agent_id == agent_id).delete(
                synchronize_session=False
            )
            db.query(Agent).filter(Agent.agent_id == agent_id).delete(
                synchronize_session=False
            )
            db.commit()
        finally:
            db.close()

        try:
            async with _create_http_client() as client:
                _log_http_message('HTTP SEND', 'ARF', ACF_AGENT_DELETIONS_URL, data)
                response = await client.post(ACF_AGENT_DELETIONS_URL, json=data)
                _log_http_message(
                    'HTTP RECV',
                    ACF_AGENT_DELETIONS_URL,
                    'ARF',
                    {'status_code': response.status_code},
                )
                arf_logger.info(
                    f'Forwarded agent deletion to ACF for {agent_id}: {response.status_code}'
                )
        except Exception as e:
            arf_logger.info(f'Error forwarding agent deletion to ACF: {e}')

        return JSONResponse(status_code=200, content={'status': 'OK'})
    except Exception as e:
        arf_logger.info(f'Error handling agent deletion: {e}')
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/clear')
async def clear_environment(request: Request):
    """Clear local state and forward the clear request to ACF."""
    try:
        data = await request.json()
        _log_http_message('HTTP RECV', 'client', 'ARF /clear', data)
        arf_logger.info('Received clear request')

        db = get_db()
        try:
            db.query(Task).filter(Task.id.isnot(None)).delete(
                synchronize_session=False
            )
            db.query(Track).filter(Track.id.isnot(None)).delete(
                synchronize_session=False
            )
            db.query(Agent).filter(Agent.agent_id.isnot(None)).delete(
                synchronize_session=False
            )
            db.commit()
        finally:
            db.close()

        try:
            async with _create_http_client() as client:
                clear_request = {'method': 'POST', 'url': '/clear', 'body': {}}
                _log_http_message('HTTP SEND', 'ARF', ACF_CLEAR_URL, clear_request)
                response = await client.post(
                    ACF_CLEAR_URL,
                    json=clear_request,
                )
                _log_http_message(
                    'HTTP RECV',
                    ACF_CLEAR_URL,
                    'ARF',
                    {'status_code': response.status_code},
                )
                arf_logger.info(
                    f'Forwarded clear request to ACF: {response.status_code}'
                )
        except Exception as e:
            arf_logger.info(f'Error forwarding clear request to ACF: {e}')

        return JSONResponse(status_code=200, content={'status': 'OK'})
    except Exception as e:
        arf_logger.info(f'Error handling clear request: {e}')
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
            'TASK START',
            'ARF',
            'discovery processor',
            {
                'requester_agent_id': requester_agent_id,
                'task_id': task_id,
                'required_capabilities': required_capabilities,
            },
        )
        agents_in_tasks = db.query(Task.agent_id).distinct().all()
        agents_in_tasks = [agent_id for (agent_id,) in agents_in_tasks]

        candidates = db.query(Agent).filter(
            Agent.agent_status == 'online',
            Agent.agent_id.notin_(agents_in_tasks) if agents_in_tasks else True,
            Agent.agent_id != requester_agent_id,
        ).all()

        if not candidates:
            arf_logger.info('No available agents found for discovery')
            return

        scored_agents = []
        for agent in candidates:
            if agent.agent_capability:
                matching_caps = set(agent.agent_capability) & set(required_capabilities)
                score = len(matching_caps)
                if score > 0:
                    scored_agents.append((agent, score))

        if not scored_agents:
            arf_logger.info('No agents with matching capabilities found')
            return

        scored_agents.sort(key=lambda item: (-item[0].priority, -item[1]))
        selected_agent = scored_agents[0][0]

        arf_logger.info(f'Selected agent {selected_agent.agent_id} for collaboration')

        collab_msg = {
            'method': 'POST',
            'url': '/acf/v1/discoveries',
            'headers': {
                'Content-Type': 'application/json',
            },
            'body': {
                'src_agent_id': 'ARF',
                'dst_agent_id': selected_agent.agent_id,
                'task_id': task_id,
                'task_description': 'Collaboration task',
                'agent_card': {
                    'agent_id': selected_agent.agent_id,
                    'skill': selected_agent.agent_capability or [],
                },
                'timestamp': datetime.utcnow().isoformat() + 'Z',
            },
        }

        async with _create_http_client() as client:
            _log_http_message('HTTP SEND', 'ARF', ACF_DISCOVERIES_URL, collab_msg)
            response = await client.post(ACF_DISCOVERIES_URL, json=collab_msg)
            _log_http_message(
                'HTTP RECV',
                ACF_DISCOVERIES_URL,
                'ARF',
                {'status_code': response.status_code},
            )
            arf_logger.info(
                f'Sent discovery request to ACF for {selected_agent.agent_id}: {response.status_code}'
            )
    except Exception as e:
        arf_logger.info(f'Error processing discovery: {e}')
    finally:
        db.close()


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=9001)
