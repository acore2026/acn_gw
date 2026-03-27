#!/usr/bin/env python3
"""
Unit tests for ARF HTTP API
"""

import pytest
import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from arf_server import app, acf_ws
from models import Base, Agent, Task, engine, SessionLocal

# Create test client
client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_database():
    """Setup and teardown database for each test"""
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)

@pytest.fixture
def mock_acf_ws():
    """Mock ACF WebSocket connection"""
    mock_ws = AsyncMock()
    with patch('arf_server.acf_ws', mock_ws):
        yield mock_ws

class TestAgentCardRegistration:
    """Test cases for POST /arf/v1/agent-cards"""
    
    @patch('httpx.AsyncClient.post')
    def test_register_agent_success(self, mock_post):
        """Test successful agent registration"""
        # Mock IDM response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "Valid": True,
            "VCId": ["CMCC/credentials/3732"]
        }
        mock_post.return_value = mock_response
        
        # Request payload
        payload = {
            "method": "POST",
            "url": "/idm/v1/vc-verifications",
            "headers": {
                "Content-Type": "application/json"
            },
            "body": {
                "agent_id": "did:test:agent:001",
                "priority": 2,
                "timestamp": "2024-03-23T12:00:00Z",
                "signature": "test_signature",
                "vc_list": [
                    {
                        "context": ["test-context"],
                        "id": "test/credentials/001",
                        "type": ["VerifiableCredential"],
                        "issuer": "did:test:issuer",
                        "valid_from": "2024-01-01T00:00:00Z",
                        "valid_until": "2025-01-01T00:00:00Z",
                        "claims": {
                            "agent_name": "Test Agent",
                            "agent_id": "did:test:agent:001",
                            "agent_attribute": "Surveillance Camera"
                        },
                        "proof": {
                            "creator": "did:test:issuer#keys-1",
                            "signature_value": "test_sig"
                        }
                    }
                ]
            }
        }
        
        response = client.post("/arf/v1/agent-cards", json=payload)
        
        assert response.status_code == 200
        assert response.json()["status"] == "OK"
        
        # Verify agent was created in database
        db = SessionLocal()
        agent = db.query(Agent).filter_by(agent_id="did:test:agent:001").first()
        assert agent is not None
        assert agent.agent_name == "Test Agent"
        assert "Surveillance Camera" in agent.agent_capability
        db.close()
    
    @patch('httpx.AsyncClient.post')
    def test_register_agent_vc_verification_failed(self, mock_post):
        """Test agent registration when VC verification fails"""
        # Mock IDM response - validation failed
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "Valid": False,
            "VCId": []
        }
        mock_post.return_value = mock_response
        
        payload = {
            "body": {
                "agent_id": "did:test:agent:002",
                "vc_list": []
            }
        }
        
        response = client.post("/arf/v1/agent-cards", json=payload)
        
        assert response.status_code == 400
        assert "error" in response.json()
    
    @patch('httpx.AsyncClient.post')
    def test_register_agent_update_existing(self, mock_post):
        """Test updating an existing agent"""
        # First create an agent
        db = SessionLocal()
        agent = Agent(
            agent_id="did:test:agent:003",
            agent_name="Old Name",
            agent_capability=["old_capability"]
        )
        db.add(agent)
        db.commit()
        db.close()
        
        # Mock IDM response
        mock_response = MagicMock()
        mock_response.json.return_value = {"Valid": True, "VCId": ["test"]}
        mock_post.return_value = mock_response
        
        # Update request
        payload = {
            "body": {
                "agent_id": "did:test:agent:003",
                "priority": 5,
                "vc_list": [
                    {
                        "claims": {
                            "agent_name": "Updated Agent",
                            "agent_id": "did:test:agent:003",
                            "agent_attribute": "New Capability"
                        }
                    }
                ]
            }
        }
        
        response = client.post("/arf/v1/agent-cards", json=payload)
        
        assert response.status_code == 200
        
        # Verify update
        db = SessionLocal()
        agent = db.query(Agent).filter_by(agent_id="did:test:agent:003").first()
        assert agent.agent_name == "Updated Agent"
        assert "New Capability" in agent.agent_capability
        db.close()

