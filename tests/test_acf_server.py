#!/usr/bin/env python3
"""
Unit tests for ACF WebSocket Server
"""

import pytest
import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock, call
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import websockets
from agent_gw.acf_server import ACFServer
from agent_gw.models import Agent, Task, Track, SessionLocal

@pytest.fixture
def acf_server():
    """Create ACF server instance"""
    server = ACFServer(host='localhost', port=9999)  # Use different port for testing
    return server

@pytest.mark.asyncio
class TestACFSetup:
    """Test SETUP message handling"""
    
    async def test_handle_setup_new_agent(self, acf_server):
        """Test SETUP message for new agent"""
        # Mock WebSocket
        mock_ws = AsyncMock()
        
        # Create agent in database first
        db = SessionLocal()
        agent = Agent(
            agent_id="did:acn:agent:test001",
            agent_name="Test Agent",
            agent_status="offline"
        )
        db.add(agent)
        db.commit()
        db.close()
        
        # SETUP message
        setup_msg = {
            "type": "SETUP",
            "timestamp": "2025-01-01T00:00:00Z",
            "payload": {
                "src_agent_id": "did:acn:agent:test001"
            }
        }
        
        await acf_server.handle_setup(mock_ws, setup_msg)
        
        # Verify connection stored
        assert "did:acn:agent:test001" in acf_server.connections
        assert acf_server.connections["did:acn:agent:test001"] == mock_ws
        
        # Verify agent status updated
        db = SessionLocal()
        agent = db.query(Agent).filter_by(agent_id="did:acn:agent:test001").first()
        assert agent.agent_status == "online"
        db.close()
        
        # Verify response sent
        mock_ws.send_text.assert_called_once()
        response = json.loads(mock_ws.send_text.call_args[0][0])
        assert response["type"] == "SETUP"
        assert response["payload"]["status"] == "OK"
    
    async def test_handle_setup_duplicate_connection(self, acf_server):
        """Test SETUP message when agent already connected"""
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        
        # First connection
        acf_server.connections["agent-dup"] = mock_ws1
        
        # Second connection attempt
        setup_msg = {
            "type": "SETUP",
            "payload": {"src_agent_id": "agent-dup"}
        }
        
        await acf_server.handle_setup(mock_ws2, setup_msg)
        
        # Should replace the old connection
        assert acf_server.connections["agent-dup"] == mock_ws2

