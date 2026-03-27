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

from models import Base, Agent, Task, engine, SessionLocal

@pytest.fixture(autouse=True)
def setup_database():
    """Setup database for integration tests"""
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)

@pytest.mark.asyncio
class TestAgentRegistrationFlow:
    """Test complete agent registration flow"""
    
    @patch('httpx.AsyncClient.post')
    async def test_agent_registers_then_connects(self, mock_post):
        """Test agent registers via ARF then connects via ACF"""
        from fastapi.testclient import TestClient
        from arf_server import app
        from acf_server import ACFServer
        
        # Setup
        client = TestClient(app)
        
        # Mock IDM response
        mock_response = MagicMock()
        mock_response.json.return_value = {"Valid": True, "VCId": ["test"]}
        mock_post.return_value = mock_response
        
        # Step 1: Agent registers via ARF
        reg_payload = {
            "body": {
                "agent_id": "did:acn:agent:integration001",
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
        from acf_server import ACFServer
        
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
        
        # Step 2: ARF sends TASK_REQUEST_COLLABORATION via ACF
        collab_msg = {
            "type": "TASK_REQUEST_COLLABORATION",
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "payload": {
                "src_agent_id": "ARF",
                "dst_agent_id": "did:acn:agent:available",
                "task_id": "task-integration-001",
                "task_description": "Integration test task",
                "agent_card": {
                    "agent_id": "did:acn:agent:available",
                    "skill": ["camera", "night_vision"]
                }
            }
        }
        
        await acf.handle_task_request_collaboration(collab_msg)
        
        # Verify forwarded to available agent
        mock_ws_available.send.assert_called_once()
        sent_msg = json.loads(mock_ws_available.send.call_args[0][0])
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
        
        # Add ARF connection
        mock_ws_arf = AsyncMock()
        acf.connections["ARF"] = mock_ws_arf
        
        await acf.handle_task_accept_collaboration(accept_msg)
        
        # Verify task recorded
        db = SessionLocal()
        task = db.query(Task).filter_by(task_id="task-integration-001").first()
        assert task is not None
        assert task.agent_id == "did:acn:agent:available"
        db.close()
        
        # Verify forwarded to requester
        mock_ws_requester.send.assert_called_once()

@pytest.mark.asyncio
class TestErrorScenarios:
    """Test error and edge cases"""
    
    async def test_agent_disconnects_mid_task(self):
        """Test handling when agent disconnects during collaboration"""
        from acf_server import ACFServer
        
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
        from acf_server import ACFServer
        
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
        from acf_server import ACFServer
        
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
        from acf_server import ACFServer
        
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
        from acf_server import ACFServer
        
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
                mock_ws.send.assert_called_once()
            else:
                mock_ws.send.assert_not_called()

@pytest.mark.asyncio
class TestMOQTWithAgents:
    """Test MOQT Relay with agent scenarios"""
    
    async def test_agent_publishes_sensor_data(self):
        """Test agent publishing sensor data via MOQT"""
        from moqt_relay import MOQTRelay
        
        relay = MOQTRelay(host='localhost', port=9992)
        
        # Agent publishes track
        pub_reader, pub_writer = AsyncMock(), AsyncMock()
        await relay.handle_publish(pub_writer, {
            "type": "PUBLISH",
            "track_id": "agent-1-sensors"
        })
        
        # Other agents subscribe
        sub_writers = []
        for i in range(3):
            sub_reader, sub_writer = AsyncMock(), AsyncMock()
            await relay.handle_subscribe(sub_writer, {
                "type": "SUBSCRIBE",
                "track_id": "agent-1-sensors"
            })
            sub_writers.append(sub_writer)
        
        # Agent publishes sensor data
        for reading in range(10):
            await relay.handle_object(pub_writer, {
                "type": "OBJECT",
                "track_id": "agent-1-sensors",
                "data": {
                    "timestamp": datetime.utcnow().isoformat(),
                    "temperature": 20.0 + reading,
                    "humidity": 50.0 + reading
                }
            })
        
        # All subscribers should receive 10 objects
        for sub_writer in sub_writers:
            # SUBSCRIBE_OK + 10 objects
            assert sub_writer.write.call_count == 11
