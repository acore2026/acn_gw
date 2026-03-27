#!/usr/bin/env python3
"""
ARF - Agent Repository Function
HTTP server on port 9001
Handles agent registration and discovery
"""

import asyncio
import websockets
import json
import httpx
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import uvicorn
from models import get_db, Agent, Task
from typing import List
from logger_config import arf_logger

app = FastAPI(title="ARF - Agent Repository Function")

# ACF WebSocket connection (ARF connects to ACF as a client)
acf_ws = None

IDM_URL = "http://10.0.18.210:9020/idm/v1/vc-verifications"

@app.post("/arf/v1/agent-cards")
async def register_agent_card(request: Request):
    """Register agent card - receives agent credentials and validates with IDM"""
    try:
        data = await request.json()
        
        # Forward to IDM for verification
        async with httpx.AsyncClient() as client:
            response = await client.post(IDM_URL, json=data)
            idm_result = response.json()
        
        # Check if validation passed
        if not idm_result.get('Valid', False):
            return JSONResponse(
                status_code=400,
                content={"error": "VC verification failed"}
            )
        
        # Extract agent information from VC
        body = data.get('body', {})
        vc_list = body.get('vc_list', [])
        
        agent_id = None
        agent_name = None
        capabilities = []
        
        for vc in vc_list:
            claims = vc.get('claims', {})
            if not agent_id:
                agent_id = claims.get('agent_id')
            if not agent_name:
                agent_name = claims.get('agent_name')
            
            # Extract agent_attribute as capability
            agent_attr = claims.get('agent_attribute')
            if agent_attr and agent_attr not in capabilities:
                capabilities.append(agent_attr)
        
        # Update Agent table
        db = get_db()
        existing_agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
        
        if existing_agent:
            existing_agent.agent_name = agent_name
            existing_agent.agent_capability = capabilities
        else:
            new_agent = Agent(
                agent_id=agent_id,
                agent_name=agent_name,
                agent_capability=capabilities,
                agent_status='offline',
                priority=body.get('priority', 0)
            )
            db.add(new_agent)
        
        db.commit()
        db.close()
        
        arf_logger.info(f"Agent {agent_id} registered with capabilities: {capabilities}")
        
        return JSONResponse(
            status_code=200,
            content={"status": "OK"}
        )
        
    except Exception as e:
        arf_logger.info(f"Error registering agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/arf/v1/agent-discoveries")
