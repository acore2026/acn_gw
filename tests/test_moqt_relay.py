#!/usr/bin/env python3
"""
Unit tests for the real MOQ relay implementation in moq/.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from moq import FullTrackName, Location
from moq.encoding import Parameters, VarInt
from moq.messages import (
    SetupMessage,
    SubgroupHeader,
    SubgroupObject,
    ObjectStatus,
    StreamType,
    PublishMessage,
    SubscribeMessage,
    PublishOkMessage,
    SubscribeOkMessage,
)
from moq.relay import MOQRelay, CachedObject, ClientSession
from moq.session import Role, SETUP_AGENT_ID_PARAM


@pytest.fixture
def relay(tmp_path):
    """Create a relay instance with isolated cache storage."""
    cache_dir = tmp_path / "relay-cache"
    return MOQRelay(host="localhost", port=9998, cache_dir=str(cache_dir))


@pytest.fixture
def mock_quic_connection():
    """Create a mock QUIC connection."""
    conn = MagicMock()
    conn.send_stream_data = MagicMock()
    conn.send_datagram_frame = MagicMock()
    conn.get_next_available_stream_id = MagicMock(return_value=100)
    return conn


@pytest.fixture
def mock_protocol():
    """Create a mock QUIC protocol."""
    protocol = MagicMock()
    protocol._quic = MagicMock()
    protocol._quic.host_cid = "test-cid"
    protocol.transmit = MagicMock()
    return protocol


@pytest.fixture
def publisher_client(mock_protocol, mock_quic_connection):
    """Create a mock publisher client."""
    client = ClientSession(
        session_id="publisher-1",
        protocol=mock_protocol,
        quic_connection=mock_quic_connection,
    )
    return client


@pytest.fixture
def subscriber_client(mock_protocol, mock_quic_connection):
    """Create a mock subscriber client."""
    client = ClientSession(
        session_id="subscriber-1",
        protocol=mock_protocol,
        quic_connection=mock_quic_connection,
    )
    return client


def generate_video_frame(group_id: int, frame_size: int = 4096) -> bytes:
    """Generate fake video frame data for testing."""
    return bytes([group_id % 256] * frame_size)


def create_streaming_message(
    track_alias: int, group_id: int, object_id: int, payload: bytes
) -> bytes:
    """Create a streaming format message (SubgroupHeader + SubgroupObject)."""
    header_data = VarInt.encode(StreamType.SUBGROUP_HEADER)
    subgroup_header = SubgroupHeader(
        track_alias=track_alias,
        group_id=group_id,
        subgroup_id=0,
        publisher_priority=128,
    )
    header_data += subgroup_header.encode()
    subgroup_obj = SubgroupObject(
        object_id=object_id,
        payload=payload,
    )
    header_data += subgroup_obj.encode()
    return header_data


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


class TestMOQRelaySetupLogging:
    """Test MOQ SETUP handling and connection logging."""

    @pytest.mark.asyncio
    async def test_setup_with_agent_id_posts_element_log(self, relay):
        params = Parameters()
        params.set(SETUP_AGENT_ID_PARAM, b"did:acn:agent:987654321")
        msg = SetupMessage(
            version=0xFF000011, role=Role.PUBLISHER.value, parameters=params
        )
        client = ClientSession(
            session_id="client-1",
            protocol=MagicMock(),
            quic_connection=MagicMock(),
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("moq.relay.relay.httpx.AsyncClient") as mock_async_client:
            mock_async_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_async_client.return_value.__aexit__ = AsyncMock(return_value=None)

            await relay._handle_setup(client, msg)

        assert client.agent_id == "did:acn:agent:987654321"
        assert client.setup_logged is True
        assert mock_client.post.await_count == 1
        _, kwargs = mock_client.post.call_args
        assert kwargs["json"]["url"] == "/acn/v3/element-logs"
        assert kwargs["json"]["body"]["element_id"] == "AgentGW"
        assert kwargs["json"]["body"]["log_type"] == "SetupConnection"
        assert (
            kwargs["json"]["body"]["content"]["agent_id"] == "did:acn:agent:987654321"
        )


class TestMOQRelayStreaming:
    """Test relay streaming mode (SubgroupHeader + SubgroupObject)."""

    @pytest.mark.asyncio
    async def test_handle_subgroup_stream_single_frame(
        self, relay, publisher_client, subscriber_client
    ):
        """Test handling a single video frame in streaming mode."""
        track_name = FullTrackName([b"agent", b"video"], b"camera-stream")
        track_alias = 1
        group_id = 0
        object_id = 0
        frame_data = generate_video_frame(group_id, frame_size=4096)

        publisher_client.publications[track_name] = {
            "track_alias": track_alias,
            "request_id": 1,
        }
        relay._publications[track_name] = publisher_client
        relay._subscriptions[track_name] = [subscriber_client]
        relay._clients[publisher_client.session_id] = publisher_client
        relay._clients[subscriber_client.session_id] = subscriber_client

        streaming_data = create_streaming_message(
            track_alias, group_id, object_id, frame_data
        )

        await relay._handle_subgroup_stream(publisher_client, streaming_data, 1)

        subscriber_client.quic_connection.send_stream_data.assert_called_once()
        call_args = subscriber_client.quic_connection.send_stream_data.call_args
        sent_stream_id = call_args[0][0]
        sent_data = call_args[0][1]

        assert sent_data == streaming_data

    @pytest.mark.asyncio
    async def test_handle_subgroup_stream_multiple_frames(
        self, relay, publisher_client, subscriber_client
    ):
        """Test handling multiple video frames in streaming mode."""
        track_name = FullTrackName([b"agent", b"video"], b"camera-stream")
        track_alias = 1

        publisher_client.publications[track_name] = {
            "track_alias": track_alias,
            "request_id": 1,
        }
        relay._publications[track_name] = publisher_client
        relay._subscriptions[track_name] = [subscriber_client]
        relay._clients[publisher_client.session_id] = publisher_client
        relay._clients[subscriber_client.session_id] = subscriber_client

        for group_id in range(5):
            frame_data = generate_video_frame(group_id, frame_size=2048)
            streaming_data = create_streaming_message(
                track_alias, group_id, 0, frame_data
            )
            await relay._handle_subgroup_stream(publisher_client, streaming_data, 1)

        assert subscriber_client.quic_connection.send_stream_data.call_count == 5

    @pytest.mark.asyncio
    async def test_handle_subgroup_stream_multiple_subscribers(
        self, relay, publisher_client
    ):
        """Test forwarding streaming data to multiple subscribers."""
        track_name = FullTrackName([b"agent", b"video"], b"camera-stream")
        track_alias = 1

        subscriber_1 = ClientSession(
            session_id="subscriber-1",
            protocol=MagicMock(),
            quic_connection=MagicMock(),
        )
        subscriber_1.quic_connection.get_next_available_stream_id = MagicMock(
            return_value=100
        )
        subscriber_1.quic_connection.send_stream_data = MagicMock()

        subscriber_2 = ClientSession(
            session_id="subscriber-2",
            protocol=MagicMock(),
            quic_connection=MagicMock(),
        )
        subscriber_2.quic_connection.get_next_available_stream_id = MagicMock(
            return_value=200
        )
        subscriber_2.quic_connection.send_stream_data = MagicMock()

        publisher_client.publications[track_name] = {
            "track_alias": track_alias,
            "request_id": 1,
        }
        relay._publications[track_name] = publisher_client
        relay._subscriptions[track_name] = [subscriber_1, subscriber_2]
        relay._clients[publisher_client.session_id] = publisher_client

        frame_data = generate_video_frame(0, frame_size=4096)
        streaming_data = create_streaming_message(track_alias, 0, 0, frame_data)

        await relay._handle_subgroup_stream(publisher_client, streaming_data, 1)

        subscriber_1.quic_connection.send_stream_data.assert_called_once()
        subscriber_2.quic_connection.send_stream_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_data_stream_continuous_video(
        self, relay, publisher_client, subscriber_client
    ):
        """Test handling continuous video stream data on QUIC stream."""
        track_name = FullTrackName([b"agent", b"video"], b"camera-stream")
        track_alias = 1
        stream_id = 50

        publisher_client.publications[track_name] = {
            "track_alias": track_alias,
            "request_id": 1,
        }
        relay._publications[track_name] = publisher_client
        relay._subscriptions[track_name] = [subscriber_client]
        relay._clients[publisher_client.session_id] = publisher_client
        relay._clients[subscriber_client.session_id] = subscriber_client

        stream_data = MagicMock()
        stream_data.stream_id = stream_id
        stream_data.end_stream = False

        for group_id in range(3):
            frame_data = generate_video_frame(group_id, frame_size=2048)
            streaming_msg = create_streaming_message(
                track_alias, group_id, 0, frame_data
            )
            stream_data.data = streaming_msg
            await relay._handle_data_stream(publisher_client, stream_data)

        assert subscriber_client.quic_connection.send_stream_data.call_count >= 3

        tracked_alias = relay._stream_buffers[stream_id]["track_alias"]
        assert tracked_alias == track_alias

    @pytest.mark.asyncio
    async def test_handle_data_stream_end_of_stream(
        self, relay, publisher_client, subscriber_client
    ):
        """Test handling end of stream marker."""
        track_name = FullTrackName([b"agent", b"video"], b"camera-stream")
        track_alias = 1
        stream_id = 50

        publisher_client.publications[track_name] = {
            "track_alias": track_alias,
            "request_id": 1,
        }
        relay._publications[track_name] = publisher_client
        relay._subscriptions[track_name] = [subscriber_client]
        relay._clients[publisher_client.session_id] = publisher_client

        frame_data = generate_video_frame(0, frame_size=2048)
        streaming_msg = create_streaming_message(track_alias, 0, 0, frame_data)

        stream_data = MagicMock()
        stream_data.stream_id = stream_id
        stream_data.data = streaming_msg
        stream_data.end_stream = True

        await relay._handle_data_stream(publisher_client, stream_data)

        assert stream_id not in relay._stream_buffers

    @pytest.mark.asyncio
    async def test_send_stream_data_continuously_maintains_stream_mapping(
        self, relay, subscriber_client
    ):
        """Test that stream mapping is maintained across multiple sends."""
        subscriber_client._relay_streams = {}

        source_stream_id = 10

        for i in range(3):
            data = bytes([i] * 100)
            end_stream = i == 2
            await relay._send_stream_data_continuously(
                subscriber_client,
                source_stream_id,
                data,
                end_stream=end_stream,
            )

        assert source_stream_id in subscriber_client._relay_streams
        dest_stream_id = subscriber_client._relay_streams[source_stream_id]
        assert dest_stream_id == 100
        assert subscriber_client.quic_connection.send_stream_data.call_count == 3

    @pytest.mark.asyncio
    async def test_unknown_track_alias_in_streaming(self, relay, publisher_client):
        """Test handling streaming data with unknown track alias."""
        track_alias = 999
        frame_data = generate_video_frame(0, frame_size=4096)
        streaming_data = create_streaming_message(track_alias, 0, 0, frame_data)

        await relay._handle_subgroup_stream(publisher_client, streaming_data, 1)

        assert not publisher_client.quic_connection.send_stream_data.called


class TestMOQRelayVideoStreamingIntegration:
    """Integration-like tests simulating real video streaming scenarios."""

    @pytest.mark.asyncio
    async def test_full_video_stream_flow(
        self, relay, publisher_client, subscriber_client
    ):
        """Test complete video streaming flow: publish -> stream -> forward."""
        track_name = FullTrackName([b"agent", b"video"], b"camera-001")
        track_alias = 1

        publish_msg = PublishMessage(
            request_id=1,
            track_alias=track_alias,
            full_track_name=track_name,
        )
        await relay._handle_publish(publisher_client, publish_msg)

        assert track_name in relay._publications
        assert track_name in publisher_client.publications

        subscriber_client.quic_connection.send_stream_data.reset_mock()

        subscribe_msg = SubscribeMessage(
            request_id=2,
            track_alias=track_alias,
            full_track_name=track_name,
            subscriber_priority=128,
            group_order=0,
            filter_type=2,
        )
        await relay._handle_subscribe(subscriber_client, subscribe_msg)

        assert track_name in relay._subscriptions
        assert subscriber_client in relay._subscriptions[track_name]

        subscriber_client.quic_connection.send_stream_data.reset_mock()

        for group_id in range(10):
            frame_data = generate_video_frame(group_id, frame_size=4096)
            streaming_data = create_streaming_message(
                track_alias, group_id, 0, frame_data
            )

            await relay._handle_subgroup_stream(publisher_client, streaming_data, 1)

        assert subscriber_client.quic_connection.send_stream_data.call_count == 10

    @pytest.mark.asyncio
    async def test_h264_like_streaming(
        self, relay, publisher_client, subscriber_client
    ):
        """Test streaming that simulates H.264 video with I/P/B frames."""
        track_name = FullTrackName([b"agent", b"video"], b"h264-stream")
        track_alias = 1

        publisher_client.publications[track_name] = {
            "track_alias": track_alias,
            "request_id": 1,
        }
        relay._publications[track_name] = publisher_client
        relay._subscriptions[track_name] = [subscriber_client]

        def generate_h264_frame(frame_type: str, group_id: int) -> bytes:
            sizes = {"I": 8192, "P": 2048, "B": 1024}
            size = sizes.get(frame_type, 4096)
            marker = {"I": 0x00, "P": 0x01, "B": 0x02}[frame_type]
            return bytes([marker, group_id % 256] + [0xAB] * (size - 2))

        frame_sequence = ["I", "P", "B", "B", "P", "B", "B", "P", "B", "B"]
        group_id = 0

        for frame_type in frame_sequence:
            frame_data = generate_h264_frame(frame_type, group_id)
            streaming_data = create_streaming_message(
                track_alias, group_id, 0, frame_data
            )
            await relay._handle_subgroup_stream(publisher_client, streaming_data, 1)

            if frame_type in ("I", "P"):
                group_id += 1

        assert subscriber_client.quic_connection.send_stream_data.call_count == len(
            frame_sequence
        )

    @pytest.mark.asyncio
    async def test_large_video_frame_streaming(
        self, relay, publisher_client, subscriber_client
    ):
        """Test streaming large video frames (e.g., 4K resolution)."""
        track_name = FullTrackName([b"agent", b"video"], b"4k-stream")
        track_alias = 1

        publisher_client.publications[track_name] = {
            "track_alias": track_alias,
            "request_id": 1,
        }
        relay._publications[track_name] = publisher_client
        relay._subscriptions[track_name] = [subscriber_client]

        large_frame_size = 1024 * 1024
        frame_data = bytes([0xFF] * large_frame_size)

        streaming_data = create_streaming_message(track_alias, 0, 0, frame_data)
        await relay._handle_subgroup_stream(publisher_client, streaming_data, 1)

        subscriber_client.quic_connection.send_stream_data.assert_called_once()
        call_args = subscriber_client.quic_connection.send_stream_data.call_args
        sent_data = call_args[0][1]
        assert len(sent_data) > large_frame_size
