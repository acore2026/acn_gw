#!/usr/bin/env python3
"""
Unit tests for the real MOQ relay implementation in moq/.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from moq import FullTrackName, Location
from moq.relay import MOQRelay, CachedObject


@pytest.fixture
def relay(tmp_path):
    """Create a relay instance with isolated cache storage."""
    cache_dir = tmp_path / "relay-cache"
    return MOQRelay(host="localhost", port=9998, cache_dir=str(cache_dir))


class TestMOQRelayLifecycle:
    """Test relay startup and shutdown."""

    @pytest.mark.asyncio
    async def test_start_and_stop(self, relay):
        relay.cache.clear_disk_cache = MagicMock()
        relay._quic_server.start = AsyncMock()
        relay._quic_server.stop = AsyncMock()

        await relay.start()

        assert relay._running is True
        relay.cache.clear_disk_cache.assert_called_once()
        relay._quic_server.start.assert_awaited_once()

        await relay.stop()

        assert relay._running is False
        relay._quic_server.stop.assert_awaited_once()


class TestMOQRelayCache:
    """Test relay caching helpers."""

    def test_cache_object_round_trip(self, relay):
        track_name = FullTrackName([b"agent", b"sensors"], b"track-1")
        cached = CachedObject(
            track_alias=1,
            group_id=7,
            object_id=3,
            publisher_priority=128,
            payload=b'{"temperature": 21.5}',
        )

        relay.cache_object(track_name, cached)

        stats = relay.get_cache_stats()
        assert stats["memory_objects"] == 1
        assert stats["memory_size"] == len(cached.payload)

        fetched = relay.cache.get(track_name, Location(7, 3))
        assert fetched is not None
        assert fetched.payload == cached.payload
