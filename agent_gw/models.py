#!/usr/bin/env python3
"""
Agent GW - Backend Application
Three functional entities:
- ARF (Agent Repository Function): HTTP on port 9001
- ACF (Agent Communication Function): WebSocket on port 9002
- MOQT Relay: MOQT protocol on port 9003
"""

from sqlalchemy import create_engine, Column, String, Integer, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import json
from pathlib import Path

Base = declarative_base()

class Agent(Base):
    __tablename__ = 'agents'
    
    agent_id = Column(String, primary_key=True)
    agent_name = Column(String)
    agent_capability = Column(JSON)  # List of strings
    agent_auth = Column(String)
    agent_status = Column(String, default='offline')  # online, offline
    priority = Column(Integer, default=0)
    
    tasks = relationship("Task", back_populates="agent")

class Task(Base):
    __tablename__ = 'tasks'
    __table_args__ = (
        UniqueConstraint('agent_id', 'task_id', name='uq_tasks_agent_id_task_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String, ForeignKey('agents.agent_id'))
    task_id = Column(String)
    task_description = Column(String)
    
    agent = relationship("Agent", back_populates="tasks")

class Track(Base):
    __tablename__ = 'tracks'
    __table_args__ = (
        UniqueConstraint('task_id', name='uq_tracks_task_id'),
    )
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    src_agent_id = Column(String)
    task_id = Column(String)
    track_list = Column(JSON)  # List of tracks

# Database setup
DB_PATH = Path(__file__).resolve().parent / 'agent_gw.db'
engine = create_engine(f'sqlite:///{DB_PATH}', echo=False)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

def get_db():
    return SessionLocal()
