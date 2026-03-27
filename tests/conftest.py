#!/usr/bin/env python3
"""
Pytest configuration and shared fixtures
"""

import pytest
import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure pytest-asyncio
@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test session."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(autouse=True)
def reset_database():
    """Reset database before each test"""
    from models import Base, engine
    # Clean up any existing tables
    Base.metadata.drop_all(engine)
    # Create fresh tables
    Base.metadata.create_all(engine)
    yield
    # Cleanup after test
    Base.metadata.drop_all(engine)

@pytest.fixture
def test_agent_data():
    """Provide test agent data"""
    return {
        "agent_id": "did:acn:agent:test001",
        "agent_name": "Test Agent",
        "agent_capability": ["camera", "radar"],
        "agent_auth": "test_auth_token",
        "agent_status": "offline",
        "priority": 1
    }

@pytest.fixture
def test_vc_data():
    """Provide test VC (Verifiable Credential) data"""
    return {
        "context": ["3gpp-ts-33.xxx-v20.0.0"],
        "id": "test/credentials/001",
        "type": ["VerifiableCredential", "TestCredential"],
        "issuer": "did:test:issuer",
        "valid_from": "2024-01-01T00:00:00Z",
        "valid_until": "2025-01-01T00:00:00Z",
        "claims": {
            "agent_name": "Test Agent",
            "agent_id": "did:test:agent:001",
            "agent_attribute": "Test Capability"
        },
        "proof": {
            "creator": "did:test:issuer#keys-1",
            "signature_value": "test_signature"
        }
    }

@pytest.fixture
def test_setup_message():
    """Provide test SETUP message"""
    return {
        "type": "SETUP",
        "timestamp": "2025-01-01T00:00:00Z",
        "payload": {
            "src_agent_id": "did:acn:agent:test001"
        }
    }

@pytest.fixture
def test_collaboration_request():
    """Provide test TASK_REQUEST_COLLABORATION message"""
    return {
        "type": "TASK_REQUEST_COLLABORATION",
        "timestamp": "2025-01-01T00:00:00Z",
        "payload": {
            "src_agent_id": "did:acn:agent:src",
            "dst_agent_id": "did:acn:agent:dst",
            "task_id": "task-test-001",
            "task_description": "Test collaboration task",
            "agent_card": {
                "agent_id": "did:acn:agent:dst",
                "skill": ["camera", "night_vision"]
            }
        }
    }

@pytest.fixture
def test_collaboration_accept():
    """Provide test TASK_ACCEPT_COLLABORATION message"""
    return {
        "type": "TASK_ACCEPT_COLLABORATION",
        "timestamp": "2025-01-01T00:00:00Z",
        "payload": {
            "src_agent_id": "did:acn:agent:accepting",
            "dst_agent_id": "did:acn:agent:requester",
            "task_id": "task-test-001",
            "result": "OK"
        }
    }

@pytest.fixture
def test_discover_result():
    """Provide test DISCOVER_RESULT message"""
    return {
        "type": "DISCOVER_RESULT",
        "timestamp": "2025-01-01T00:00:00Z",
        "payload": {
            "src_agent_id": "ARF",
            "dst_agent_id": "did:acn:agent:discoverer",
            "discover_result": ["did:acn:agent:found"]
        }
    }

@pytest.fixture
def mock_websocket():
    """Provide a mock WebSocket"""
    from unittest.mock import AsyncMock
    mock_ws = AsyncMock()
    mock_ws.send = AsyncMock()
    mock_ws.recv = AsyncMock()
    return mock_ws