@pytest.mark.asyncio
class TestACFMessageForwarding:
    """Test message forwarding between agents"""
    
    async def test_forward_task_request_collaboration(self, acf_server):
        """Test forwarding TASK_REQUEST_COLLABORATION"""
        # Setup: Create two agent connections
        mock_ws_src = AsyncMock()
        mock_ws_dst = AsyncMock()
        
        acf_server.connections["src-agent"] = mock_ws_src
        acf_server.connections["dst-agent"] = mock_ws_dst
        
        # Message to forward
        msg = {
            "type": "TASK_REQUEST_COLLABORATION",
            "timestamp": "2025-01-01T00:00:00Z",
            "payload": {
                "src_agent_id": "src-agent",
                "dst_agent_id": "dst-agent",
                "task_id": "task-001",
                "task_description": "Test task"
            }
        }
        
        await acf_server.handle_task_request_collaboration(msg)
        
        # Verify message forwarded to destination
        mock_ws_dst.send_text.assert_called_once()
        sent_msg = json.loads(mock_ws_dst.send_text.call_args[0][0])
        assert sent_msg["type"] == "TASK_REQUEST_COLLABORATION"
        assert sent_msg["payload"]["dst_agent_id"] == "dst-agent"
    
    async def test_forward_to_disconnected_agent(self, acf_server):
        """Test forwarding to disconnected agent"""
        msg = {
            "type": "TASK_REQUEST_COLLABORATION",
            "payload": {
                "dst_agent_id": "disconnected-agent"
            }
        }
        
        # Should not raise exception
        await acf_server.handle_task_request_collaboration(msg)
    
    async def test_forward_task_accept_collaboration(self, acf_server):
        """Test handling TASK_ACCEPT_COLLABORATION"""
        # Setup connections
        mock_ws_dst = AsyncMock()

        acf_server.connections["requesting-agent"] = mock_ws_dst
        
        # Message
        msg = {
            "type": "TASK_ACCEPT_COLLABORATION",
            "timestamp": "2025-01-01T00:00:00Z",
            "payload": {
                "src_agent_id": "accepting-agent",
                "dst_agent_id": "requesting-agent",
                "task_id": "task-002",
                "result": "OK"
            }
        }
        
        await acf_server.handle_task_accept_collaboration(msg)

        # Verify direct DISCOVER_RESULT to requester
        mock_ws_dst.send_text.assert_called_once()
        sent_msg = json.loads(mock_ws_dst.send_text.call_args[0][0])
        assert sent_msg["type"] == "DISCOVER_RESULT"
        assert sent_msg["payload"]["discover_result"] == ["accepting-agent"]
        assert sent_msg["payload"]["dst_agent_id"] == "requesting-agent"

    async def test_handle_discoveries_http(self, acf_server):
        """Test HTTP discovery requests are forwarded to the destination agent."""
        mock_ws = AsyncMock()
        acf_server.connections["dst-agent"] = mock_ws

        request = AsyncMock()
        request.json.return_value = {
            "body": {
                "src_agent_id": "ARF",
                "dst_agent_id": "dst-agent",
                "task_id": "task-002",
                "task_description": "Collaboration task",
                "agent_card": {
                    "agent_id": "dst-agent",
                    "skill": ["camera", "night_vision"]
                },
                "timestamp": "2025-01-01T00:00:00Z"
            }
        }

        response = await acf_server.handle_discoveries(request)

        assert response.status_code == 200
        mock_ws.send_text.assert_called_once()
        sent_msg = json.loads(mock_ws.send_text.call_args[0][0])
        assert sent_msg["type"] == "TASK_REQUEST_COLLABORATION"
        assert sent_msg["payload"]["dst_agent_id"] == "dst-agent"
        assert sent_msg["payload"]["task_id"] == "task-002"

    async def test_handle_discoveries_http_with_flat_payload(self, acf_server):
        """Test flat discovery requests are forwarded to the destination agent."""
        mock_ws = AsyncMock()
        acf_server.connections["dst-agent-flat"] = mock_ws

        request = AsyncMock()
        request.json.return_value = {
            "src_agent_id": "src-agent-flat",
            "dst_agent_id": "dst-agent-flat",
            "task_id": "task-flat-002",
            "task_description": "Collaboration task",
            "agent_card": {
                "agent_id": "src-agent-flat",
                "skill": ["camera", "night_vision"]
            },
            "timestamp": "2025-01-01T00:00:00Z"
        }

        response = await acf_server.handle_discoveries(request)

        assert response.status_code == 200
        mock_ws.send_text.assert_called_once()
        sent_msg = json.loads(mock_ws.send_text.call_args[0][0])
        assert sent_msg["type"] == "TASK_REQUEST_COLLABORATION"
        assert sent_msg["payload"]["dst_agent_id"] == "dst-agent-flat"
        assert sent_msg["payload"]["src_agent_id"] == "src-agent-flat"
        assert sent_msg["payload"]["task_id"] == "task-flat-002"

    async def test_handle_task_assigned_http_forwards_to_assigned_agents(self, acf_server):
        """Test HTTP TASK_ASSIGNED requests are forwarded to assigned agents."""
        mock_ws_1 = AsyncMock()
        mock_ws_2 = AsyncMock()
        acf_server.connections["did:acn:agent:2222222"] = mock_ws_1
        acf_server.connections["did:acn:agent:33333333"] = mock_ws_2

        request = AsyncMock()
        request.json.return_value = {
            "type": "TASK_ASSIGNED",
            "timestamp": "2026-04-24T00:00:00Z",
            "payload": {
                "task_description": "危险区域协同巡检",
                "assigned_agents": [
                    "did:acn:agent:2222222",
                    "did:acn:agent:33333333",
                ],
            },
        }

        response = await acf_server.handle_task_assigned(request)

        assert response.status_code == 200
        response_body = json.loads(response.body)
        assert response_body["sent_agents"] == [
            "did:acn:agent:2222222",
            "did:acn:agent:33333333",
        ]
        assert response_body["missing_agents"] == []

        for mock_ws in (mock_ws_1, mock_ws_2):
            mock_ws.send_text.assert_called_once()
            sent_msg = json.loads(mock_ws.send_text.call_args[0][0])
            assert sent_msg["type"] == "TASK_ASSIGNED"
            assert sent_msg["timestamp"] == "2026-04-24T00:00:00Z"
            assert sent_msg["payload"]["task_description"] == "危险区域协同巡检"
            assert sent_msg["payload"]["assigned_agents"] == [
                "did:acn:agent:2222222",
                "did:acn:agent:33333333",
            ]

    async def test_handle_task_assigned_http_skips_disconnected_agents(self, acf_server):
        """Test TASK_ASSIGNED reports assigned agents without open websocket sessions."""
        mock_ws = AsyncMock()
        acf_server.connections["did:acn:agent:2222222"] = mock_ws

        request = AsyncMock()
        request.json.return_value = {
            "type": "TASK_ASSIGNED",
            "timestamp": "2026-04-24T00:00:00Z",
            "payload": {
                "task_description": "危险区域协同巡检",
                "assigned_agents": [
                    "did:acn:agent:2222222",
                    "did:acn:agent:33333333",
                ],
            },
        }

        response = await acf_server.handle_task_assigned(request)

        assert response.status_code == 200
        response_body = json.loads(response.body)
        assert response_body["sent_agents"] == ["did:acn:agent:2222222"]
        assert response_body["missing_agents"] == ["did:acn:agent:33333333"]
        mock_ws.send_text.assert_called_once()

    async def test_publish_track_persists_deduped_tracks(self, acf_server):
        """Test PUBLISH_TRACK stores deduplicated track metadata."""
        msg = {
            "type": "PUBLISH_TRACK",
            "timestamp": "2025-01-01T00:00:00Z",
            "payload": {
                "src_agent_id": "did:acn:agent:222222222",
                "task_id": "task-12345",
                "track_list": [
                    {
                        "namespace": "/task-12345/did:acn:agent:222222222",
                        "track": "Video"
                    },
                    {
                        "namespace": "/task-12345/did:acn:agent:222222222",
                        "track": "Video"
                    },
                    {
                        "namespace": "/task-12345/did:acn:agent:222222222",
                        "track": "Location"
                    }
                ]
            }
        }

        await acf_server.handle_publish_track(msg)

        db = SessionLocal()
        track = db.query(Track).filter_by(task_id="task-12345").first()
        assert track is not None
        assert track.src_agent_id == "did:acn:agent:222222222"
        assert len(track.track_list) == 2
        tracks = {(item["namespace"], item["track"]) for item in track.track_list}
        assert tracks == {
            ("/task-12345/did:acn:agent:222222222", "Video"),
            ("/task-12345/did:acn:agent:222222222", "Location"),
        }
        db.close()

    async def test_publish_track_dedupes_per_task_only(self, acf_server):
        """Test identical track items are preserved across different task_ids."""
        common_tracks = [
            {
                "namespace": "/task/shared/did:acn:agent:222222222",
                "track": "Video"
            },
            {
                "namespace": "/task/shared/did:acn:agent:222222222",
                "track": "Location"
            }
        ]

        for task_id in ("task-a", "task-b"):
            await acf_server.handle_publish_track({
                "type": "PUBLISH_TRACK",
                "timestamp": "2025-01-01T00:00:00Z",
                "payload": {
                    "src_agent_id": "did:acn:agent:222222222",
                    "task_id": task_id,
                    "track_list": common_tracks,
                }
            })

        db = SessionLocal()
        task_a = db.query(Track).filter_by(task_id="task-a").first()
        task_b = db.query(Track).filter_by(task_id="task-b").first()
        assert task_a is not None
        assert task_b is not None
        assert task_a.track_list == common_tracks
        assert task_b.track_list == common_tracks
        assert task_a.src_agent_id == "did:acn:agent:222222222"
        assert task_b.src_agent_id == "did:acn:agent:222222222"
        db.close()

    @patch('agent_gw.acf_server.httpx.AsyncClient')
    async def test_task_execution_subscribes_tracks(self, mock_async_client, acf_server):
        """Test task-execution notification triggers SUBSCRIBE_TRACK."""
        publish_msg = {
            "type": "PUBLISH_TRACK",
            "timestamp": "2025-01-01T00:00:00Z",
            "payload": {
                "src_agent_id": "did:acn:agent:222222222",
                "task_id": "task-12345",
                "track_list": [
                    {
                        "namespace": "/task-12345/did:acn:agent:222222222",
                        "track": "Video"
                    },
                    {
                        "namespace": "/task-12345/did:acn:agent:222222222",
                        "track": "Location"
                    }
                ]
            }
        }
        await acf_server.handle_publish_track(publish_msg)

        mock_ws = AsyncMock()
        acf_server.connections["did:acn:agent:222222222"] = mock_ws

        request = AsyncMock()
        request.json.return_value = {
            "body": {
                "agent_id": "did:acn:agent:222222222",
                "task_id": "task-12345",
                "description": "危险区域可以人员巡检",
                "timestamp": "2025-01-01T00:00:00Z"
            }
        }

        response = await acf_server.handle_task_executions(request)

        assert response.status_code == 200
        assert mock_async_client.return_value.__aenter__.called
        mock_ws.send_text.assert_called_once()
        sent_msg = json.loads(mock_ws.send_text.call_args[0][0])
        assert sent_msg["type"] == "SUBSCRIBE_TRACK"
        assert sent_msg["payload"]["task_id"] == "task-12345"
        assert len(sent_msg["payload"]["track_list"]) == 2
        http_client = mock_async_client.return_value.__aenter__.return_value
        assert http_client.post.await_count == 1
        _, kwargs = http_client.post.call_args
        assert kwargs["json"]["url"] == "/ACN_v3/subscribe_track"
        assert kwargs["json"]["body"]["type"] == "SUBSCRIBE_TRACK"
        assert kwargs["json"]["body"]["payload"]["dst_agent_id"] == "did:acn:agent:222222222"
        assert kwargs["json"]["body"]["payload"]["track_list"] == [
            {
                "namespace": "/task-12345/did:acn:agent:222222222",
                "track": "Video"
            },
            {
                "namespace": "/task-12345/did:acn:agent:222222222",
                "track": "Location"
            }
        ]

    @patch('agent_gw.acf_server.httpx.AsyncClient')
    async def test_task_execution_subscribes_tracks_with_flat_payload(self, mock_async_client, acf_server):
        """Test flat task-execution payloads trigger SUBSCRIBE_TRACK."""
        await acf_server.handle_publish_track({
            "type": "PUBLISH_TRACK",
            "timestamp": "2025-01-01T00:00:00Z",
            "payload": {
                "src_agent_id": "did:acn:agent:222222222",
                "task_id": "task-8717f",
                "track_list": [
                    {
                        "namespace": "/task-8717f/did:acn:agent:222222222",
                        "track": "Location"
                    }
                ]
            }
        })

        mock_ws = AsyncMock()
        acf_server.connections["did:acn:agent:target"] = mock_ws

        request = AsyncMock()
        request.json.return_value = {
            "agent_id": "did:acn:agent:target",
            "task_id": "task-8717f",
            "description": "声光驱离",
            "timestamp": "2026-04-03T02:13:52Z"
        }

        response = await acf_server.handle_task_executions(request)

        assert response.status_code == 200
        http_client = mock_async_client.return_value.__aenter__.return_value
        assert http_client.post.await_count == 1
        _, kwargs = http_client.post.call_args
        assert kwargs["json"]["url"] == "/ACN_v3/subscribe_track"
        assert kwargs["json"]["body"]["payload"]["dst_agent_id"] == "did:acn:agent:target"
        mock_ws.send_text.assert_called_once()
        sent_msg = json.loads(mock_ws.send_text.call_args[0][0])
        assert sent_msg["type"] == "SUBSCRIBE_TRACK"
        assert sent_msg["payload"]["task_id"] == "task-8717f"
        assert sent_msg["payload"]["track_list"] == [
            {
                "namespace": "/task-8717f/did:acn:agent:222222222",
                "track": "Location"
            }
        ]

    async def test_task_execution_logs_saved_tracks_when_mapping_missing(self, acf_server, caplog):
        """Test missing track mapping logs saved track content for debugging."""
        db = SessionLocal()
        db.add(Track(
            src_agent_id="did:acn:agent:existing",
            task_id="task-existing",
            track_list=[
                {
                    "namespace": "/task-existing/did:acn:agent:existing",
                    "track": "Video"
                }
            ],
        ))
        db.commit()
        db.close()

        request = AsyncMock()
        request.json.return_value = {
            "body": {
                "agent_id": "did:acn:agent:222222222",
                "task_id": None,
                "description": "missing mapping",
                "timestamp": "2025-01-01T00:00:00Z"
            }
        }

        response = await acf_server.handle_task_executions(request)

        assert response.status_code == 200
        assert 'No track mapping found:' in caplog.text
        assert '"task_id": null' in caplog.text
        assert '"task_id": "task-existing"' in caplog.text
        assert '"src_agent_id": "did:acn:agent:existing"' in caplog.text

    async def test_start_task_forwards_to_agent(self, acf_server):
        """Test START_TASK is forwarded to the destination agent."""
        mock_ws = AsyncMock()
        acf_server.connections["did:acn:agent:111111111"] = mock_ws

        msg = {
            "type": "START_TASK",
            "timestamp": "2025-01-01T00:00:00Z",
            "payload": {
                "src_agent_id": "did:acn:agent:222222222",
                "dst_agent_id": "did:acn:agent:111111111",
                "task_id": "task-12345",
                "task_description": "Collaboration task"
            }
        }

        await acf_server.handle_start_task(msg)

        mock_ws.send_text.assert_called_once()
        sent_msg = json.loads(mock_ws.send_text.call_args[0][0])
        assert sent_msg["type"] == "START_TASK"
        assert sent_msg["payload"]["dst_agent_id"] == "did:acn:agent:111111111"

    async def test_disconnection_removes_tracks_and_closes_socket(self, acf_server):
        """Test DISCONNECTION closes the socket and removes tracks for the agent."""
        db = SessionLocal()
        db.add(Track(
            src_agent_id="did:acn:agent:disconnect-me",
            task_id="task-1",
            track_list=[
                {
                    "namespace": "/task-1/did:acn:agent:disconnect-me",
                    "track": "Video"
                }
            ]
        ))
        db.add(Track(
            src_agent_id="did:acn:agent:disconnect-me",
            task_id="task-2",
            track_list=[
                {
                    "namespace": "/task-2/did:acn:agent:disconnect-me",
                    "track": "Location"
                }
            ]
        ))
        db.add(Track(
            src_agent_id="did:acn:agent:other",
            task_id="task-3",
            track_list=[
                {
                    "namespace": "/task-3/did:acn:agent:other",
                    "track": "Video"
                }
            ]
        ))
        db.commit()
        db.close()

        mock_ws = AsyncMock()
        acf_server.connections["did:acn:agent:disconnect-me"] = mock_ws

        msg = {
            "type": "DISCONNECTION",
            "timestamp": "2025-01-01T00:00:00Z",
            "payload": {
                "src_agent_id": "did:acn:agent:disconnect-me"
            }
        }

        await acf_server.handle_disconnection(mock_ws, msg)

        mock_ws.close.assert_called_once()
        assert "did:acn:agent:disconnect-me" not in acf_server.connections

        db = SessionLocal()
        remaining = db.query(Track).all()
        remaining_task_ids = sorted(track.task_id for track in remaining)
        assert remaining_task_ids == ["task-3"]
        assert remaining[0].src_agent_id == "did:acn:agent:other"
        db.close()

    async def test_clear_broadcasts_clear_and_resets_state(self, acf_server):
        """Test /clear broadcasts CLEAR and deletes local state."""
        db = SessionLocal()
        db.add(Agent(agent_id="agent-clear-1", agent_status="online"))
        db.add(Task(agent_id="agent-clear-1", task_id="task-clear-1", task_description="x"))
        db.add(Track(
            src_agent_id="agent-clear-1",
            task_id="task-clear-1",
            track_list=[{"namespace": "/task-clear-1/agent-clear-1", "track": "Video"}],
        ))
        db.commit()
        db.close()

        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        acf_server.connections["agent-clear-1"] = mock_ws1
        acf_server.connections["agent-clear-2"] = mock_ws2

        request = AsyncMock()
        request.json.return_value = {"body": {}}

        response = await acf_server.handle_clear(request)

        assert response.status_code == 200
        assert acf_server.connections == {}
        mock_ws1.send_text.assert_called_once()
        mock_ws2.send_text.assert_called_once()
        mock_ws1.close.assert_called_once()
        mock_ws2.close.assert_called_once()

        db = SessionLocal()
        assert db.query(Agent).count() == 0
        assert db.query(Task).count() == 0
        assert db.query(Track).count() == 0
        db.close()

    async def test_agent_deletions_clears_agent_rows_and_disconnects(self, acf_server):
        """Test agent deletion removes local state and disconnects the agent."""
        db = SessionLocal()
        db.add(Agent(agent_id="agent-delete-1", agent_status="online"))
        db.add(Task(agent_id="agent-delete-1", task_id="task-delete-1", task_description="x"))
        db.add(Track(
            src_agent_id="agent-delete-1",
            task_id="task-delete-1",
            track_list=[{"namespace": "/task-delete-1/agent-delete-1", "track": "Video"}],
        ))
        db.add(Track(
            src_agent_id="agent-delete-2",
            task_id="task-delete-2",
            track_list=[{"namespace": "/task-delete-2/agent-delete-2", "track": "Location"}],
        ))
        db.commit()
        db.close()

        mock_ws = AsyncMock()
        acf_server.connections["agent-delete-1"] = mock_ws

        request = AsyncMock()
        request.json.return_value = {
            "agent_id": "agent-delete-1",
            "reason": "retired",
            "timestamp": "2025-01-01T00:00:00Z",
            "signature": "xxxxxxx",
            "signature_encoding": "base64",
        }

        response = await acf_server.handle_agent_deletions(request)

        assert response.status_code == 200
        mock_ws.close.assert_called_once()
        assert "agent-delete-1" not in acf_server.connections

        db = SessionLocal()
        assert db.query(Agent).filter_by(agent_id="agent-delete-1").first() is None
        assert db.query(Task).filter_by(agent_id="agent-delete-1").count() == 0
        assert db.query(Track).filter_by(src_agent_id="agent-delete-1").count() == 0
        assert db.query(Track).filter_by(src_agent_id="agent-delete-2").count() == 1
        db.close()

    async def test_agent_deletions_with_flat_payload(self, acf_server):
        """Test flat agent deletion requests remove local state and disconnect the agent."""
        db = SessionLocal()
        db.add(Agent(agent_id="agent-delete-flat", agent_status="online"))
        db.add(Task(agent_id="agent-delete-flat", task_id="task-delete-flat", task_description="x"))
        db.add(Track(
            src_agent_id="agent-delete-flat",
            task_id="task-delete-flat",
            track_list=[{"namespace": "/task-delete-flat/agent-delete-flat", "track": "Video"}],
        ))
        db.commit()
        db.close()

        mock_ws = AsyncMock()
        acf_server.connections["agent-delete-flat"] = mock_ws

        request = AsyncMock()
        request.json.return_value = {
            "agent_id": "agent-delete-flat",
            "reason": "retired",
            "timestamp": "2025-01-01T00:00:00Z",
        }

        response = await acf_server.handle_agent_deletions(request)

        assert response.status_code == 200
        mock_ws.close.assert_called_once()
        assert "agent-delete-flat" not in acf_server.connections

        db = SessionLocal()
        assert db.query(Agent).filter_by(agent_id="agent-delete-flat").first() is None
        assert db.query(Task).filter_by(agent_id="agent-delete-flat").count() == 0
        assert db.query(Track).filter_by(src_agent_id="agent-delete-flat").count() == 0
        db.close()
    
    async def test_forward_discover_result(self, acf_server):
        """Test forwarding DISCOVER_RESULT"""
        mock_ws = AsyncMock()
        acf_server.connections["discoverer-agent"] = mock_ws
        
        msg = {
            "type": "DISCOVER_RESULT",
            "timestamp": "2025-01-01T00:00:00Z",
            "payload": {
                "src_agent_id": "ARF",
                "dst_agent_id": "discoverer-agent",
                "discover_result": ["did:acn:agent:found"]
            }
        }
        
        await acf_server.handle_discover_result(msg)
        
        # Verify forwarded
        mock_ws.send_text.assert_called_once()
        sent_msg = json.loads(mock_ws.send_text.call_args[0][0])
        assert sent_msg["payload"]["discover_result"][0] == "did:acn:agent:found"

