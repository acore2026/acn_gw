#!/usr/bin/env python3
"""
Agent GW - Main Application
Starts all three functional entities:
- ARF: HTTP server on port 9001
- ACF: WebSocket server on port 9002
- MOQT Relay: MOQT protocol on port 9003
"""

import asyncio
import sys
import os

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arf_server import app as arf_app, connect_to_acf
from acf_server import ACFServer
from moqt_relay import MOQTRelay
import uvicorn

async def run_arf():
    """Run ARF HTTP server"""
    config = uvicorn.Config(
        arf_app,
        host='0.0.0.0',
        port=9001,
        log_level='info'
    )
    server = uvicorn.Server(config)
    await server.serve()

async def run_acf():
    """Run ACF WebSocket server"""
    acf = ACFServer(host='0.0.0.0', port=9002)
    await acf.start()

async def run_moqt():
    """Run MOQT Relay server"""
    moqt = MOQTRelay(host='0.0.0.0', port=9003)
    await moqt.start()

async def main():
    """Main entry point - run all servers concurrently"""
    print("=" * 60)
    print("Agent GW - Starting all services")
    print("=" * 60)
    print()
    print("Services:")
    print("  - ARF (Agent Repository Function): HTTP on port 9001")
    print("  - ACF (Agent Communication Function): WebSocket on port 9002")
    print("  - MOQT Relay: MOQT protocol on port 9003")
    print()
    print("=" * 60)
    
    # Run all three servers concurrently
    await asyncio.gather(
        run_arf(),
        run_acf(),
        run_moqt(),
        return_exceptions=True
    )

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nAgent GW - Shutting down...")
        sys.exit(0)
