#!/usr/bin/env python3
"""
Agent GW - Main Application
Starts all three functional entities:
- ARF: HTTP server on port 9001
- ACF: Agent Communication Function WebSocket on port 9002
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
from logger_config import main_logger, LOG_DIR
import uvicorn

async def run_arf():
    """Run ARF HTTP server"""
    main_logger.info("Starting ARF HTTP server on port 9001")
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
    main_logger.info("Starting ACF WebSocket server on port 9002")
    acf = ACFServer(host='0.0.0.0', port=9002)
    await acf.start()

async def run_moqt():
    """Run MOQT Relay server"""
    main_logger.info("Starting MOQT Relay server on port 9003")
    moqt = MOQTRelay(host='0.0.0.0', port=9003)
    await moqt.start()

async def main():
    """Main entry point - run all servers concurrently"""
    main_logger.info("=" * 60)
    main_logger.info("Agent GW - Starting all services")
    main_logger.info("=" * 60)
    main_logger.info("")
    main_logger.info("Services:")
    main_logger.info("  - ARF (Agent Repository Function): HTTP on port 9001")
    main_logger.info("  - ACF (Agent Communication Function): WebSocket on port 9002")
    main_logger.info("  - MOQT Relay: MOQT protocol on port 9003")
    main_logger.info("")
    main_logger.info(f"Log directory: {LOG_DIR}")
    main_logger.info("=" * 60)
    
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
        main_logger.info("Agent GW - Shutting down...")
        sys.exit(0)