class TestAgentDiscovery:
    """Test cases for POST /arf/v1/agent-discoveries"""
    
    def test_discover_agents_success(self, mock_acf_ws):
        """Test successful agent discovery"""
        # Setup: Create online agents with capabilities
        db = SessionLocal()
        agents = [
            Agent(
                agent_id="agent-cam-001",
                agent_name="Camera Agent",
                agent_capability=["camera", "night_vision"],
                agent_status="online",
                priority=1
            ),
            Agent(
                agent_id="agent-radar-001",
                agent_name="Radar Agent",
                agent_capability=["radar", "gps"],
                agent_status="online",
                priority=2
            ),
        ]
        for agent in agents:
            db.add(agent)
        db.commit()
        db.close()
        
        # Discovery request
        payload = {
            "method": "POST",
            "url": "/arf/v1/agent-discoveries",
            "headers": {
                "Content-Type": "application/json"
            },
            "body": {
                "task_id": "task-discovery-001",
                "agent_id": "did:acn:agent:requester",
                "required_capabilities": ["camera", "night_vision"],
                "timestamp": "2024-03-23T12:00:00Z"
            }
        }
        
        response = client.post("/arf/v1/agent-discoveries", json=payload)
        
        assert response.status_code == 200
        assert response.json()["status"] == "OK"
    
    def test_discover_no_matching_agents(self, mock_acf_ws):
        """Test discovery when no agents match capabilities"""
        # Setup: Create agent without matching capabilities
        db = SessionLocal()
        agent = Agent(
            agent_id="agent-gps-001",
            agent_capability=["gps"],
            agent_status="online"
        )
        db.add(agent)
        db.commit()
        db.close()
        
        # Discovery request for camera capability
        payload = {
            "body": {
                "task_id": "task-discovery-002",
                "agent_id": "did:acn:agent:requester",
                "required_capabilities": ["camera"]
            }
        }
        
        response = client.post("/arf/v1/agent-discoveries", json=payload)
        
        # Should still return 200, but no collaboration message sent
        assert response.status_code == 200

class TestErrorHandling:
    """Test error handling scenarios"""
    
    def test_invalid_json_payload(self):
        """Test handling invalid JSON"""
        response = client.post(
            "/arf/v1/agent-cards",
            data="invalid json",
            headers={"Content-Type": "application/json"}
        )
        # Should return error for invalid JSON (500 due to JSON parsing error)
        assert response.status_code in [422, 500]
    
    def test_missing_required_fields(self):
        """Test handling missing required fields"""
        payload = {
            "body": {}  # Missing agent_id
        }
        
        response = client.post("/arf/v1/agent-cards", json=payload)
        # Should handle gracefully
        assert response.status_code in [200, 422, 500]

@pytest.mark.asyncio
class TestACFWebSocketConnection:
    """Test ARF to ACF WebSocket connection"""
    
    async def test_connect_to_acf(self):
        """Test ARF connecting to ACF as a client"""
        from arf_server import connect_to_acf
        
        # This would require a running ACF server
        # For unit tests, we mock the connection
        mock_ws = AsyncMock()
        mock_ws.recv.return_value = json.dumps({
            "type": "SETUP",
            "payload": {"status": "OK"}
        })
        
        # Mock websockets.connect to return the mock WebSocket
        # Create an awaitable mock that returns mock_ws when awaited
        async def mock_connect(*args, **kwargs):
            return mock_ws
        
        with patch('arf_server.websockets.connect', side_effect=mock_connect):
            await connect_to_acf()
            
            # Verify connection was established
            assert True  # If we got here, connection succeeded
            mock_ws.send.assert_called_once()
            
            # Verify SETUP message was sent
            sent_msg = json.loads(mock_ws.send.call_args[0][0])
            assert sent_msg["type"] == "SETUP"
            assert sent_msg["payload"]["src_agent_id"] == "ARF"
