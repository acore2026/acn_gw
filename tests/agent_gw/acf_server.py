#!/usr/bin/env python3
"""
ACF - Agent Communication Function
HTTP + WebSocket server on port 9002
Manages WebSocket connections for agents and discovery requests from ARF
"""

import asyncio
import json
from datetime import datetime

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from .logger_config import acf_logger
from .models import Agent, Task, Track, get_db


def _format_log_payload(data):
    """Serialize payloads for structured message logging."""
    try:
        return json.dumps(data, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(data)


def _log_message(direction, source, target, data):
    """Log a message exchanged with a surrounding component."""
    acf_logger.info(
        f'{direction} {source} -> {target}: {_format_log_payload(data)}'
    )


class ACFServer:
    def __init__(self, host='0.0.0.0', port=9002):
        self.host = host
        self.port = port
        self.connections = {}  # Map: agent_id -> websocket
        self.app = FastAPI(title='ACF - Agent Communication Function')

        self.app.post('/acf/v1/discoveries')(self.handle_discoveries)
        self.app.post('/acn-agent/v1/task-executions')(self.handle_task_executions)
        self.app.post('/clear')(self.handle_clear)
        self.app.post('/acn-agent/v1/agent-deletions')(self.handle_agent_deletions)
        self.app.websocket('/acf/ws')(self.websocket_endpoint)

    async def _send_json(self, websocket, data, target=None):
        message = json.dumps(data)
        _log_message('WS SEND', 'ACF', target or 'websocket', data)
        if hasattr(websocket, 'send_text'):
            await websocket.send_text(message)
        else:
            await websocket.send(message)

    async def _process_message(self, websocket, message, agent_id=None):
        try:
            data = json.loads(message)
            msg_type = data.get('type')
            source = agent_id or data.get('payload', {}).get('src_agent_id') or 'unknown'
            _log_message('WS RECV', source, 'ACF', data)

            if msg_type == 'SETUP':
                await self.handle_setup(websocket, data)
                return data['payload']['src_agent_id']
            elif msg_type == 'PUBLISH_TRACK':
                await self.handle_publish_track(data)
            elif msg_type == 'START_TASK':
                await self.handle_start_task(data)
            elif msg_type == 'DISCONNECTION':
                await self.handle_disconnection(websocket, data, agent_id)
                return None
            elif msg_type == 'TASK_REQUEST_COLLABORATION':
                await self.handle_task_request_collaboration(data)
            elif msg_type == 'TASK_ACCEPT_COLLABORATION':
                await self.handle_task_accept_collaboration(data)
            elif msg_type == 'DISCOVER_RESULT':
                await self.handle_discover_result(data)
            elif msg_type == 'ROUTE':
                await self.handle_route(data)
            else:
                acf_logger.info(f'Unknown message type: {msg_type}')
        except json.JSONDecodeError:
            acf_logger.info('Invalid JSON received')
        except Exception as e:
            acf_logger.info(f'Error processing message: {e}')

        return agent_id

    async def handle_websocket(self, websocket, path=None):
        """Compatibility handler used by tests and legacy websocket flows."""
        agent_id = None
        try:
            async for message in websocket:
                agent_id = await self._process_message(websocket, message, agent_id)
        except Exception as e:
            acf_logger.info(f'Error in websocket handler: {e}')
        finally:
            if agent_id and agent_id in self.connections:
                del self.connections[agent_id]
                db = get_db()
                agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
                if agent:
                    agent.agent_status = 'offline'
                    db.commit()
                db.close()
                acf_logger.info(f'Agent {agent_id} disconnected')

    async def websocket_endpoint(self, websocket: WebSocket):
        """FastAPI websocket endpoint for connected agents."""
        await websocket.accept()
        agent_id = None
        try:
            while True:
                message = await websocket.receive_text()
                agent_id = await self._process_message(websocket, message, agent_id)
        except WebSocketDisconnect:
            pass
        finally:
            if agent_id and agent_id in self.connections:
                del self.connections[agent_id]
                db = get_db()
                agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
                if agent:
                    agent.agent_status = 'offline'
                    db.commit()
                db.close()
                acf_logger.info(f'Agent {agent_id} disconnected')

    async def handle_setup(self, websocket, data):
        """Handle SETUP message from agent."""
        agent_id = data['payload']['src_agent_id']
        self.connections[agent_id] = websocket

        db = get_db()
        agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
        if agent:
            agent.agent_status = 'online'
            db.commit()
        db.close()

        acf_logger.info(f'Agent {agent_id} connected and status set to online')

        response = {
            'type': 'SETUP',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'payload': {
                'status': 'OK',
            },
        }
        await self._send_json(websocket, response, target=agent_id)

    async def handle_discoveries(self, request: Request):
        """Handle discovery HTTP requests from ARF."""
        try:
            data = await request.json()
            _log_message('HTTP RECV', 'ARF', 'ACF /acf/v1/discoveries', data)
            body = data.get('body', {})
            await self.forward_discovery(body)
            return JSONResponse(status_code=200, content={'status': 'OK'})
        except Exception as e:
            acf_logger.info(f'Error handling discovery request: {e}')
            raise HTTPException(status_code=500, detail=str(e))

    async def handle_task_executions(self, request: Request):
        """Handle task execution notifications forwarded from ARF."""
        try:
            data = await request.json()
            _log_message(
                'HTTP RECV',
                'ARF',
                'ACF /acn-agent/v1/task-executions',
                data,
            )
            body = data.get('body', {})
            task_id = body.get('task_id')
            agent_id = body.get('agent_id')

            db = get_db()
            try:
                track_record = db.query(Track).filter(Track.task_id == task_id).first()
                if not track_record:
                    acf_logger.info(f'No track mapping found for task {task_id}')
                    return JSONResponse(status_code=200, content={'status': 'OK'})

                target_agent_id = agent_id
                if target_agent_id not in self.connections:
                    acf_logger.info(f'Destination agent {target_agent_id} not connected')
                    return JSONResponse(status_code=200, content={'status': 'OK'})

                subscribe_msg = {
                    'type': 'SUBSCRIBE_TRACK',
                    'timestamp': datetime.utcnow().isoformat() + 'Z',
                    'payload': {
                        'src_agent_id': 'ACF',
                        'task_id': task_id,
                        'track_list': track_record.track_list or [],
                    },
                }
                await self._send_json(
                    self.connections[target_agent_id],
                    subscribe_msg,
                    target=target_agent_id,
                )
                acf_logger.info(f'Forwarded SUBSCRIBE_TRACK to {target_agent_id}')
            finally:
                db.close()

            return JSONResponse(status_code=200, content={'status': 'OK'})
        except Exception as e:
            acf_logger.info(f'Error handling task execution message: {e}')
            raise HTTPException(status_code=500, detail=str(e))

    async def handle_clear(self, request: Request):
        """Clear all cached data and disconnect connected websocket clients."""
        try:
            data = await request.json()
            _log_message('HTTP RECV', 'ARF', 'ACF /clear', data)
            clear_msg = {
                'type': 'CLEAR',
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'payload': {},
            }

            for agent_id, websocket in list(self.connections.items()):
                try:
                    await self._send_json(websocket, clear_msg, target=agent_id)
                except Exception as e:
                    acf_logger.info(f'Error sending CLEAR to {agent_id}: {e}')
                finally:
                    try:
                        await websocket.close(code=1000)
                    except TypeError:
                        await websocket.close()

            self.connections.clear()
            self._clear_local_state()
            acf_logger.info('ACF state cleared')
            return JSONResponse(status_code=200, content={'status': 'OK'})
        except Exception as e:
            acf_logger.info(f'Error handling clear request: {e}')
            raise HTTPException(status_code=500, detail=str(e))

    async def handle_agent_deletions(self, request: Request):
        """Remove all local data for a deleted agent and disconnect it."""
        try:
            data = await request.json()
            _log_message(
                'HTTP RECV',
                'ARF',
                'ACF /acn-agent/v1/agent-deletions',
                data,
            )
            agent_id = data.get('agent_id')

            if not agent_id:
                acf_logger.info('agent-deletions request missing agent_id')
                return JSONResponse(status_code=200, content={'status': 'OK'})

            self._remove_agent_state(agent_id)
            await self._close_agent_connection(agent_id)
            acf_logger.info(f'Agent deletion handled for {agent_id}')
            return JSONResponse(status_code=200, content={'status': 'OK'})
        except Exception as e:
            acf_logger.info(f'Error handling agent deletion: {e}')
            raise HTTPException(status_code=500, detail=str(e))

    async def forward_discovery(self, body):
        """Forward a discovery payload to the target agent over websocket."""
        dst_agent_id = body.get('dst_agent_id')
        if not dst_agent_id:
            acf_logger.info('Discovery request missing dst_agent_id')
            return

        message = {
            'type': 'TASK_REQUEST_COLLABORATION',
            'timestamp': body.get('timestamp', datetime.utcnow().isoformat() + 'Z'),
            'payload': body,
        }

        if dst_agent_id in self.connections:
            await self._send_json(
                self.connections[dst_agent_id],
                message,
                target=dst_agent_id,
            )
            acf_logger.info(f'Forwarded TASK_REQUEST_COLLABORATION to {dst_agent_id}')
        else:
            acf_logger.info(f'Destination agent {dst_agent_id} not connected')

    async def handle_publish_track(self, data):
        """Persist track metadata for a single task_id with per-task dedupe."""
        payload = data.get('payload', {})
        src_agent_id = payload.get('src_agent_id')
        task_id = payload.get('task_id')
        track_list = payload.get('track_list', [])

        if not task_id:
            acf_logger.info('PUBLISH_TRACK missing task_id')
            return

        deduped_tracks = []
        seen = set()
        for item in track_list:
            namespace = item.get('namespace')
            track = item.get('track')
            key = (namespace, track)
            if namespace and track and key not in seen:
                seen.add(key)
                deduped_tracks.append({
                    'namespace': namespace,
                    'track': track,
                })

        db = get_db()
        try:
            existing_track = db.query(Track).filter(Track.task_id == task_id).first()
            if existing_track and existing_track.track_list:
                merged = existing_track.track_list + deduped_tracks
                merged_deduped = []
                seen = set()
                for item in merged:
                    namespace = item.get('namespace')
                    track = item.get('track')
                    key = (namespace, track)
                    if namespace and track and key not in seen:
                        seen.add(key)
                        merged_deduped.append({
                            'namespace': namespace,
                            'track': track,
                        })
                existing_track.track_list = merged_deduped
                existing_track.src_agent_id = src_agent_id
            elif existing_track:
                existing_track.track_list = deduped_tracks
                existing_track.src_agent_id = src_agent_id
            else:
                db.add(Track(
                    src_agent_id=src_agent_id,
                    task_id=task_id,
                    track_list=deduped_tracks,
                ))
            db.commit()
        finally:
            db.close()

        acf_logger.info(f'Persisted track metadata for task {task_id}')

    async def handle_task_request_collaboration(self, data):
        """Forward TASK_REQUEST_COLLABORATION to destination agent."""
        await self.forward_discovery(data.get('payload', {}))

    async def handle_task_accept_collaboration(self, data):
        """Handle TASK_ACCEPT_COLLABORATION."""
        payload = data.get('payload', {})
        dst_agent_id = payload.get('dst_agent_id')
        src_agent_id = payload.get('src_agent_id')
        task_id = payload.get('task_id')

        acf_logger.info(f'Received TASK_ACCEPT_COLLABORATION from {src_agent_id}')

        if not dst_agent_id:
            acf_logger.info('TASK_ACCEPT_COLLABORATION missing dst_agent_id')
            return

        discover_msg = {
            'type': 'DISCOVER_RESULT',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'payload': {
                'src_agent_id': 'ARF',
                'dst_agent_id': dst_agent_id,
                'discover_result': [src_agent_id],
            },
        }

        if dst_agent_id in self.connections:
            await self._send_json(
                self.connections[dst_agent_id],
                discover_msg,
                target=dst_agent_id,
            )
            acf_logger.info(f'Forwarded DISCOVER_RESULT to {dst_agent_id}')
        else:
            acf_logger.info(f'Destination agent {dst_agent_id} not connected')

    async def handle_start_task(self, data):
        """Forward START_TASK to the destination agent."""
        payload = data.get('payload', {})
        dst_agent_id = payload.get('dst_agent_id')

        if not dst_agent_id:
            acf_logger.info('START_TASK missing dst_agent_id')
            return

        if dst_agent_id in self.connections:
            await self._send_json(
                self.connections[dst_agent_id],
                data,
                target=dst_agent_id,
            )
            acf_logger.info(f'Forwarded START_TASK to {dst_agent_id}')
        else:
            acf_logger.info(f'Destination agent {dst_agent_id} not connected for START_TASK')

    async def handle_disconnection(self, websocket, data, agent_id=None):
        """Gracefully close a websocket and remove track rows for the agent."""
        payload = data.get('payload', {})
        src_agent_id = payload.get('src_agent_id')
        target_agent_id = src_agent_id or agent_id

        if hasattr(websocket, 'close'):
            try:
                await websocket.close(code=1000)
            except TypeError:
                await websocket.close()
        acf_logger.info(f'Received DISCONNECTION from {target_agent_id}')

        if not target_agent_id:
            return

        db = get_db()
        try:
            deleted_rows = db.query(Track).filter(
                Track.src_agent_id == target_agent_id,
            ).delete(synchronize_session=False)
            db.commit()
            acf_logger.info(
                f'Deleted {deleted_rows} track rows for disconnected agent {target_agent_id}'
            )
        finally:
            db.close()

        if target_agent_id in self.connections:
            del self.connections[target_agent_id]

        self._mark_agent_offline(target_agent_id)

    def _clear_local_state(self):
        """Remove all persisted ACF state."""
        db = get_db()
        try:
            db.query(Track).filter(Track.id.isnot(None)).delete(
                synchronize_session=False
            )
            db.query(Task).filter(Task.id.isnot(None)).delete(
                synchronize_session=False
            )
            db.query(Agent).filter(Agent.agent_id.isnot(None)).delete(
                synchronize_session=False
            )
            db.commit()
        finally:
            db.close()

    def _remove_agent_state(self, agent_id):
        """Remove all persisted rows for a single agent."""
        db = get_db()
        try:
            db.query(Track).filter(Track.src_agent_id == agent_id).delete(
                synchronize_session=False
            )
            db.query(Task).filter(Task.agent_id == agent_id).delete(
                synchronize_session=False
            )
            db.query(Agent).filter(Agent.agent_id == agent_id).delete(
                synchronize_session=False
            )
            db.commit()
        finally:
            db.close()

    async def _close_agent_connection(self, agent_id):
        """Close and remove a websocket connection if it exists."""
        websocket = self.connections.get(agent_id)
        if not websocket:
            return

        try:
            await websocket.close(code=1000)
        except TypeError:
            await websocket.close()
        finally:
            self.connections.pop(agent_id, None)

    def _mark_agent_offline(self, agent_id):
        """Mark an agent offline if the row still exists."""
        db = get_db()
        try:
            agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
            if agent:
                agent.agent_status = 'offline'
                db.commit()
        finally:
            db.close()

    async def handle_discover_result(self, data):
        """Forward DISCOVER_RESULT to destination agent."""
        dst_agent_id = data['payload']['dst_agent_id']

        if dst_agent_id in self.connections:
            await self._send_json(
                self.connections[dst_agent_id],
                data,
                target=dst_agent_id,
            )
            acf_logger.info(f'Forwarded DISCOVER_RESULT to {dst_agent_id}')
        else:
            acf_logger.info(f'Destination agent {dst_agent_id} not connected')

    async def handle_route(self, data):
        """Forward ROUTE message to destination agent as-is."""
        dst_agent_id = data['payload']['dst_agent_id']

        if dst_agent_id in self.connections:
            await self._send_json(
                self.connections[dst_agent_id],
                data,
                target=dst_agent_id,
            )
            acf_logger.info(f'Forwarded ROUTE message to {dst_agent_id}')
        else:
            acf_logger.info(f'Destination agent {dst_agent_id} not connected for ROUTE message')

    async def start(self):
        """Start the HTTP + websocket server."""
        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level='info',
        )
        server = uvicorn.Server(config)
        await server.serve()


if __name__ == '__main__':
    server = ACFServer()
    asyncio.run(server.start())
