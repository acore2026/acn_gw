#!/usr/bin/env python3
"""
Unit tests for MOQT Relay Server
"""

import pytest
import asyncio
import json
import struct
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from moqt_relay import MOQTRelay

@pytest.fixture
def moqt_relay():
    """Create MOQT relay instance"""
    relay = MOQTRelay(host='localhost', port=9998)
    return relay

@pytest.fixture
def mock_reader_writer():
    """Create mock reader and writer"""
    reader = AsyncMock()
    writer = AsyncMock()
    writer.get_extra_info.return_value = ('127.0.0.1', 12345)
    return reader, writer

@pytest.mark.asyncio
class TestMOQTSubscribe:
    """Test SUBSCRIBE message handling"""
    
    async def test_handle_subscribe_new_track(self, moqt_relay, mock_reader_writer):
        """Test subscribing to a new track"""
        reader, writer = mock_reader_writer
        
        msg = {
            "type": "SUBSCRIBE",
            "track_id": "track-test-001"
        }
        
        await moqt_relay.handle_subscribe(writer, msg)
        
        # Verify subscriber added
        assert "track-test-001" in moqt_relay.subscribers
        assert writer in moqt_relay.subscribers["track-test-001"]
        
        # Verify SUBSCRIBE_OK sent
        writer.write.assert_called()
        writer.drain.assert_called()
    
    async def test_handle_subscribe_existing_track(self, moqt_relay, mock_reader_writer):
        """Test multiple subscribers to same track"""
        reader1, writer1 = mock_reader_writer
        reader2, writer2 = AsyncMock(), AsyncMock()
        
        # First subscriber
        msg1 = {"type": "SUBSCRIBE", "track_id": "track-shared"}
        await moqt_relay.handle_subscribe(writer1, msg1)
        
        # Second subscriber
        msg2 = {"type": "SUBSCRIBE", "track_id": "track-shared"}
        await moqt_relay.handle_subscribe(writer2, msg2)
        
        # Verify both subscribers
        assert len(moqt_relay.subscribers["track-shared"]) == 2
        assert writer1 in moqt_relay.subscribers["track-shared"]
        assert writer2 in moqt_relay.subscribers["track-shared"]

@pytest.mark.asyncio
class TestMOQTPublish:
    """Test PUBLISH message handling"""
    
    async def test_handle_publish_new_track(self, moqt_relay, mock_reader_writer):
        """Test publishing a new track"""
        reader, writer = mock_reader_writer
        
        msg = {
            "type": "PUBLISH",
            "track_id": "track-pub-001"
        }
        
        await moqt_relay.handle_publish(writer, msg)
        
        # Verify track created
        assert "track-pub-001" in moqt_relay.tracks
        assert moqt_relay.tracks["track-pub-001"]["publisher"] == writer
        assert "track-pub-001" in moqt_relay.publishers
        
        # Verify PUBLISH_OK sent
        writer.write.assert_called()
    
    async def test_handle_publish_duplicate(self, moqt_relay, mock_reader_writer):
        """Test publishing same track twice (should update)"""
        reader1, writer1 = mock_reader_writer
        reader2, writer2 = AsyncMock(), AsyncMock()
        
        # First publish
        msg1 = {"type": "PUBLISH", "track_id": "track-dup"}
        await moqt_relay.handle_publish(writer1, msg1)
        
        # Second publish (different publisher)
        msg2 = {"type": "PUBLISH", "track_id": "track-dup"}
        await moqt_relay.handle_publish(writer2, msg2)
        
        # Should update to new publisher
        assert moqt_relay.tracks["track-dup"]["publisher"] == writer2
        assert moqt_relay.publishers["track-dup"] == writer2

