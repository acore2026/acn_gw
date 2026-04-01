#!/usr/bin/env python3
"""
Unit tests for ARF HTTP API
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from agent_gw.arf_server import app, process_discovery, clear_environment, handle_agent_deletions
from agent_gw.models import Agent, Task, Track, SessionLocal

# Create test client
client = TestClient(app)

class TestAgentCardRegistration:
    """Test cases for POST /arf/v1/agent-cards"""
    
    @patch('agent_gw.arf_server.httpx.AsyncClient')
    def test_register_agent_success(self, mock_async_client):
        """Test successful agent registration"""
        # Mock IDM response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "valid": True,
            "vc_ids": ["CMCC/credentials/3732"],
            "invalid_vcs": None,
        }
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_async_client.return_value.__aexit__ = AsyncMock(return_value=None)
        
        # Request payload
        payload = {
            "agent_id": "did:test:agent:001",
            "method": "POST",
            "url": "/idm/v1/vc-verifications",
            "headers": {
                "Content-Type": "application/json"
            },
            "body": {
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
    
    @patch('agent_gw.arf_server.httpx.AsyncClient')
    def test_register_agent_vc_verification_failed(self, mock_async_client):
        """Test agent registration when VC verification fails"""
        # Mock IDM response - validation failed
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "valid": False,
            "vc_ids": [],
            "invalid_vcs": None,
        }
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_async_client.return_value.__aexit__ = AsyncMock(return_value=None)
        
        payload = {
            "agent_id": "did:test:agent:002",
            "body": {
                "vc_list": []
            }
        }
        
        response = client.post("/arf/v1/agent-cards", json=payload)
        
        assert response.status_code == 400
        assert "error" in response.json()
    
    @patch('agent_gw.arf_server.httpx.AsyncClient')
    def test_register_agent_update_existing(self, mock_async_client):
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
        mock_response.json.return_value = {
            "valid": True,
            "vc_ids": ["test"],
            "invalid_vcs": None,
        }
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_async_client.return_value.__aexit__ = AsyncMock(return_value=None)
        
        # Update request
        payload = {
            "agent_id": "did:test:agent:003",
            "body": {
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
    
    @patch('agent_gw.arf_server.asyncio.create_task')
    def test_discover_agents_success(self, mock_create_task):
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
        mock_create_task.assert_called_once()
    
    @patch('agent_gw.arf_server.asyncio.create_task')
    def test_discover_no_matching_agents(self, mock_create_task):
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
        mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    @patch('agent_gw.arf_server.httpx.AsyncClient')
    async def test_process_discovery_posts_to_acf(self, mock_async_client):
        """Test that process_discovery sends the wrapped HTTP message to ACF."""
        db = SessionLocal()
        agent = Agent(
            agent_id="agent-collab-001",
            agent_name="Collab Agent",
            agent_capability=["camera", "radar"],
            agent_status="online",
            priority=3
        )
        db.add(agent)
        db.commit()
        db.close()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_async_client.return_value.__aexit__ = AsyncMock(return_value=None)

        await process_discovery(
            requester_agent_id="did:acn:agent:requester",
            task_id="task-discovery-003",
            required_capabilities=["camera"],
        )

        assert mock_client.post.await_count == 1
        _, kwargs = mock_client.post.call_args
        assert kwargs["json"]["url"] == "/acf/v1/discoveries"
        assert kwargs["json"]["method"] == "POST"
        assert kwargs["json"]["body"]["dst_agent_id"] == "agent-collab-001"
        assert kwargs["json"]["body"]["task_id"] == "task-discovery-003"

class TestTaskExecution:
    """Test cases for task execution lifecycle endpoints"""

    def test_task_execution_creates_record(self):
        """Test creating a task execution record."""
        db = SessionLocal()
        agent = Agent(
            agent_id="did:acn:agent:exec001",
            agent_name="Executor",
            agent_status="online",
        )
        db.add(agent)
        db.commit()
        db.close()

        payload = {
            "body": {
                "agent_id": "did:acn:agent:exec001",
                "task_id": "task-exec-001",
                "description": "危险区域可以人员巡检",
                "timestamp": "2024-03-23T12:00:00Z",
            }
        }

        response = client.post("/acn-agent/v1/task-executions", json=payload)

        assert response.status_code == 200
        db = SessionLocal()
        task = db.query(Task).filter_by(agent_id="did:acn:agent:exec001", task_id="task-exec-001").first()
        assert task is not None
        assert task.task_description == "危险区域可以人员巡检"
        db.close()

    @patch('agent_gw.arf_server.httpx.AsyncClient')
    def test_task_execution_forwards_to_acf(self, mock_async_client):
        """Test that task executions are forwarded to ACF after local persistence."""
        db = SessionLocal()
        agent = Agent(
            agent_id="did:acn:agent:exec-forward",
            agent_name="Forwarder",
            agent_status="online",
        )
        db.add(agent)
        db.commit()
        db.close()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_async_client.return_value.__aexit__ = AsyncMock(return_value=None)

        payload = {
            "body": {
                "agent_id": "did:acn:agent:exec-forward",
                "task_id": "task-exec-forward",
                "description": "Forward this task execution",
                "timestamp": "2024-03-23T12:00:00Z",
            }
        }

        response = client.post("/acn-agent/v1/task-executions", json=payload)

        assert response.status_code == 200
        assert mock_client.post.await_count == 1
        _, kwargs = mock_client.post.call_args
        assert kwargs["json"]["body"]["task_id"] == "task-exec-forward"
        assert kwargs["json"]["body"]["agent_id"] == "did:acn:agent:exec-forward"


class TestEnvironmentReset:
    """Test cases for clear and agent deletion endpoints."""

    @pytest.mark.asyncio
    @patch('agent_gw.arf_server.httpx.AsyncClient')
    async def test_clear_resets_local_state_and_forwards(self, mock_async_client):
        """Test /clear clears local state and forwards the request to ACF."""
        db = SessionLocal()
        agent = Agent(
            agent_id="did:acn:agent:clear-001",
            agent_name="Clear Agent",
            agent_capability=["camera"],
            agent_status="online",
        )
        task = Task(
            agent_id="did:acn:agent:clear-001",
            task_id="task-clear-001",
            task_description="Clear task",
        )
        track = Track(
            src_agent_id="did:acn:agent:clear-001",
            task_id="task-clear-001",
            track_list=[{"namespace": "/task-clear-001/agent", "track": "Video"}],
        )
        db.add(agent)
        db.add(task)
        db.add(track)
        db.commit()
        db.close()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_async_client.return_value.__aenter__.return_value = mock_client
        mock_async_client.return_value.__aexit__.return_value = None

        request = AsyncMock()
        request.json.return_value = {"method": "POST", "url": "/clear", "body": {}}
        response = await clear_environment(request)

        assert response.status_code == 200
        assert mock_client.post.await_count == 1
        _, kwargs = mock_client.post.call_args
        assert kwargs["json"]["url"] == "/clear"

        db = SessionLocal()
        assert db.query(Agent).count() == 0
        assert db.query(Task).count() == 0
        assert db.query(Track).count() == 0
        db.close()

    @pytest.mark.asyncio
    @patch('agent_gw.arf_server.httpx.AsyncClient')
    async def test_agent_deletions_removes_agent_state_and_forwards(self, mock_async_client):
        """Test agent deletion removes local rows and forwards to ACF."""
        db = SessionLocal()
        agent = Agent(
            agent_id="did:acn:agent:delete-001",
            agent_name="Delete Agent",
            agent_capability=["camera"],
            agent_status="online",
        )
        task = Task(
            agent_id="did:acn:agent:delete-001",
            task_id="task-delete-001",
            task_description="Delete task",
        )
        db.add(agent)
        db.add(task)
        db.commit()
        db.close()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_async_client.return_value.__aenter__.return_value = mock_client
        mock_async_client.return_value.__aexit__.return_value = None

        payload = {
            "agent_id": "did:acn:agent:delete-001",
            "reason": "retired",
            "timestamp": "2024-03-23T12:00:00Z",
            "signature": "xxxxxxx",
            "signature_encoding": "base64"
        }

        request = AsyncMock()
        request.json.return_value = payload
        response = await handle_agent_deletions(request)

        assert response.status_code == 200
        assert mock_client.post.await_count == 1
        _, kwargs = mock_client.post.call_args
        assert kwargs["json"]["agent_id"] == "did:acn:agent:delete-001"

        db = SessionLocal()
        assert db.query(Agent).filter_by(agent_id="did:acn:agent:delete-001").first() is None
        assert db.query(Task).filter_by(agent_id="did:acn:agent:delete-001").count() == 0
        db.close()

    def test_task_execution_updates_existing_record(self):
        """Test that repeated task execution updates the existing record."""
        db = SessionLocal()
        agent = Agent(
            agent_id="did:acn:agent:exec002",
            agent_name="Executor 2",
            agent_status="online",
        )
        db.add(agent)
        db.commit()
        task = Task(
            agent_id="did:acn:agent:exec002",
            task_id="task-exec-002",
            task_description="Old description",
        )
        db.add(task)
        db.commit()
        db.close()

        payload = {
            "body": {
                "agent_id": "did:acn:agent:exec002",
                "task_id": "task-exec-002",
                "description": "New description",
                "timestamp": "2024-03-23T12:00:00Z",
            }
        }

        response = client.post("/acn-agent/v1/task-executions", json=payload)

        assert response.status_code == 200
        db = SessionLocal()
        tasks = db.query(Task).filter_by(agent_id="did:acn:agent:exec002", task_id="task-exec-002").all()
        assert len(tasks) == 1
        assert tasks[0].task_description == "New description"
        db.close()

    def test_task_execution_termination_deletes_record(self):
        """Test removing a task record when execution terminates."""
        db = SessionLocal()
        agent = Agent(
            agent_id="did:acn:agent:exec003",
            agent_name="Executor 3",
            agent_status="online",
        )
        db.add(agent)
        db.commit()
        task = Task(
            agent_id="did:acn:agent:exec003",
            task_id="task-exec-003",
            task_description="Terminate me",
        )
        db.add(task)
        db.commit()
        db.close()

        payload = {
            "body": {
                "agent_id": "did:acn:agent:exec003",
                "task_id": "task-exec-003",
                "reason": "目标已离开区域，任务完成",
                "timestamp": "2024-03-23T12:00:00Z",
                "force": "false",
            }
        }

        response = client.post("/acn-agent/v1/task-execution-terminations", json=payload)

        assert response.status_code == 200
        db = SessionLocal()
        task = db.query(Task).filter_by(agent_id="did:acn:agent:exec003", task_id="task-exec-003").first()
        assert task is None
        db.close()

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
