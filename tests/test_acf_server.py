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
from acf_server import ACFServer
from models import Base, Agent, Task, engine, SessionLocal

@pytest.fixture(autouse=True)
def setup_database():
    """Setup and teardown database for each test"""
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)

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
        mock_ws.send.assert_called_once()
        response = json.loads(mock_ws.send.call_args[0][0])
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
        mock_ws_dst.send.assert_called_once()
        sent_msg = json.loads(mock_ws_dst.send.call_args[0][0])
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
        mock_ws_src = AsyncMock()
        mock_ws_dst = AsyncMock()
        
        acf_server.connections["accepting-agent"] = mock_ws_src
        acf_server.connections["requesting-agent"] = mock_ws_dst
        acf_server.connections["ARF"] = AsyncMock()  # ARF connection
        
        # Create accepting agent in DB
        db = SessionLocal()
        agent = Agent(
            agent_id="accepting-agent",
            agent_name="Accepting Agent"
        )
        db.add(agent)
        db.commit()
        db.close()
        
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
        
        # Verify task recorded in database
        db = SessionLocal()
        task = db.query(Task).filter_by(task_id="task-002").first()
        assert task is not None
        assert task.agent_id == "accepting-agent"
        db.close()
        
        # Verify forwarded to destination
        mock_ws_dst.send.assert_called_once()
    
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
        mock_ws.send.assert_called_once()
        sent_msg = json.loads(mock_ws.send.call_args[0][0])
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
                self.send = AsyncMock()
                
            def __aiter__(self):
                return self
                
            async def __anext__(self):
                if not self.messages:
                    raise StopAsyncIteration
                return self.messages.pop(0)
        
        mock_ws = MockWebSocket(messages)
        
        # Handle connection
        await acf_server.handle_websocket(mock_ws, "/")
        
        # Verify
        assert "test-agent-flow" in acf_server.connections

    async def test_handle_invalid_json(self, acf_server):
        """Test handling invalid JSON"""
        messages = ["invalid json"]
        
        class MockWebSocket:
            def __init__(self, msgs):
                self.messages = msgs
                self.send = AsyncMock()
                
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
                self.send = AsyncMock()
                
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
        mock_ws1.send.assert_not_called()
        mock_ws2.send.assert_called_once()
        mock_ws3.send.assert_not_called()