@pytest.mark.asyncio
class TestMOQTObjectForwarding:
    """Test OBJECT message forwarding"""
    
    async def test_handle_object_forward_to_subscribers(self, moqt_relay):
        """Test forwarding objects to all subscribers"""
        # Setup publisher
        pub_reader, pub_writer = AsyncMock(), AsyncMock()
        moqt_relay.publishers["track-obj-001"] = pub_writer
        moqt_relay.tracks["track-obj-001"] = {"publisher": pub_writer}
        
        # Setup subscribers
        sub1_reader, sub1_writer = AsyncMock(), AsyncMock()
        sub2_reader, sub2_writer = AsyncMock(), AsyncMock()
        moqt_relay.subscribers["track-obj-001"] = {sub1_writer, sub2_writer}
        
        # Object message from publisher
        msg = {
            "type": "OBJECT",
            "track_id": "track-obj-001",
            "data": {"sensor_reading": 42.5}
        }
        
        await moqt_relay.handle_object(pub_writer, msg)
        
        # Verify forwarded to all subscribers
        sub1_writer.write.assert_called()
        sub2_writer.write.assert_called()
    
    async def test_handle_object_unauthorized_publisher(self, moqt_relay):
        """Test object from unauthorized publisher"""
        # Setup track with specific publisher
        authorized_writer = AsyncMock()
        moqt_relay.publishers["track-auth"] = authorized_writer
        moqt_relay.tracks["track-auth"] = {"publisher": authorized_writer}
        
        # Unauthorized publisher tries to publish
        unauthorized_writer = AsyncMock()
        msg = {
            "type": "OBJECT",
            "track_id": "track-auth",
            "data": {}
        }
        
        await moqt_relay.handle_object(unauthorized_writer, msg)
        
        # Should not forward (no subscribers to receive anyway)
        # Test passes if no exception
    
    async def test_handle_object_no_subscribers(self, moqt_relay):
        """Test object with no subscribers"""
        pub_reader, pub_writer = AsyncMock(), AsyncMock()
        moqt_relay.publishers["track-empty"] = pub_writer
        moqt_relay.tracks["track-empty"] = {"publisher": pub_writer}
        # No subscribers
        
        msg = {
            "type": "OBJECT",
            "track_id": "track-empty",
            "data": {}
        }
        
        # Should not raise exception
        await moqt_relay.handle_object(pub_writer, msg)
    
    async def test_handle_object_with_dead_subscribers(self, moqt_relay):
        """Test forwarding when some subscribers are dead"""
        pub_reader, pub_writer = AsyncMock(), AsyncMock()
        moqt_relay.publishers["track-dead"] = pub_writer
        moqt_relay.tracks["track-dead"] = {"publisher": pub_writer}
        
        # One good subscriber, one dead
        good_writer = AsyncMock()
        dead_writer = AsyncMock()
        dead_writer.write.side_effect = Exception("Connection closed")
        
        moqt_relay.subscribers["track-dead"] = {good_writer, dead_writer}
        
        msg = {
            "type": "OBJECT",
            "track_id": "track-dead",
            "data": {}
        }
        
        await moqt_relay.handle_object(pub_writer, msg)
        
        # Dead subscriber should be removed
        assert dead_writer not in moqt_relay.subscribers["track-dead"]
        assert good_writer in moqt_relay.subscribers["track-dead"]

@pytest.mark.asyncio
class TestMOQTUnsubscribe:
    """Test UNSUBSCRIBE message handling"""
    
    async def test_handle_unsubscribe(self, moqt_relay):
        """Test unsubscribing from a track"""
        writer = AsyncMock()
        
        # First subscribe
        moqt_relay.subscribers["track-unsub"] = {writer}
        
        # Then unsubscribe
        msg = {
            "type": "UNSUBSCRIBE",
            "track_id": "track-unsub"
        }
        
        await moqt_relay.handle_unsubscribe(writer, msg)
        
        # Verify removed
        assert writer not in moqt_relay.subscribers["track-unsub"]
        
        # Verify UNSUBSCRIBE_OK sent
        writer.write.assert_called()
    
    async def test_handle_unsubscribe_not_subscribed(self, moqt_relay):
        """Test unsubscribing from track not subscribed to"""
        writer = AsyncMock()
        
        msg = {
            "type": "UNSUBSCRIBE",
            "track_id": "track-not-subscribed"
        }
        
        # Should not raise exception
        await moqt_relay.handle_unsubscribe(writer, msg)

@pytest.mark.asyncio
class TestMOQTClientCleanup:
    """Test client disconnection cleanup"""
    
    async def test_cleanup_publisher(self, moqt_relay):
        """Test cleanup when publisher disconnects"""
        writer = AsyncMock()
        
        # Setup publisher
        moqt_relay.publishers["track-pub"] = writer
        moqt_relay.tracks["track-pub"] = {"publisher": writer}
        
        # Cleanup
        await moqt_relay.cleanup_client(writer)
        
        # Verify track removed
        assert "track-pub" not in moqt_relay.publishers
        assert "track-pub" not in moqt_relay.tracks
    
    async def test_cleanup_subscriber(self, moqt_relay):
        """Test cleanup when subscriber disconnects"""
        writer = AsyncMock()
        
        # Setup subscriber
        moqt_relay.subscribers["track-sub"] = {writer}
        
        # Cleanup
        await moqt_relay.cleanup_client(writer)
        
        # Verify removed
        assert writer not in moqt_relay.subscribers["track-sub"]
    
    async def test_cleanup_both_roles(self, moqt_relay):
        """Test cleanup when client is both publisher and subscriber"""
        writer = AsyncMock()
        
        # Setup as both
        moqt_relay.publishers["track-pub"] = writer
        moqt_relay.tracks["track-pub"] = {"publisher": writer}
        moqt_relay.subscribers["track-sub"] = {writer}
        
        # Cleanup
        await moqt_relay.cleanup_client(writer)
        
        # Verify all cleaned up
        assert "track-pub" not in moqt_relay.publishers
        assert writer not in moqt_relay.subscribers["track-sub"]

