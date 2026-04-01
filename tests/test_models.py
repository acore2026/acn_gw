#!/usr/bin/env python3
"""
Unit tests for Database Models
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_gw.models import Base, Agent, Task, Track, SessionLocal, engine

@pytest.fixture
def db_session():
    """Create a fresh database session for each test"""
    # Create all tables
    Base.metadata.create_all(engine)
    
    session = SessionLocal()
    yield session
    
    # Cleanup
    session.close()
    Base.metadata.drop_all(engine)

class TestAgentModel:
    """Test cases for Agent model"""
    
    def test_create_agent(self, db_session):
        """Test creating an agent"""
        agent = Agent(
            agent_id="did:acn:agent:111111111",
            agent_name="Test Agent",
            agent_capability=["camera", "radar"],
            agent_auth="test_auth",
            agent_status="offline",
            priority=1
        )
        db_session.add(agent)
        db_session.commit()
        
        # Verify
        result = db_session.query(Agent).filter_by(agent_id="did:acn:agent:111111111").first()
        assert result is not None
        assert result.agent_name == "Test Agent"
        assert result.agent_capability == ["camera", "radar"]
        assert result.agent_status == "offline"
        assert result.priority == 1
    
    def test_update_agent_status(self, db_session):
        """Test updating agent status"""
        agent = Agent(
            agent_id="did:acn:agent:222222222",
            agent_name="Test Agent 2",
            agent_capability=["microphone"],
            agent_status="offline"
        )
        db_session.add(agent)
        db_session.commit()
        
        # Update status
        agent.agent_status = "online"
        db_session.commit()
        
        # Verify
        result = db_session.query(Agent).filter_by(agent_id="did:acn:agent:222222222").first()
        assert result.agent_status == "online"
    
    def test_agent_capability_as_list(self, db_session):
        """Test that agent_capability is stored as JSON list"""
        capabilities = ["camera", "radar", "gps", "lidar"]
        agent = Agent(
            agent_id="did:acn:agent:333333333",
            agent_name="Multi-capability Agent",
            agent_capability=capabilities
        )
        db_session.add(agent)
        db_session.commit()
        
        result = db_session.query(Agent).filter_by(agent_id="did:acn:agent:333333333").first()
        assert isinstance(result.agent_capability, list)
        assert len(result.agent_capability) == 4
        assert "camera" in result.agent_capability

class TestTaskModel:
    """Test cases for Task model"""
    
    def test_create_task(self, db_session):
        """Test creating a task"""
        # First create an agent
        agent = Agent(
            agent_id="did:acn:agent:444444444",
            agent_name="Task Owner"
        )
        db_session.add(agent)
        db_session.commit()
        
        # Create task
        task = Task(
            agent_id="did:acn:agent:444444444",
            task_id="task-12345",
            task_description="Test collaboration task"
        )
        db_session.add(task)
        db_session.commit()
        
        # Verify
        result = db_session.query(Task).filter_by(task_id="task-12345").first()
        assert result is not None
        assert result.task_description == "Test collaboration task"
        assert result.agent_id == "did:acn:agent:444444444"
    
    def test_agent_task_relationship(self, db_session):
        """Test relationship between Agent and Task"""
        agent = Agent(
            agent_id="did:acn:agent:555555555",
            agent_name="Multi-task Agent"
        )
        db_session.add(agent)
        db_session.commit()
        
        # Create multiple tasks
        for i in range(3):
            task = Task(
                agent_id="did:acn:agent:555555555",
                task_id=f"task-{i}",
                task_description=f"Task {i}"
            )
            db_session.add(task)
        db_session.commit()
        
        # Verify relationship
        agent = db_session.query(Agent).filter_by(agent_id="did:acn:agent:555555555").first()
        assert len(agent.tasks) == 3

class TestTrackModel:
    """Test cases for Track model"""
    
    def test_create_track(self, db_session):
        """Test creating a track"""
        track = Track(
            src_agent_id="did:acn:agent:444444444",
            task_id="task-12345",
            track_list=["track-1", "track-2", "track-3"]
        )
        db_session.add(track)
        db_session.commit()
        
        # Verify
        result = db_session.query(Track).filter_by(task_id="task-12345").first()
        assert result is not None
        assert result.src_agent_id == "did:acn:agent:444444444"
        assert len(result.track_list) == 3
        assert "track-1" in result.track_list

class TestAgentDiscoveryQuery:
    """Test agent discovery queries"""
    
    def test_find_online_agents_not_in_tasks(self, db_session):
        """Test finding online agents not assigned to tasks"""
        # Create agents
        agents = [
            Agent(agent_id="agent-1", agent_status="online", agent_capability=["camera"]),
            Agent(agent_id="agent-2", agent_status="online", agent_capability=["radar"]),
            Agent(agent_id="agent-3", agent_status="offline", agent_capability=["gps"]),
            Agent(agent_id="agent-4", agent_status="online", agent_capability=["lidar"]),
        ]
        for agent in agents:
            db_session.add(agent)
        db_session.commit()
        
        # Assign task to agent-2
        task = Task(agent_id="agent-2", task_id="task-1", task_description="Test")
        db_session.add(task)
        db_session.commit()
        
        # Query: online agents not in tasks
        from sqlalchemy import not_
        agents_in_tasks = db_session.query(Task.agent_id).distinct().all()
        agents_in_tasks = [a[0] for a in agents_in_tasks]
        
        candidates = db_session.query(Agent).filter(
            Agent.agent_status == "online",
            not_(Agent.agent_id.in_(agents_in_tasks))
        ).all()
        
        # Should return agent-1 and agent-4
        assert len(candidates) == 2
        candidate_ids = [a.agent_id for a in candidates]
        assert "agent-1" in candidate_ids
        assert "agent-4" in candidate_ids
        assert "agent-2" not in candidate_ids  # Has task
        assert "agent-3" not in candidate_ids  # Offline
    
    def test_capability_matching(self, db_session):
        """Test capability matching for discovery"""
        # Create agents with different capabilities
        agents = [
            Agent(agent_id="agent-a", agent_capability=["camera", "radar"], priority=1),
            Agent(agent_id="agent-b", agent_capability=["camera", "gps"], priority=2),
            Agent(agent_id="agent-c", agent_capability=["radar", "lidar"], priority=3),
        ]
        for agent in agents:
            db_session.add(agent)
        db_session.commit()
        
        # Find agents matching required capabilities
        required_capabilities = ["camera"]
        all_agents = db_session.query(Agent).all()
        
        scored_agents = []
        for agent in all_agents:
            if agent.agent_capability:
                matching = set(agent.agent_capability) & set(required_capabilities)
                score = len(matching)
                if score > 0:
                    scored_agents.append((agent, score))
        
        # Should match agent-a (score 1) and agent-b (score 1)
        assert len(scored_agents) == 2
        agent_ids = [a[0].agent_id for a in scored_agents]
        assert "agent-a" in agent_ids
        assert "agent-b" in agent_ids
        assert "agent-c" not in agent_ids
