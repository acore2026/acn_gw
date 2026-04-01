#!/usr/bin/env python3
"""
Integration tests for Agent GW
Tests interaction between ARF, ACF, and agents
"""

import pytest
import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_gw.models import Agent, Task, Track, SessionLocal

@pytest.mark.asyncio
class TestAgentRegistrationFlow:
    """Test complete agent registration flow"""
    
    @patch('httpx.AsyncClient.post')
    async def test_agent_registers_then_connects(self, mock_post):
        """Test agent registers via ARF then connects via ACF"""
        from fastapi.testclient import TestClient
        from agent_gw.arf_server import app
        from agent_gw.acf_server import ACFServer
        
        # Setup
        client = TestClient(app)
        
        # Mock IDM response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "valid": True,
            "vc_ids": ["test"],
            "invalid_vcs": None,
        }
        mock_post.return_value = mock_response
        
        # Step 1: Agent registers via ARF
        reg_payload = {
            "agent_id": "did:acn:agent:integration001",
            "body": {
                "priority": 1,
                "vc_list": [{
                    "claims": {
                        "agent_name": "Integration Test Agent",
                        "agent_id": "did:acn:agent:integration001",
                        "agent_attribute": "Test Capability"
                    }
                }]
            }
        }
        
        response = client.post("/arf/v1/agent-cards", json=reg_payload)
        assert response.status_code == 200
        
        # Verify agent in database
        db = SessionLocal()
        agent = db.query(Agent).filter_by(agent_id="did:acn:agent:integration001").first()
        assert agent is not None
        assert agent.agent_status == "offline"
        db.close()

@pytest.mark.asyncio
class TestDiscoveryAndCollaborationFlow:
    """Test discovery and collaboration workflow"""
    
    async def test_full_discovery_flow(self):
        """Test complete discovery -> collaboration flow"""
        from agent_gw.acf_server import ACFServer
        
        # Setup ACF
        acf = ACFServer(host='localhost', port=9997)
        
        # Setup agents in database
        db = SessionLocal()
        
        # Requester agent
        requester = Agent(
            agent_id="did:acn:agent:requester",
            agent_name="Requester",
            agent_capability=["controller"],
            agent_status="online"
        )
        db.add(requester)
        
        # Available agent with matching capability
        available = Agent(
            agent_id="did:acn:agent:available",
            agent_name="Available Agent",
            agent_capability=["camera", "night_vision"],
            agent_status="online",
            priority=2
        )
        db.add(available)
        db.commit()
        db.close()
        
        # Mock WebSocket connections
        mock_ws_requester = AsyncMock()
        mock_ws_available = AsyncMock()
        
        acf.connections["did:acn:agent:requester"] = mock_ws_requester
        acf.connections["did:acn:agent:available"] = mock_ws_available
        
        # Step 1: Discovery request (simulated)
        # In real scenario, this comes from HTTP API
        
        # Step 2: ARF sends an HTTP discovery request to ACF
        discovery_request = AsyncMock()
        discovery_request.json.return_value = {
            "body": {
                "src_agent_id": "ARF",
                "dst_agent_id": "did:acn:agent:available",
                "task_id": "task-integration-001",
                "task_description": "Integration test task",
                "agent_card": {
                    "agent_id": "did:acn:agent:available",
                    "skill": ["camera", "night_vision"]
                },
                "timestamp": datetime.utcnow().isoformat() + 'Z'
            }
        }

        await acf.handle_discoveries(discovery_request)
        
        # Verify forwarded to available agent
        mock_ws_available.send_text.assert_called_once()
        sent_msg = json.loads(mock_ws_available.send_text.call_args[0][0])
        assert sent_msg["payload"]["task_id"] == "task-integration-001"
        
        # Step 3: Available agent accepts
        accept_msg = {
            "type": "TASK_ACCEPT_COLLABORATION",
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "payload": {
                "src_agent_id": "did:acn:agent:available",
                "dst_agent_id": "did:acn:agent:requester",
                "task_id": "task-integration-001",
                "result": "OK"
            }
        }
        
        await acf.handle_task_accept_collaboration(accept_msg)

        # Verify direct discover result to requester
        mock_ws_requester.send_text.assert_called_once()
        sent_msg = json.loads(mock_ws_requester.send_text.call_args[0][0])
        assert sent_msg["type"] == "DISCOVER_RESULT"
        assert sent_msg["payload"]["discover_result"] == ["did:acn:agent:available"]

        # Step 4: publish track metadata before the task starts
        publish_msg = {
            "type": "PUBLISH_TRACK",
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "payload": {
                "src_agent_id": "did:acn:agent:available",
                "task_id": "task-integration-001",
                "track_list": [
                    {
                        "namespace": "/task-integration-001/did:acn:agent:available",
                        "track": "Video"
                    },
                    {
                        "namespace": "/task-integration-001/did:acn:agent:available",
                        "track": "Location"
                    }
                ]
            }
        }
        await acf.handle_publish_track(publish_msg)

        db = SessionLocal()
        track = db.query(Track).filter_by(task_id="task-integration-001").first()
        assert track is not None
        assert track.src_agent_id == "did:acn:agent:available"
        assert len(track.track_list) == 2
        db.close()

        # Step 5: available agent reports task execution to ARF
        from fastapi.testclient import TestClient
        from agent_gw.arf_server import app as arf_app

        client = TestClient(arf_app)
        execution_payload = {
            "body": {
                "agent_id": "did:acn:agent:available",
                "task_id": "task-integration-001",
                "description": "Integration test task",
                "timestamp": datetime.utcnow().isoformat() + 'Z'
            }
        }

        with patch('agent_gw.arf_server.httpx.AsyncClient') as mock_async_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_async_client.return_value.__aexit__ = AsyncMock(return_value=None)

            response = client.post("/acn-agent/v1/task-executions", json=execution_payload)

        assert response.status_code == 200

        db = SessionLocal()
        task = db.query(Task).filter_by(task_id="task-integration-001").first()
        assert task is not None
        assert task.agent_id == "did:acn:agent:available"
        db.close()

        # Step 6: ARF forwards task execution to ACF, which subscribes the agent to tracks
        subscribe_request = AsyncMock()
        subscribe_request.json.return_value = {
            "body": execution_payload["body"]
        }
        response = await acf.handle_task_executions(subscribe_request)
        assert response.status_code == 200
        assert mock_ws_available.send_text.call_count == 2
        sent_msg = json.loads(mock_ws_available.send_text.call_args_list[1][0][0])
        assert sent_msg["type"] == "SUBSCRIBE_TRACK"
        assert sent_msg["payload"]["task_id"] == "task-integration-001"

        # Step 7: task termination removes the task record
        termination_payload = {
            "body": {
                "agent_id": "did:acn:agent:available",
                "task_id": "task-integration-001",
                "reason": "目标已离开区域，任务完成",
                "timestamp": datetime.utcnow().isoformat() + 'Z',
                "force": "false"
            }
        }
        response = client.post("/acn-agent/v1/task-execution-terminations", json=termination_payload)
        assert response.status_code == 200

        db = SessionLocal()
        task = db.query(Task).filter_by(task_id="task-integration-001").first()
        assert task is None
        db.close()