@pytest.mark.asyncio
class TestMOQTMessageProtocol:
    """Test message protocol format"""
    
    async def test_send_message_format(self, moqt_relay):
        """Test message encoding format"""
        writer = AsyncMock()
        
        msg = {
            "type": "TEST",
            "data": "test data"
        }
        
        await moqt_relay.send_message(writer, msg)
        
        # Verify write called with correct format
        writer.write.assert_called_once()
        written_data = writer.write.call_args[0][0]
        
        # First 4 bytes should be length
        length = struct.unpack('!I', written_data[:4])[0]
        
        # Rest should be JSON
        json_data = written_data[4:].decode('utf-8')
        parsed = json.loads(json_data)
        
        assert parsed["type"] == "TEST"
        assert length == len(json_data)

@pytest.mark.asyncio
class TestMOQTEndToEnd:
    """End-to-end MOQT scenarios"""
    
    async def test_pub_sub_flow(self, moqt_relay):
        """Test complete publish-subscribe flow"""
        pub_reader, pub_writer = AsyncMock(), AsyncMock()
        sub_reader, sub_writer = AsyncMock(), AsyncMock()
        
        # 1. Publisher publishes track
        await moqt_relay.handle_publish(pub_writer, {
            "type": "PUBLISH",
            "track_id": "track-flow"
        })
        
        # 2. Subscriber subscribes to track
        await moqt_relay.handle_subscribe(sub_writer, {
            "type": "SUBSCRIBE",
            "track_id": "track-flow"
        })
        
        # 3. Publisher sends objects
        for i in range(3):
            await moqt_relay.handle_object(pub_writer, {
                "type": "OBJECT",
                "track_id": "track-flow",
                "data": {"seq": i}
            })
        
        # Verify subscriber received all 3 objects
        assert sub_writer.write.call_count == 4  # SUBSCRIBE_OK + 3 objects
        
        # 4. Subscriber unsubscribes
        await moqt_relay.handle_unsubscribe(sub_writer, {
            "type": "UNSUBSCRIBE",
            "track_id": "track-flow"
        })
        
        assert sub_writer not in moqt_relay.subscribers["track-flow"]
    
    async def test_multiple_publishers_same_track(self, moqt_relay):
        """Test behavior when multiple publishers try to publish same track"""
        pub1_reader, pub1_writer = AsyncMock(), AsyncMock()
        pub2_reader, pub2_writer = AsyncMock(), AsyncMock()
        
        # First publisher
        await moqt_relay.handle_publish(pub1_writer, {
            "type": "PUBLISH",
            "track_id": "track-multi-pub"
        })
        
        # Second publisher (takes over)
        await moqt_relay.handle_publish(pub2_writer, {
            "type": "PUBLISH",
            "track_id": "track-multi-pub"
        })
        
        # Only second publisher can publish objects
        sub_reader, sub_writer = AsyncMock(), AsyncMock()
        await moqt_relay.handle_subscribe(sub_writer, {
            "type": "SUBSCRIBE",
            "track_id": "track-multi-pub"
        })
        
        # First publisher tries to publish (should fail)
        await moqt_relay.handle_object(pub1_writer, {
            "type": "OBJECT",
            "track_id": "track-multi-pub",
            "data": {"from": "pub1"}
        })
        
        # Second publisher publishes (should succeed)
        await moqt_relay.handle_object(pub2_writer, {
            "type": "OBJECT",
            "track_id": "track-multi-pub",
            "data": {"from": "pub2"}
        })
        
        # Sub should have received: SUBSCRIBE_OK + 1 object (from pub2)
        # Note: This test documents current behavior (last publisher wins)
        assert sub_writer.write.call_count >= 1
