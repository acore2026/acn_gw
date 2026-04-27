#!/usr/bin/env python3
"""
Agent GW - Main Application
Starts all three functional entities:
- ARF: HTTP server on port 9001
- ACF: Agent Communication Function WebSocket on port 9002
- MOQT Relay: MOQT protocol on port 9003 by default
"""

import asyncio
import os
import signal
import socket
import sys
from contextlib import suppress
from pathlib import Path

import uvicorn

if __package__ in (None, ''):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from agent_gw.arf_server import app as arf_app
    from agent_gw.acf_server import ACFServer
    from agent_gw.logger_config import main_logger, LOG_DIR
else:
    from .arf_server import app as arf_app
    from .acf_server import ACFServer
    from .logger_config import main_logger, LOG_DIR

from moq import MOQRelay

ARF_HOST = os.environ.get('ARF_HOST', '0.0.0.0')
ARF_PORT = int(os.environ.get('ARF_PORT', '9001'))
ACF_HOST = os.environ.get('ACF_HOST', '0.0.0.0')
ACF_PORT = int(os.environ.get('ACF_PORT', '9002'))
RELAY_HOST = os.environ.get('MOQ_RELAY_HOST', '0.0.0.0')
RELAY_PORT = int(os.environ.get('MOQ_RELAY_PORT', '9003'))
RELAY_CACHE_DIR = os.environ.get(
    'MOQ_RELAY_CACHE_DIR',
    str(Path(__file__).resolve().parent / '.relay_cache'),
)
RELAY_MAX_MEMORY_CACHE = 100 * 1024 * 1024
RELAY_MAX_DISK_CACHE = 1024 * 1024 * 1024


class StartupError(Exception):
    """Raised when Agent GW cannot start cleanly."""


async def _watch_stop_event(stop_event: asyncio.Event, server):
    """Translate a shutdown event into a Uvicorn stop request."""
    await stop_event.wait()
    server.should_exit = True


def _check_port_available(name: str, host: str, port: int, sock_type: int) -> None:
    """Fail fast if a service port is already occupied."""
    with socket.socket(socket.AF_INET, sock_type) as sock:
        if sock_type == socket.SOCK_STREAM:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            if sock_type == socket.SOCK_STREAM:
                sock.listen(1)
        except OSError as exc:
            raise StartupError(f"{name} cannot bind {host}:{port}: {exc}") from exc


def _check_startup_ports() -> None:
    _check_port_available('ARF HTTP server', ARF_HOST, ARF_PORT, socket.SOCK_STREAM)
    _check_port_available('ACF WebSocket server', ACF_HOST, ACF_PORT, socket.SOCK_STREAM)
    _check_port_available('MOQT Relay server', RELAY_HOST, RELAY_PORT, socket.SOCK_DGRAM)


async def run_arf(stop_event: asyncio.Event):
    """Run ARF HTTP server"""
    main_logger.info(f"Starting ARF HTTP server on {ARF_HOST}:{ARF_PORT}")
    config = uvicorn.Config(
        arf_app,
        host=ARF_HOST,
        port=ARF_PORT,
        log_level='info'
    )
    server = uvicorn.Server(config)
    watcher = asyncio.create_task(_watch_stop_event(stop_event, server))
    try:
        try:
            await server.serve()
        except SystemExit as exc:
            stop_event.set()
            raise StartupError(f"ARF HTTP server failed to start: {exc}") from exc
    finally:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher
        server.should_exit = True

async def run_acf(stop_event: asyncio.Event):
    """Run ACF WebSocket server"""
    main_logger.info(f"Starting ACF WebSocket server on {ACF_HOST}:{ACF_PORT}")
    acf = ACFServer(host=ACF_HOST, port=ACF_PORT)
    try:
        await acf.start(stop_event=stop_event)
    except SystemExit as exc:
        stop_event.set()
        raise StartupError(f"ACF WebSocket server failed to start: {exc}") from exc

async def run_moqt(stop_event: asyncio.Event):
    """Run MOQT Relay server"""
    main_logger.info(
        f"Starting MOQT Relay server on {RELAY_HOST}:{RELAY_PORT} "
        f"with cache_dir={RELAY_CACHE_DIR}"
    )
    moqt = MOQRelay(
        host=RELAY_HOST,
        port=RELAY_PORT,
        cache_dir=RELAY_CACHE_DIR,
        max_memory_cache=RELAY_MAX_MEMORY_CACHE,
        max_disk_cache=RELAY_MAX_DISK_CACHE,
    )
    try:
        await moqt.start()
        main_logger.info(f"MOQT Relay server started: {RELAY_HOST}:{RELAY_PORT}")
        await stop_event.wait()
    finally:
        await moqt.stop()
        main_logger.info("MOQT Relay server stopped")

async def main():
    """Main entry point - run all servers concurrently"""
    main_logger.info("=" * 60)
    main_logger.info("Agent GW - Starting all services")
    main_logger.info("=" * 60)
    main_logger.info("")
    main_logger.info("Services:")
    main_logger.info(
        f"  - ARF (Agent Repository Function): HTTP on {ARF_HOST}:{ARF_PORT}"
    )
    main_logger.info(
        f"  - ACF (Agent Communication Function): WebSocket on {ACF_HOST}:{ACF_PORT}"
    )
    main_logger.info(f"  - MOQT Relay: MOQT protocol on {RELAY_HOST}:{RELAY_PORT}")
    main_logger.info("")
    main_logger.info(f"Log directory: {LOG_DIR}")
    main_logger.info("=" * 60)

    _check_startup_ports()
    
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
    stop_waiter = asyncio.create_task(stop_event.wait())

    try:
        done, _ = await asyncio.wait(
            [stop_waiter, *tasks],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            if task is stop_waiter:
                continue
            exc = task.exception()
            if exc is None:
                raise StartupError("Agent GW service stopped unexpectedly")
            if isinstance(exc, StartupError):
                raise exc
            raise StartupError(f"Agent GW service task failed: {exc}") from exc
    finally:
        stop_event.set()
        stop_waiter.cancel()
        with suppress(asyncio.CancelledError):
            await stop_waiter
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
    except StartupError as exc:
        main_logger.info(f"Agent GW startup failed: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        main_logger.info("Agent GW - Shutting down...")
        sys.exit(0)


if __name__ == '__main__':
    run()
