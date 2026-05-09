#!/usr/bin/env python3
"""
Agent GW - Backend Application
Three functional entities:
- ARF (Agent Repository Function): HTTP on port 9001
- ACF (Agent Communication Function): WebSocket on port 9002
- MOQT Relay: MOQT protocol on port 9003
"""

import os
from sqlalchemy import (
    create_engine,
    Column,
    DateTime,
    String,
    Integer,
    JSON,
    ForeignKey,
    UniqueConstraint,
    text,
)
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
    setup_at = Column(DateTime)
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
        UniqueConstraint(
            'task_id',
            'src_agent_id',
            name='uq_tracks_task_id_src_agent_id',
        ),
    )
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    src_agent_id = Column(String)
    task_id = Column(String)
    track_list = Column(JSON)  # List of tracks

# Database setup
DB_PATH = Path(
    os.getenv('AGENT_GW_DB_PATH', Path(__file__).resolve().parent / 'agent_gw.db')
)
engine = create_engine(f'sqlite:///{DB_PATH}', echo=False)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)


def _tracks_has_legacy_task_unique(connection):
    """Return True when tracks still has the old UNIQUE(task_id) constraint."""
    indexes = connection.execute(text('PRAGMA index_list(tracks)')).fetchall()
    for index in indexes:
        is_unique = bool(index[2])
        if not is_unique:
            continue
        columns = connection.execute(text(f'PRAGMA index_info("{index[1]}")')).fetchall()
        column_names = [column[2] for column in columns]
        if column_names == ['task_id']:
            return True
    return False


def _migrate_tracks_unique_constraint():
    """Migrate old tracks UNIQUE(task_id) schema to UNIQUE(task_id, src_agent_id)."""
    with engine.begin() as connection:
        if not _tracks_has_legacy_task_unique(connection):
            return

        connection.execute(text('ALTER TABLE tracks RENAME TO tracks_legacy_task_unique'))
        connection.execute(text('''
            CREATE TABLE tracks (
                id INTEGER NOT NULL,
                src_agent_id VARCHAR,
                task_id VARCHAR,
                track_list JSON,
                PRIMARY KEY (id),
                CONSTRAINT uq_tracks_task_id_src_agent_id UNIQUE (task_id, src_agent_id)
            )
        '''))
        connection.execute(text('''
            INSERT OR IGNORE INTO tracks (id, src_agent_id, task_id, track_list)
            SELECT id, src_agent_id, task_id, track_list
            FROM tracks_legacy_task_unique
        '''))
        connection.execute(text('DROP TABLE tracks_legacy_task_unique'))


_migrate_tracks_unique_constraint()


def _add_column_if_missing(table_name, column_name, ddl):
    """Add a column to an existing SQLite table when upgrading old databases."""
    with engine.begin() as connection:
        columns = connection.execute(text(f'PRAGMA table_info("{table_name}")')).fetchall()
        column_names = [column[1] for column in columns]
        if column_name not in column_names:
            connection.execute(text(f'ALTER TABLE {table_name} ADD COLUMN {ddl}'))


_add_column_if_missing('agents', 'setup_at', 'setup_at DATETIME')


def get_db():
    return SessionLocal()