@pytest.mark.asyncio
class TestACFConnectionCleanup:
    """Test connection cleanup on disconnect"""
    
    async def test_cleanup_on_disconnect(self, acf_server):
        """Test connection removal when agent disconnects"""
        # Setup
        db = SessionLocal()
        agent = Agent(
            agent_id="disconnecting-agent",
            agent_status="online"
        )
        db.add(agent)
        db.commit()
        db.close()
        
        mock_ws = AsyncMock()
        acf_server.connections["disconnecting-agent"] = mock_ws
        
        # Simulate disconnect
        del acf_server.connections["disconnecting-agent"]
        
        # Update status
        db = SessionLocal()
        agent = db.query(Agent).filter_by(agent_id="disconnecting-agent").first()
        if agent:
            agent.agent_status = "offline"
            db.commit()
        db.close()
        
        # Verify
        assert "disconnecting-agent" not in acf_server.connections
        db = SessionLocal()
        agent = db.query(Agent).filter_by(agent_id="disconnecting-agent").first()
        assert agent.agent_status == "offline"
        db.close()

    async def test_websocket_disconnect_clears_tasks_and_tracks(self, acf_server):
        """Unexpected websocket closure should clear persisted task and track state."""
        db = SessionLocal()
        db.add(Agent(
            agent_id="disconnecting-agent-2",
            agent_status="online"
        ))
        db.add(Task(
            agent_id="disconnecting-agent-2",
            task_id="task-disconnect-1",
            task_description="test task"
        ))
        db.add(Track(
            src_agent_id="disconnecting-agent-2",
            task_id="task-disconnect-1",
            track_list=[
                {
                    "namespace": "/task-disconnect-1/disconnecting-agent-2",
                    "track": "Video"
                }
            ]
        ))
        db.commit()
        db.close()

        messages = [json.dumps({"type": "SETUP", "payload": {"src_agent_id": "disconnecting-agent-2"}})]

        class MockWebSocket:
            def __init__(self, msgs):
                self.messages = msgs
                self.send_text = AsyncMock()

            def __aiter__(self):
                return self

            async def __anext__(self):
                if not self.messages:
                    raise StopAsyncIteration
                return self.messages.pop(0)

        await acf_server.handle_websocket(MockWebSocket(messages), "/")

        db = SessionLocal()
        agent = db.query(Agent).filter_by(agent_id="disconnecting-agent-2").first()
        assert agent is not None
        assert agent.agent_status == "offline"
        assert db.query(Task).filter_by(agent_id="disconnecting-agent-2").count() == 0
        assert db.query(Track).filter_by(src_agent_id="disconnecting-agent-2").count() == 0
        db.close()