async def discover_agents(request: Request):
    """Discover agents based on required capabilities"""
    try:
        data = await request.json()
        body = data.get('body', {})
        
        requester_agent_id = body.get('agent_id')
        task_id = body.get('task_id')
        required_capabilities = body.get('required_capabilities', [])
        
        arf_logger.info(f"Discovery request from {requester_agent_id} for task {task_id}")
        
        # Return 200 OK immediately
        response_task = asyncio.create_task(process_discovery(
            requester_agent_id, task_id, required_capabilities
        ))
        
        return JSONResponse(
            status_code=200,
            content={"status": "OK"}
        )
        
    except Exception as e:
        arf_logger.info(f"Error in discovery: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def process_discovery(requester_agent_id: str, task_id: str, required_capabilities: List[str]):
    """Process discovery asynchronously"""
    global acf_ws
    
    db = get_db()
    
    # (1) Filter: online agents not in any task
    agents_in_tasks = db.query(Task.agent_id).distinct().all()
    agents_in_tasks = [a[0] for a in agents_in_tasks]
    
    candidates = db.query(Agent).filter(
        Agent.agent_status == 'online',
        Agent.agent_id.notin_(agents_in_tasks) if agents_in_tasks else True,
        Agent.agent_id != requester_agent_id
    ).all()
    
    if not candidates:
        arf_logger.info(f"No available agents found for discovery")
        db.close()
        return
    
    # (2) Capability similarity matching
    scored_agents = []
    for agent in candidates:
        if agent.agent_capability:
            matching_caps = set(agent.agent_capability) & set(required_capabilities)
            score = len(matching_caps)
            if score > 0:
                scored_agents.append((agent, score))
    
    if not scored_agents:
        arf_logger.info(f"No agents with matching capabilities found")
        db.close()
        return
    
    # (3) Sort by priority (higher priority first), then by score
    scored_agents.sort(key=lambda x: (-x[0].priority, -x[1]))
    
    # Select the best matching agent
    selected_agent = scored_agents[0][0]
    
    arf_logger.info(f"Selected agent {selected_agent.agent_id} for collaboration")
    
    # Send TASK_REQUEST_COLLABORATION via ACF
    if acf_ws:
        collab_msg = {
            "type": "TASK_REQUEST_COLLABORATION",
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "payload": {
                "src_agent_id": "ARF",
                "dst_agent_id": selected_agent.agent_id,
                "task_id": task_id,
                "task_description": "Collaboration task",
                "agent_card": {
                    "agent_id": selected_agent.agent_id,
                    "skill": selected_agent.agent_capability or []
                }
            }
        }
        await acf_ws.send(json.dumps(collab_msg))
        arf_logger.info(f"Sent TASK_REQUEST_COLLABORATION to {selected_agent.agent_id}")
    else:
        arf_logger.info(f"ACF connection not available")
    
    db.close()

async def handle_acf_messages():
    """Handle messages from ACF WebSocket"""
    global acf_ws
    
    try:
        async for message in acf_ws:
            try:
                data = json.loads(message)
                msg_type = data.get('type')
                
                if msg_type == 'TASK_ACCEPT_COLLABORATION':
                    await handle_task_accept(data)
                elif msg_type == 'SETUP':
                    arf_logger.info(f"Received SETUP response from ACF")
                else:
                    arf_logger.info(f"Unknown message from ACF: {msg_type}")
                    
            except json.JSONDecodeError:
                arf_logger.info(f"Invalid JSON from ACF")
            except Exception as e:
                arf_logger.info(f"Error processing ACF message: {e}")
                
    except websockets.exceptions.ConnectionClosed:
        arf_logger.info(f"ACF connection closed")
    except Exception as e:
        arf_logger.info(f"Error in ACF message handler: {e}")

async def handle_task_accept(data):
    """Handle TASK_ACCEPT_COLLABORATION from ACF"""
    global acf_ws
    
    payload = data.get('payload', {})
    src_agent_id = payload.get('src_agent_id')
    dst_agent_id = payload.get('dst_agent_id')
    task_id = payload.get('task_id')
    
    arf_logger.info(f"Received TASK_ACCEPT_COLLABORATION from {src_agent_id}")
    
    # Record in Task table
    db = get_db()
    task = Task(
        agent_id=src_agent_id,
        task_id=task_id,
        task_description="Collaboration task"
    )
    db.add(task)
    db.commit()
    db.close()
    
    # Send DISCOVER_RESULT to requester
    if acf_ws and dst_agent_id:
        discover_msg = {
            "type": "DISCOVER_RESULT",
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "payload": {
                "src_agent_id": "ARF",
                "dst_agent_id": dst_agent_id,
                "discover_result": [src_agent_id]
            }
        }
        await acf_ws.send(json.dumps(discover_msg))
        arf_logger.info(f"Sent DISCOVER_RESULT to {dst_agent_id}")

async def connect_to_acf():
    """Connect to ACF WebSocket server"""
    global acf_ws
    
    try:
        acf_ws = await websockets.connect('ws://localhost:9002')
        
        # Send SETUP message
        setup_msg = {
            "type": "SETUP",
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "payload": {
                "src_agent_id": "ARF"
            }
        }
        await acf_ws.send(json.dumps(setup_msg))
        
        # Wait for response
        response = await acf_ws.recv()
        arf_logger.info(f"Connected to ACF, response: {response}")
        
        # Start message handler
        asyncio.create_task(handle_acf_messages())
        
    except Exception as e:
        arf_logger.info(f"Failed to connect to ACF: {e}")

async def startup_event():
    """Startup event handler"""
    await connect_to_acf()

app.add_event_handler("startup", startup_event)

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=9001)
