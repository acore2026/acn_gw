"""
Logging configuration for Agent GW
Provides file-based logging for all services
"""

import logging
import os
from datetime import datetime
from pathlib import Path

# Log directory
LOG_DIR = Path(__file__).parent / 'logs'
LOG_DIR.mkdir(exist_ok=True)

def setup_logger(name: str, log_file: str, level=logging.INFO) -> logging.Logger:
    """
    Setup a logger with file and console handlers.
    
    Args:
        name: Logger name
        log_file: Log file name (relative to agent_gw/logs/ directory)
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
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    simple_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # File handler - rotates daily
    log_path = LOG_DIR / log_file
    file_handler = logging.FileHandler(log_path, mode='a')
    file_handler.setLevel(level)
    file_handler.setFormatter(detailed_formatter)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(simple_formatter)
    
    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


def setup_arf_logger() -> logging.Logger:
    """Setup logger for ARF (Agent Repository Function)"""
    return setup_logger('arf', 'arf.log')


def setup_acf_logger() -> logging.Logger:
    """Setup logger for ACF (Agent Communication Function)"""
    return setup_logger('acf', 'acf.log')


def setup_moqt_logger() -> logging.Logger:
    """Setup logger for MOQT Relay"""
    return setup_logger('moqt', 'moqt.log')


def setup_main_logger() -> logging.Logger:
    """Setup logger for main application"""
    return setup_logger('main', 'agent_gw.log')


# Create loggers
arf_logger = setup_arf_logger()
acf_logger = setup_acf_logger()
moqt_logger = setup_moqt_logger()
main_logger = setup_main_logger()