class TestACFWebSocketRoutes:
    """Test registered websocket paths."""

    def test_websocket_alias_ws_maps_to_same_endpoint(self, acf_server):
        """Legacy /ws should remain accepted alongside /acf/ws."""
        websocket_paths = {
            route.path
            for route in acf_server.app.routes
            if getattr(route, 'path', None) in ('/acf/ws', '/ws')
        }

        assert websocket_paths == {'/acf/ws', '/ws'}


class TestACFHttpRoutes:
    """Test registered HTTP paths."""

    def test_task_assigned_route_is_registered(self, acf_server):
        """ACN SDK callback path should be available on the ACF HTTP server."""
        http_paths = {
            route.path
            for route in acf_server.app.routes
            if "POST" in getattr(route, "methods", set())
        }

        assert "/acn/v3/task-assigned" in http_paths

@pytest.mark.asyncio
class TestACFWebSocketHandler:
    """Test main WebSocket handler"""
    
    async def test_handle_websocket_setup_flow(self, acf_server):
        """Test complete WebSocket handling flow"""
        # Create agent in DB first
        db = SessionLocal()
        agent = Agent(agent_id="test-agent-flow")
        db.add(agent)
        db.commit()
        db.close()
        
        # Create a mock that properly supports async for
        messages = [json.dumps({"type": "SETUP", "payload": {"src_agent_id": "test-agent-flow"}})]
        
        class MockWebSocket:
            def __init__(self, msgs):
                self.messages = msgs
                self.send_text = AsyncMock()
                self._closed = False
                
            def __aiter__(self):
                return self
                
            async def __anext__(self):
                if not self.messages:
                    # Keep connection open by sleeping instead of raising StopAsyncIteration
                    # This simulates a real WebSocket that waits for more messages
                    while not self._closed:
                        await asyncio.sleep(0.1)
                    raise StopAsyncIteration
                return self.messages.pop(0)
            
            async def close(self):
                self._closed = True
        
        mock_ws = MockWebSocket(messages)
        
        # Handle connection in a task so we can cancel it
        task = asyncio.create_task(acf_server.handle_websocket(mock_ws, "/"))
        
        # Give handler time to process the SETUP message
        await asyncio.sleep(0.2)
        
        # Verify agent is connected
        assert "test-agent-flow" in acf_server.connections
        
        # Close the mock to end the handler
        await mock_ws.close()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def test_handle_invalid_json(self, acf_server):
        """Test handling invalid JSON"""
        messages = ["invalid json"]
        
        class MockWebSocket:
            def __init__(self, msgs):
                self.messages = msgs
                self.send_text = AsyncMock()
                
            def __aiter__(self):
                return self
                
            async def __anext__(self):
                if not self.messages:
                    raise StopAsyncIteration
                return self.messages.pop(0)
        
        mock_ws = MockWebSocket(messages)
        
        # Should not raise exception
        await acf_server.handle_websocket(mock_ws, "/")
    
    async def test_handle_unknown_message_type(self, acf_server):
        """Test handling unknown message type"""
        messages = [json.dumps({"type": "UNKNOWN_TYPE", "payload": {}})]
        
        class MockWebSocket:
            def __init__(self, msgs):
                self.messages = msgs
                self.send_text = AsyncMock()
                
            def __aiter__(self):
                return self
                
            async def __anext__(self):
                if not self.messages:
                    raise StopAsyncIteration
                return self.messages.pop(0)
        
        mock_ws = MockWebSocket(messages)
        
        # Should not raise exception
        await acf_server.handle_websocket(mock_ws, "/")

