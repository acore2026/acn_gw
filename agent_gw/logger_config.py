"""
Logging configuration for Agent GW
Provides file-based logging for all services
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Log directory
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


def setup_logger(name: str, log_file: str, level=logging.INFO) -> logging.Logger:
    """
    Setup a logger with file and console handlers.

    When running in a terminal (direct python3 agent_gw.py), logs go to both
    console and file. When running via start_agent_gw.sh (background), logs
    go to file only to avoid duplication.

    Args:
        name: Logger name
        log_file: Log file name (relative to repository logs/ directory)
        level: Logging level

    Returns:
        Configured logger
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    logger.handlers = []

    # Create formatters
    detailed_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    simple_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler - always enabled
    log_path = LOG_DIR / log_file
    file_handler = logging.FileHandler(log_path, mode="a")
    file_handler.setLevel(level)
    file_handler.setFormatter(detailed_formatter)
    logger.addHandler(file_handler)

    # Console handler - enabled when:
    # 1. Running in a terminal (isatty)
    # 2. AGENT_GW_NO_CONSOLE env var is not set
    no_console = os.environ.get("AGENT_GW_NO_CONSOLE", "")
    is_tty = sys.stdout.isatty()

    if is_tty and not no_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(simple_formatter)
        logger.addHandler(console_handler)

    return logger


def setup_arf_logger() -> logging.Logger:
    """Setup logger for ARF (Agent Repository Function)"""
    return setup_logger("arf", "arf.log")


def setup_acf_logger() -> logging.Logger:
    """Setup logger for ACF (Agent Communication Function)"""
    return setup_logger("acf", "acf.log")


def setup_moqt_logger() -> logging.Logger:
    """Setup logger for MOQT Relay"""
    return setup_logger("moqt", "moqt.log")


def setup_moq_logger() -> logging.Logger:
    """Setup logger for MOQ library (moq.relay, moq.transport, etc.)"""
    return setup_logger("moq", "moqt.log", level=logging.DEBUG)


def setup_main_logger() -> logging.Logger:
    """Setup logger for main application"""
    return setup_logger("main", "agent_gw.log")


# Create loggers
arf_logger = setup_arf_logger()
acf_logger = setup_acf_logger()
moqt_logger = setup_moqt_logger()
moq_logger = setup_moq_logger()  # MOQ library logger
main_logger = setup_main_logger()