@pytest.mark.asyncio
class TestErrorScenarios:
    """Test error and edge cases"""
    
    async def test_agent_disconnects_mid_task(self):
        """Test handling when agent disconnects during collaboration"""
        from agent_gw.acf_server import ACFServer
        
        acf = ACFServer(host='localhost', port=9996)
        
        # Setup agent
        db = SessionLocal()
        agent = Agent(
            agent_id="did:acn:agent:disconnect-test",
            agent_name="Disconnect Test",
            agent_status="online"
        )
        db.add(agent)
        db.commit()
        db.close()
        
        # Connect
        mock_ws = AsyncMock()
        acf.connections["did:acn:agent:disconnect-test"] = mock_ws
        
        # Simulate disconnect
        del acf.connections["did:acn:agent:disconnect-test"]
        
        # Update status
        db = SessionLocal()
        agent = db.query(Agent).filter_by(agent_id="did:acn:agent:disconnect-test").first()
        agent.agent_status = "offline"
        db.commit()
        db.close()
        
        # Verify status updated
        db = SessionLocal()
        agent = db.query(Agent).filter_by(agent_id="did:acn:agent:disconnect-test").first()
        assert agent.agent_status == "offline"
        db.close()
    
    async def test_discovery_no_online_agents(self):
        """Test discovery when no agents are online"""
        from agent_gw.acf_server import ACFServer
        
        acf = ACFServer(host='localhost', port=9995)
        
        # Setup offline agents
        db = SessionLocal()
        for i in range(3):
            agent = Agent(
                agent_id=f"offline-agent-{i}",
                agent_status="offline",
                agent_capability=["camera"]
            )
            db.add(agent)
        db.commit()
        db.close()
        
        # Query online agents
        db = SessionLocal()
        online_agents = db.query(Agent).filter(Agent.agent_status == "online").all()
        assert len(online_agents) == 0
        db.close()
    
    async def test_capability_matching_edge_cases(self):
        """Test capability matching with edge cases"""
        from agent_gw.acf_server import ACFServer
        
        db = SessionLocal()
        
        # Agent with empty capabilities
        agent_empty = Agent(
            agent_id="agent-empty",
            agent_capability=[],
            agent_status="online"
        )
        db.add(agent_empty)
        
        # Agent with None capabilities
        agent_none = Agent(
            agent_id="agent-none",
            agent_capability=None,
            agent_status="online"
        )
        db.add(agent_none)
        
        # Agent with many capabilities
        agent_many = Agent(
            agent_id="agent-many",
            agent_capability=["cap" + str(i) for i in range(100)],
            agent_status="online"
        )
        db.add(agent_many)
        
        db.commit()
        db.close()
        
        # Test matching
        db = SessionLocal()
        agents = db.query(Agent).filter(Agent.agent_status == "online").all()
        
        required = ["cap1", "cap2"]
        matching = []
        
        for agent in agents:
            if agent.agent_capability:
                if set(agent.agent_capability) & set(required):
                    matching.append(agent)
        
        # Should only match agent-many
        assert len(matching) == 1
        assert matching[0].agent_id == "agent-many"
        db.close()