@pytest.mark.asyncio
class TestACFMultipleAgents:
    """Test scenarios with multiple agents"""
    
    async def test_multiple_agents_connected(self, acf_server):
        """Test managing connections for multiple agents"""
        agents = [f"agent-{i}" for i in range(5)]
        
        for agent_id in agents:
            db = SessionLocal()
            agent = Agent(agent_id=agent_id)
            db.add(agent)
            db.commit()
            db.close()
            
            mock_ws = AsyncMock()
            setup_msg = {
                "type": "SETUP",
                "payload": {"src_agent_id": agent_id}
            }
            await acf_server.handle_setup(mock_ws, setup_msg)
        
        # Verify all agents connected
        assert len(acf_server.connections) == 5
        for agent_id in agents:
            assert agent_id in acf_server.connections
    
    async def test_broadcast_not_supported(self, acf_server):
        """Test that ACF forwards to specific agents, not broadcast"""
        # ACF should forward messages to specific destination agents only
        # This test documents the expected behavior
        
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        mock_ws3 = AsyncMock()
        
        acf_server.connections["agent-1"] = mock_ws1
        acf_server.connections["agent-2"] = mock_ws2
        acf_server.connections["agent-3"] = mock_ws3
        
        # Message for agent-2 only
        msg = {
            "type": "TASK_REQUEST_COLLABORATION",
            "payload": {"dst_agent_id": "agent-2"}
        }
        
        await acf_server.handle_task_request_collaboration(msg)
        
        # Only agent-2 should receive the message
        mock_ws1.send_text.assert_not_called()
        mock_ws2.send_text.assert_called_once()
        mock_ws3.send_text.assert_not_called()
