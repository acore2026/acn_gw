#!/usr/bin/env python3
"""
Agent GW - Main Application
Starts all three functional entities:
- ARF: HTTP server on port 9001
- ACF: Agent Communication Function WebSocket on port 9002
- MOQT Relay: MOQT protocol on port 9003
"""

import asyncio
import signal
import sys
from contextlib import suppress
from pathlib import Path

import uvicorn

if __package__ in (None, ''):
    import os

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from agent_gw.arf_server import app as arf_app
    from agent_gw.acf_server import ACFServer
    from agent_gw.logger_config import main_logger, LOG_DIR
else:
    from .arf_server import app as arf_app
    from .acf_server import ACFServer
    from .logger_config import main_logger, LOG_DIR

from moq import MOQRelay


async def _watch_stop_event(stop_event: asyncio.Event, server):
    """Translate a shutdown event into a Uvicorn stop request."""
    await stop_event.wait()
    server.should_exit = True


async def run_arf(stop_event: asyncio.Event):
    """Run ARF HTTP server"""
    main_logger.info("Starting ARF HTTP server on port 9001")
    config = uvicorn.Config(
        arf_app,
        host='0.0.0.0',
        port=9001,
        log_level='info'
    )
    server = uvicorn.Server(config)
    watcher = asyncio.create_task(_watch_stop_event(stop_event, server))
    try:
        await server.serve()
    finally:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher
        server.should_exit = True

async def run_acf(stop_event: asyncio.Event):
    """Run ACF WebSocket server"""
    main_logger.info("Starting ACF WebSocket server on port 9002")
    acf = ACFServer(host='0.0.0.0', port=9002)
    await acf.start(stop_event=stop_event)

async def run_moqt(stop_event: asyncio.Event):
    """Run MOQT Relay server"""
    main_logger.info("Starting MOQT Relay server on port 9003")
    moqt = MOQRelay(
        host='0.0.0.0',
        port=9003,
        cache_dir=str(Path(__file__).resolve().parent / '.relay_cache'),
    )
    try:
        await moqt.start()
        main_logger.info("MOQT Relay server started")
        await stop_event.wait()
    finally:
        await moqt.stop()

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
    
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _request_shutdown():
        main_logger.info("Shutdown requested")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except NotImplementedError:
            pass

    tasks = [
        asyncio.create_task(run_arf(stop_event)),
        asyncio.create_task(run_acf(stop_event)),
        asyncio.create_task(run_moqt(stop_event)),
    ]

    try:
        await stop_event.wait()
    finally:
        stop_event.set()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError, Exception):
                await task
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.remove_signal_handler(sig)
            except Exception:
                pass


def run():
    """Run the Agent GW services from a synchronous entry point."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        main_logger.info("Agent GW - Shutting down...")
        sys.exit(0)


if __name__ == '__main__':
    run()
