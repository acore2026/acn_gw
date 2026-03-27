#!/usr/bin/env python3
"""
Agent GW - Backend Application
Three functional entities:
- ARF (Agent Repository Function): HTTP on port 9001
- ACF (Agent Communication Function): WebSocket on port 9002
- MOQT Relay: MOQT protocol on port 9003
"""

from sqlalchemy import create_engine, Column, String, Integer, JSON, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import json

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
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String, ForeignKey('agents.agent_id'))
    task_id = Column(String)
    task_description = Column(String)
    
    agent = relationship("Agent", back_populates="tasks")

class Track(Base):
    __tablename__ = 'tracks'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String)
    track_list = Column(JSON)  # List of tracks

# Database setup
engine = create_engine('sqlite:///agent_gw.db', echo=False)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        return db
    finally:
        db.close()
