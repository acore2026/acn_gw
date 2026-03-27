#!/usr/bin/env python3
"""
MOQT Relay Server for Agent GW
Full MOQT implementation using QUIC transport
Compatible with moq/moq/moq implementation
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple, Callable, Any
from dataclasses import dataclass, field

from moqt.encoding import FullTrackName, Location
from moqt.messages import (
    SubscribeMessage, SubscribeOkMessage, PublishMessage, PublishOkMessage,
    FetchMessage, FetchOkMessage, decode_control_message, GroupOrder, ErrorCode,
    ObjectDatagram, ObjectHeader
)
from moqt.transport import QUICServer, is_quic_available, StreamData, DatagramData
from logger_config import moqt_logger as logger


@dataclass
class ClientSession:
    """Represents a connected client session over QUIC."""
    session_id: str
    protocol: Any  # MOQQuicProtocol instance
    quic_connection: Any  # QuicConnection instance
    role: Optional[str] = None
    subscriptions: Dict[FullTrackName, dict] = field(default_factory=dict)
    publications: Dict[FullTrackName, dict] = field(default_factory=dict)
    control_stream_id: Optional[int] = None
    control_buffer: bytes = b""


@dataclass
class CachedObject:
    """Cached object with metadata."""
    track_alias: int
    group_id: int
    object_id: int
    publisher_priority: int
    payload: bytes
    timestamp: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    
    def to_bytes(self) -> bytes:
        """Serialize to bytes."""
        header = ObjectHeader(
            track_alias=self.track_alias,
            group_id=self.group_id,
            object_id=self.object_id,
            publisher_priority=self.publisher_priority
        )
        datagram = ObjectDatagram(header=header, payload=self.payload)
        return datagram.encode()
    
    @staticmethod
    def from_bytes(data: bytes) -> 'CachedObject':
        """Deserialize from bytes."""
        datagram, _ = ObjectDatagram.decode(data)
        return CachedObject(
            track_alias=datagram.header.track_alias,
            group_id=datagram.header.group_id,
            object_id=datagram.header.object_id,
            publisher_priority=datagram.header.publisher_priority,
            payload=datagram.payload
        )
    
    def get_location(self) -> Location:
        """Get object location."""
        return Location(self.group_id, self.object_id)


class ObjectCache:
    """Cache for MOQT objects with memory backing."""
    
    def __init__(self, max_memory_size: int = 100 * 1024 * 1024):  # 100MB default
        self.max_memory_size = max_memory_size
        
        # Memory cache: track_name -> {location -> CachedObject}
        self._memory_cache: Dict[FullTrackName, Dict[Location, CachedObject]] = {}
        self._memory_size = 0
        
        # Statistics
        self._hits = 0
        self._misses = 0
    
    def put(self, track_name: FullTrackName, obj: CachedObject):
        """Add object to cache."""
        location = obj.get_location()
        
        # Add to memory cache
        if track_name not in self._memory_cache:
            self._memory_cache[track_name] = {}
        
        # Remove old object if exists
        if location in self._memory_cache[track_name]:
            old_obj = self._memory_cache[track_name][location]
            self._memory_size -= len(old_obj.payload)
        
        # Add new object
        self._memory_cache[track_name][location] = obj
        self._memory_size += len(obj.payload)
        
        # Evict from memory if needed
        self._evict_memory_if_needed()
    
    def _evict_memory_if_needed(self):
        """Evict objects from memory cache if size exceeds limit."""
        if self._memory_size <= self.max_memory_size:
            return
        
        # Simple LRU eviction
        all_objects = []
        for track_name, objects in self._memory_cache.items():
            for location, obj in objects.items():
                all_objects.append((track_name, location, obj))
        
        # Sort by access time (oldest first)
        all_objects.sort(key=lambda x: x[2].timestamp)
        
        # Evict oldest objects
        while self._memory_size > self.max_memory_size * 0.8 and all_objects:
            track_name, location, obj = all_objects.pop(0)
            if location in self._memory_cache.get(track_name, {}):
                del self._memory_cache[track_name][location]
                self._memory_size -= len(obj.payload)
                logger.debug(f"Evicted from memory: {track_name} @ {location}")
    
    def get(self, track_name: FullTrackName, location: Location) -> Optional[CachedObject]:
        """Get object from cache."""
        # Try memory cache
        if track_name in self._memory_cache:
            if location in self._memory_cache[track_name]:
                obj = self._memory_cache[track_name][location]
                obj.access_count += 1
                obj.timestamp = datetime.now()
                self._hits += 1
                return obj
        
        self._misses += 1
        return None
    
    def get_range(self, track_name: FullTrackName, 
                  start: Location, end: Location) -> List[CachedObject]:
        """Get all objects in range from cache."""
        objects = []
        
        if track_name not in self._memory_cache:
            return objects
        
        for location, obj in self._memory_cache[track_name].items():
            if start <= location <= end:
                obj.access_count += 1
                objects.append(obj)
        
        # Sort by location
        objects.sort(key=lambda o: o.get_location())
        return objects
    
    def get_statistics(self) -> dict:
        """Get cache statistics."""
        total_requests = self._hits + self._misses
        hit_rate = self._hits / total_requests if total_requests > 0 else 0
        
        return {
            'memory_size': self._memory_size,
            'memory_objects': sum(len(objs) for objs in self._memory_cache.values()),
            'hits': self._hits,
            'misses': self._misses,
            'hit_rate': hit_rate
        }


class MOQTRelay:
    """
    MOQT Relay Server for Agent GW
    Full MOQT implementation using QUIC transport
    Port: 9003
    """
    
    def __init__(self, host: str = '0.0.0.0', port: int = 9003,
                 cert_file: Optional[str] = None,
                 key_file: Optional[str] = None):
        
        # Check QUIC availability
        if not is_quic_available():
            raise RuntimeError("QUIC is not available. Please install aioquic.")
        
        self.host = host
        self.port = port
        
        # Cache
        self.cache = ObjectCache()
        
        # Client management
        self._clients: Dict[str, ClientSession] = {}
        self._publications: Dict[FullTrackName, ClientSession] = {}
        self._subscriptions: Dict[FullTrackName, List[ClientSession]] = {}
        self._object_cache: Dict[FullTrackName, List[dict]] = {}
        self._max_cached_objects = 1000  # Limit cache size
        self._running = False
        
        # QUIC Server
        self._quic_server = QUICServer(
            host=host,
            port=port,
            use_datagrams=True,
            cert_file=cert_file,
            key_file=key_file
        )
        
        logger.info(f"MOQTRelay initialized: {host}:{port} (QUIC)")
    
    async def start(self):
        """Start the relay server using QUIC transport."""
        self._running = True
        
        # Set up QUIC server handlers
        self._quic_server.set_handlers(
            on_client_connect=self._on_quic_client_connect,
            on_stream_data=self._on_quic_stream_data,
            on_datagram=self._on_quic_datagram,
            on_client_disconnect=self._on_quic_client_disconnect
        )
        
        # Start QUIC server
        await self._quic_server.start()
        
        logger.info(f"MOQ Relay running on {self.host}:{self.port} (QUIC)")
        logger.info("Waiting for connections... (Press Ctrl+C to stop)")
    
    async def stop(self):
        """Stop the relay server."""
        self._running = False
        
        # Stop the QUIC server
        if self._quic_server:
            await self._quic_server.stop()
        
        # Close all client connections
        for client in list(self._clients.values()):
            try:
                if hasattr(client.protocol, 'close'):
                    client.protocol.close()
            except:
                pass
        self._clients.clear()
        
        logger.info("Relay server stopped")
    
    async def _on_quic_client_connect(self, protocol):
        """Handle new QUIC client connection."""
        client = self._get_or_create_client(protocol)
        logger.info(f"QUIC client connected: {client.session_id}")
    
    async def _on_quic_client_disconnect(self, protocol, error_code, reason):
        """Handle QUIC client disconnection."""
        # Find client by protocol
        for session_id, client in list(self._clients.items()):
            if client.protocol == protocol:
                await self._cleanup_client(client)
                break
        
        logger.info(f"QUIC client disconnected: error_code={error_code}, reason={reason}")
    
    async def _on_quic_stream_data(self, protocol, stream_data: StreamData):
        """Handle data received on a QUIC stream."""
        client = self._get_or_create_client(protocol)
        
        # Set control stream if not set
        if client.control_stream_id is None:
            client.control_stream_id = stream_data.stream_id
        
        if stream_data.stream_id == client.control_stream_id:
            await self._handle_control_stream_data(client, stream_data.data, end_stream=stream_data.end_stream)
        else:
            await self._handle_message(client, stream_data.data)
    
    async def _on_quic_datagram(self, protocol, datagram_data: DatagramData):
        """Handle data received as QUIC datagram."""
        client = self._get_or_create_client(protocol)
        await self._handle_message(client, datagram_data.data)
    
    async def _handle_message(self, client: ClientSession, data: bytes):
        """Handle a message from a client."""
        try:
            # Try to decode as control message first
            try:
                msg, _ = decode_control_message(data)
                
                if isinstance(msg, PublishMessage):
                    await self._handle_publish(client, msg)
                elif isinstance(msg, SubscribeMessage):
                    await self._handle_subscribe(client, msg)
                elif isinstance(msg, FetchMessage):
                    await self._handle_fetch(client, msg)
                else:
                    logger.debug(f"Received control message type: {type(msg).__name__}")
                return
            except Exception as e:
                logger.debug(f"Not a control message: {e}")
                pass  # Not a control message, try data message
            
            # Try to decode as ObjectDatagram (data message)
            try:
                obj, _ = ObjectDatagram.decode(data)
                await self._handle_object(client, obj)
                return
            except Exception as e:
                logger.debug(f"Not an ObjectDatagram: {e}")
                pass  # Not an ObjectDatagram either
            
            # Treat as raw data
            logger.debug(f"Received raw data: {len(data)} bytes")
                
        except Exception as e:
            logger.error(f"Error handling message: {e}")

    async def _handle_control_stream_data(self, client: ClientSession, data: bytes, end_stream: bool = False):
        """Handle buffered control stream data from a client."""
        client.control_buffer += data

        while client.control_buffer:
            try:
                msg, consumed = decode_control_message(client.control_buffer)
            except Exception as e:
                if end_stream:
                    logger.warning(f"Failed to decode control message from {client.session_id}: {e}")
                    client.control_buffer = b""
                break

            client.control_buffer = client.control_buffer[consumed:]
            await self._dispatch_control_message(client, msg)

    async def _dispatch_control_message(self, client: ClientSession, msg: object):
        """Dispatch a decoded control message."""
        if isinstance(msg, PublishMessage):
            await self._handle_publish(client, msg)
        elif isinstance(msg, SubscribeMessage):
            await self._handle_subscribe(client, msg)
        elif isinstance(msg, FetchMessage):
            await self._handle_fetch(client, msg)
        else:
            logger.debug(f"Received control message type: {type(msg).__name__}")

    def _get_or_create_client(self, protocol) -> ClientSession:
        """Find the client session for a protocol, creating it if needed."""
        for client in self._clients.values():
            if client.protocol == protocol:
                return client

        session_id = f"{protocol._quic.host_cid}"
        client = ClientSession(
            session_id=session_id,
            protocol=protocol,
            quic_connection=protocol._quic
        )
        self._clients[session_id] = client
        logger.info(f"QUIC client registered: {session_id}")
        return client
    
    async def _handle_publish(self, client: ClientSession, msg: PublishMessage):
        """Handle a publish request."""
        track_name = msg.full_track_name
        logger.info(f"Client {client.session_id} publishing: {track_name}")
        
        # Store publication
        self._publications[track_name] = client
        client.publications[track_name] = {
            'track_alias': msg.track_alias,
            'request_id': msg.request_id
        }
        
        # Send PUBLISH_OK
        response = PublishOkMessage(request_id=msg.request_id)
        response_data = response.encode()
        logger.debug(f"Sending PUBLISH_OK: {len(response_data)} bytes")
        await self._send_control_message(client, response_data)
        logger.info(f"Publication accepted: {track_name}")
    
    async def _handle_subscribe(self, client: ClientSession, msg: SubscribeMessage):
        """Handle a subscribe request."""
        track_name = msg.full_track_name
        logger.info(f"Client {client.session_id} subscribing to: {track_name}")
        
        # Store subscription
        if track_name not in self._subscriptions:
            self._subscriptions[track_name] = []
        self._subscriptions[track_name].append(client)
        client.subscriptions[track_name] = {
            'track_alias': msg.track_alias,
            'request_id': msg.request_id
        }
        
        # Send SUBSCRIBE_OK
        response = SubscribeOkMessage(
            request_id=msg.request_id,
            expires=0,
            group_order=GroupOrder.ASCENDING
        )
        response_data = response.encode()
        logger.debug(f"Sending SUBSCRIBE_OK: {len(response_data)} bytes")
        await self._send_control_message(client, response_data)
        logger.info(f"Subscription accepted: {track_name}")
    
    async def _handle_fetch(self, client: ClientSession, msg: FetchMessage):
        """Handle a fetch request."""
        track_name = msg.full_track_name
        logger.info(f"Client {client.session_id} fetching from: {track_name}")
        
        # Check if track exists (has a publisher or cached objects)
        has_cached_objects = track_name in self._object_cache and len(self._object_cache[track_name]) > 0
        if track_name not in self._publications and not has_cached_objects:
            from moqt.messages.control import RequestErrorMessage, ErrorCode
            logger.warning(f"Fetch requested for unknown track: {track_name}")
            response = RequestErrorMessage(
                request_id=msg.request_id,
                error_code=ErrorCode.INTERNAL_ERROR,
                reason="Track not found"
            )
            await self._send_control_message(client, response.encode())
            return
        
        # Store fetch request
        if track_name not in self._subscriptions:
            self._subscriptions[track_name] = []
        self._subscriptions[track_name].append(client)
        
        # Send FETCH_OK
        response = FetchOkMessage(
            request_id=msg.request_id,
            group_order=GroupOrder.ASCENDING,
            end_of_track=False
        )
        response_data = response.encode()
        logger.debug(f"Sending FETCH_OK: {len(response_data)} bytes")
        await self._send_control_message(client, response_data)
        if track_name in self._publications:
            logger.info(f"Fetch accepted: {track_name}")
        else:
            logger.info(f"Fetch accepted from cache: {track_name}")
        
        # Send cached objects that match the fetch range
        await self._send_cached_objects(client, track_name, msg)
    
    async def _send_cached_objects(self, client: ClientSession, track_name: FullTrackName, msg: FetchMessage):
        """Send cached objects that match the fetch range to the client."""
        cached_objects = self._object_cache.get(track_name, [])
        if not cached_objects:
            logger.info(f"No cached objects for track: {track_name}")
            return
        
        sent_count = 0
        for obj_data in cached_objects:
            # Check if object is within fetch range
            end_group_limit = msg.end_group if msg.end_group is not None else float('inf')
            end_object_limit = msg.end_object if msg.end_object is not None else float('inf')
            
            if (msg.start_group <= obj_data['group_id'] <= end_group_limit and
                msg.start_object <= obj_data['object_id'] <= end_object_limit):
                
                # Create ObjectDatagram and send
                header = ObjectHeader(
                    track_alias=obj_data['track_alias'],
                    group_id=obj_data['group_id'],
                    object_id=obj_data['object_id'],
                    publisher_priority=obj_data['publisher_priority'],
                    object_status=obj_data['object_status']
                )
                obj = ObjectDatagram(header=header, payload=obj_data['payload'])
                
                try:
                    await self._send_datagram(client, obj.encode())
                    sent_count += 1
                except Exception as e:
                    logger.error(f"Error sending cached object to {client.session_id}: {e}")
        
        logger.info(f"Sent {sent_count} cached objects to {client.session_id} for fetch request")
    
    async def _handle_object(self, client: ClientSession, obj: ObjectDatagram):
        """Handle an object from a publisher."""
        # Find the track name from the client's publications
        track_name = None
        for tn, pub_info in client.publications.items():
            if pub_info['track_alias'] == obj.header.track_alias:
                track_name = tn
                break
        
        if not track_name:
            logger.warning(f"Received object for unknown track alias: {obj.header.track_alias}")
            return
        
        # Cache the object for future fetches
        await self._cache_object(track_name, obj)
        
        # Also cache in the ObjectCache for advanced caching features
        cached_obj = CachedObject(
            track_alias=obj.header.track_alias,
            group_id=obj.header.group_id,
            object_id=obj.header.object_id,
            publisher_priority=obj.header.publisher_priority,
            payload=obj.payload
        )
        self.cache.put(track_name, cached_obj)
        
        # Forward to all subscribers
        await self._forward_object(track_name, obj)
    
    async def _cache_object(self, track_name: FullTrackName, obj: ObjectDatagram):
        """Cache an object for future fetch requests."""
        if track_name not in self._object_cache:
            self._object_cache[track_name] = []
        
        # Store object data
        self._object_cache[track_name].append({
            'track_alias': obj.header.track_alias,
            'group_id': obj.header.group_id,
            'object_id': obj.header.object_id,
            'publisher_priority': obj.header.publisher_priority,
            'object_status': obj.header.object_status,
            'payload': obj.payload
        })
        
        # Limit cache size
        if len(self._object_cache[track_name]) > self._max_cached_objects:
            self._object_cache[track_name].pop(0)
        
        logger.debug(f"Cached object for {track_name}: group={obj.header.group_id}, object={obj.header.object_id}")
    
    async def _forward_object(self, track_name: FullTrackName, obj: ObjectDatagram):
        """Forward an object to all subscribers of a track."""
        subscribers = self._subscriptions.get(track_name, [])
        if not subscribers:
            return

        data = obj.encode()
        forwarded = 0

        for subscriber in subscribers:
            try:
                await self._send_datagram(subscriber, data)
                forwarded += 1
            except Exception as e:
                logger.error(f"Error forwarding to {subscriber.session_id}: {e}")
        
        if forwarded > 0:
            logger.debug(f"Forwarded object to {forwarded} subscribers")
    
    async def _send_control_message(self, client: ClientSession, data: bytes):
        """Send a message to a client over QUIC."""
        try:
            if client.control_stream_id is not None:
                # Send on control stream
                client.quic_connection.send_stream_data(client.control_stream_id, data)
            else:
                # Open a new stream or use datagram
                stream_id = client.quic_connection.get_next_available_stream_id(is_unidirectional=False)
                client.quic_connection.send_stream_data(stream_id, data)
            
            # Transmit the data
            if hasattr(client.protocol, 'transmit'):
                client.protocol.transmit()
            
            logger.debug(f"Sent {len(data)} bytes to {client.session_id}")
        except Exception as e:
            logger.error(f"Error sending message to {client.session_id}: {e}")
            raise

    async def _send_datagram(self, client: ClientSession, data: bytes):
        """Send a datagram to a client over QUIC."""
        try:
            client.quic_connection.send_datagram_frame(data)
            if hasattr(client.protocol, 'transmit'):
                client.protocol.transmit()
            logger.debug(f"Sent datagram {len(data)} bytes to {client.session_id}")
        except Exception as e:
            logger.error(f"Error sending datagram to {client.session_id}: {e}")
            raise
    
    async def _cleanup_client(self, client: ClientSession):
        """Clean up when a client disconnects."""
        logger.info(f"Client disconnected: {client.session_id}")
        
        # Remove from clients
        if client.session_id in self._clients:
            del self._clients[client.session_id]
        
        # Remove publications
        for track_name in list(client.publications.keys()):
            if track_name in self._publications and self._publications[track_name].session_id == client.session_id:
                del self._publications[track_name]
                logger.info(f"Publication removed: {track_name}")
        
        # Remove subscriptions
        for track_name in list(client.subscriptions.keys()):
            if track_name in self._subscriptions:
                self._subscriptions[track_name] = [
                    s for s in self._subscriptions[track_name] 
                    if s.session_id != client.session_id
                ]
                if not self._subscriptions[track_name]:
                    del self._subscriptions[track_name]

    def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        return self.cache.get_statistics()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    relay = MOQTRelay()
    asyncio.run(relay.start())