@pytest.mark.asyncio
class TestMultipleAgentsScenario:
    """Test scenarios with multiple agents"""
    
    async def test_many_agents_connect(self):
        """Test handling many agents connecting"""
        from agent_gw.acf_server import ACFServer
        
        acf = ACFServer(host='localhost', port=9994)
        
        # Create 10 agents
        num_agents = 10
        db = SessionLocal()
        
        for i in range(num_agents):
            agent = Agent(
                agent_id=f"agent-bulk-{i}",
                agent_name=f"Agent {i}",
                agent_status="offline",
                agent_capability=["capability"]
            )
            db.add(agent)
        
        db.commit()
        db.close()
        
        # Connect all agents
        for i in range(num_agents):
            mock_ws = AsyncMock()
            setup_msg = {
                "type": "SETUP",
                "payload": {"src_agent_id": f"agent-bulk-{i}"}
            }
            await acf.handle_setup(mock_ws, setup_msg)
        
        # Verify all connected
        assert len(acf.connections) == num_agents
        
        # Verify all online
        db = SessionLocal()
        online_count = db.query(Agent).filter(Agent.agent_status == "online").count()
        assert online_count == num_agents
        db.close()
    
    async def test_broadcast_message_to_multiple(self):
        """Test message handling with multiple recipients"""
        from agent_gw.acf_server import ACFServer
        
        acf = ACFServer(host='localhost', port=9993)
        
        # Setup multiple agents
        mock_ws_list = []
        for i in range(5):
            mock_ws = AsyncMock()
            acf.connections[f"agent-{i}"] = mock_ws
            mock_ws_list.append(mock_ws)
        
        # Send to specific agent
        msg = {
            "type": "TASK_REQUEST_COLLABORATION",
            "payload": {"dst_agent_id": "agent-2"}
        }
        
        await acf.handle_task_request_collaboration(msg)
        
        # Only agent-2 should receive
        for i, mock_ws in enumerate(mock_ws_list):
            if i == 2:
                mock_ws.send_text.assert_called_once()
            else:
                mock_ws.send_text.assert_not_called()

@pytest.mark.asyncio
class TestMOQTWithAgents:
    """Test MOQT Relay with agent scenarios"""
    
    async def test_agent_publishes_sensor_data(self):
        """Test agent sensor data being cached by the relay."""
        from moq import FullTrackName, Location
        from moq.relay import MOQRelay, CachedObject

        relay = MOQRelay(
            host='localhost',
            port=9992,
            cache_dir='.test_integration_cache',
        )

        track_name = FullTrackName([b'agent', b'sensors'], b'agent-1')

        for reading in range(10):
            relay.cache_object(
                track_name,
                CachedObject(
                    track_alias=1,
                    group_id=1,
                    object_id=reading,
                    publisher_priority=128,
                    payload=json.dumps({
                        'timestamp': datetime.utcnow().isoformat(),
                        'temperature': 20.0 + reading,
                        'humidity': 50.0 + reading,
                    }).encode('utf-8'),
                ),
            )

        stats = relay.get_cache_stats()
        assert stats['memory_objects'] == 10

        cached = relay.cache.get(track_name, Location(1, 0))
        assert cached is not None
        assert b'temperature' in cached.payload
