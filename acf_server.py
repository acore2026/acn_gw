#!/usr/bin/env python3
"""
ACF - Agent Communication Function
WebSocket server on port 9002
Manages WebSocket connections for agents
"""

import asyncio
import websockets
import json
from datetime import datetime
from models import get_db, Agent, Task

class ACFServer:
    def __init__(self, host='0.0.0.0', port=9002):
        self.host = host
        self.port = port
        self.connections = {}  # Map: agent_id -> websocket
        self.arf_ws = None  # ARF WebSocket connection
        
    async def handle_websocket(self, websocket, path):
        """Handle WebSocket connections"""
        agent_id = None
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get('type')
                    
                    if msg_type == 'SETUP':
                        await self.handle_setup(websocket, data)
                        agent_id = data['payload']['src_agent_id']
                    elif msg_type == 'TASK_REQUEST_COLLABORATION':
                        await self.handle_task_request_collaboration(data)
                    elif msg_type == 'TASK_ACCEPT_COLLABORATION':
                        await self.handle_task_accept_collaboration(data)
                    elif msg_type == 'DISCOVER_RESULT':
                        await self.handle_discover_result(data)
                    else:
                        print(f"ACF: Unknown message type: {msg_type}")
                        
                except json.JSONDecodeError:
                    print(f"ACF: Invalid JSON received")
                except Exception as e:
                    print(f"ACF: Error processing message: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            print(f"ACF: Connection closed for agent {agent_id}")
        finally:
            if agent_id and agent_id in self.connections:
                del self.connections[agent_id]
                # Update agent status to offline
                db = get_db()
                agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
                if agent:
                    agent.agent_status = 'offline'
                    db.commit()
                db.close()
                print(f"ACF: Agent {agent_id} disconnected")
    
    async def handle_setup(self, websocket, data):
        """Handle SETUP message from agent"""
        agent_id = data['payload']['src_agent_id']
        
        # Store connection
        self.connections[agent_id] = websocket
        
        # Update agent status to online
        db = get_db()
        agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
        if agent:
            agent.agent_status = 'online'
            db.commit()
        db.close()
        
        print(f"ACF: Agent {agent_id} connected and status set to online")
        
        # Send SETUP response
        response = {
            "type": "SETUP",
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "payload": {
                "status": "OK"
            }
        }
        await websocket.send(json.dumps(response))
    
    async def handle_task_request_collaboration(self, data):
        """Forward TASK_REQUEST_COLLABORATION to destination agent"""
        dst_agent_id = data['payload']['dst_agent_id']
        
        if dst_agent_id in self.connections:
            await self.connections[dst_agent_id].send(json.dumps(data))
            print(f"ACF: Forwarded TASK_REQUEST_COLLABORATION to {dst_agent_id}")
        else:
            print(f"ACF: Destination agent {dst_agent_id} not connected")
    
    async def handle_task_accept_collaboration(self, data):
        """Handle TASK_ACCEPT_COLLABORATION"""
        dst_agent_id = data['payload']['dst_agent_id']
        
        # Update Task table
        src_agent_id = data['payload']['src_agent_id']
        task_id = data['payload']['task_id']
        
        db = get_db()
        # Check if task exists for this agent
        existing_task = db.query(Task).filter(
            Task.agent_id == src_agent_id,
            Task.task_id == task_id
        ).first()
        
        if not existing_task:
            # Create new task entry
            task = Task(
                agent_id=src_agent_id,
                task_id=task_id,
                task_description="Collaboration task"
            )
            db.add(task)
            db.commit()
        
        db.close()
        
        # Forward to ARF
        if self.arf_ws:
            await self.arf_ws.send(json.dumps(data))
            print(f"ACF: Forwarded TASK_ACCEPT_COLLABORATION to ARF")
        
        # Forward to destination if not ARF
        if dst_agent_id != 'ARF' and dst_agent_id in self.connections:
            await self.connections[dst_agent_id].send(json.dumps(data))
            print(f"ACF: Forwarded TASK_ACCEPT_COLLABORATION to {dst_agent_id}")
    
    async def handle_discover_result(self, data):
        """Forward DISCOVER_RESULT to destination agent"""
        dst_agent_id = data['payload']['dst_agent_id']
        
        if dst_agent_id in self.connections:
            await self.connections[dst_agent_id].send(json.dumps(data))
            print(f"ACF: Forwarded DISCOVER_RESULT to {dst_agent_id}")
        else:
            print(f"ACF: Destination agent {dst_agent_id} not connected")
    
    async def connect_to_arf(self):
        """Connect to ARF as a client"""
        try:
            self.arf_ws = await websockets.connect('ws://localhost:9001/ws')
            
            # Send SETUP message
            setup_msg = {
                "type": "SETUP",
                "timestamp": datetime.utcnow().isoformat() + 'Z',
                "payload": {
                    "src_agent_id": "ACF"
                }
            }
            await self.arf_ws.send(json.dumps(setup_msg))
            
            # Wait for response
            response = await self.arf_ws.recv()
            print(f"ACF: Connected to ARF, response: {response}")
            
        except Exception as e:
            print(f"ACF: Failed to connect to ARF: {e}")
    
    async def start(self):
        """Start the WebSocket server"""
        # First connect to ARF
        await self.connect_to_arf()
        
        # Start WebSocket server
        async with websockets.serve(self.handle_websocket, self.host, self.port):
            print(f"ACF WebSocket Server started on ws://{self.host}:{self.port}")
            await asyncio.Future()  # Run forever

if __name__ == '__main__':
    server = ACFServer()
    asyncio.run(server.start())
