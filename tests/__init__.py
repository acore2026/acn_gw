#!/usr/bin/env python3
"""
Test suite for Agent GW backend
"""

import pytest
import asyncio
import json
from datetime import datetime

# Configure pytest-asyncio
pytest_plugins = ('pytest_asyncio',)

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
