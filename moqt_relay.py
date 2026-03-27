#!/usr/bin/env python3
"""
MOQT Relay Server
MOQT protocol on port 9003
Publishes, subscribes to Tracks and forwards Objects
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Set
import struct

class MOQTRelay:
    """
    MOQT (Media over QUIC Transport) Relay
    Handles track publishing and subscription
    """
    
    def __init__(self, host='0.0.0.0', port=9003):
        self.host = host
        self.port = port
        self.tracks: Dict[str, Dict] = {}  # track_id -> track_info
        self.subscribers: Dict[str, Set[asyncio.StreamWriter]] = {}  # track_id -> set of writers
        self.publishers: Dict[str, asyncio.StreamWriter] = {}  # track_id -> publisher writer
        
    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle incoming MOQT client connection"""
        client_addr = writer.get_extra_info('peername')
        print(f"MOQT: Client connected from {client_addr}")
        
        try:
            while True:
                # Read message length (4 bytes)
                length_data = await reader.read(4)
                if not length_data:
                    break
                    
                msg_length = struct.unpack('!I', length_data)[0]
                
                # Read message
                message_data = await reader.read(msg_length)
                if not message_data:
                    break
                
                try:
                    message = json.loads(message_data.decode('utf-8'))
                    msg_type = message.get('type')
                    
                    if msg_type == 'SUBSCRIBE':
                        await self.handle_subscribe(writer, message)
                    elif msg_type == 'PUBLISH':
                        await self.handle_publish(writer, message)
                    elif msg_type == 'OBJECT':
                        await self.handle_object(writer, message)
                    elif msg_type == 'UNSUBSCRIBE':
                        await self.handle_unsubscribe(writer, message)
                    else:
                        print(f"MOQT: Unknown message type: {msg_type}")
                        
                except json.JSONDecodeError:
                    print(f"MOQT: Invalid JSON received from {client_addr}")
                except Exception as e:
                    print(f"MOQT: Error processing message: {e}")
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"MOQT: Connection error with {client_addr}: {e}")
        finally:
            await self.cleanup_client(writer)
            writer.close()
            await writer.wait_closed()
            print(f"MOQT: Client {client_addr} disconnected")
    
    async def handle_subscribe(self, writer: asyncio.StreamWriter, message: dict):
        """Handle SUBSCRIBE message"""
        track_id = message.get('track_id')
        
        if track_id not in self.subscribers:
            self.subscribers[track_id] = set()
        
        self.subscribers[track_id].add(writer)
        
        # Send SUBSCRIBE_OK
        response = {
            "type": "SUBSCRIBE_OK",
            "track_id": track_id,
            "timestamp": datetime.utcnow().isoformat() + 'Z'
        }
        await self.send_message(writer, response)
        
        print(f"MOQT: Client subscribed to track {track_id}")
    
    async def handle_publish(self, writer: asyncio.StreamWriter, message: dict):
        """Handle PUBLISH message"""
        track_id = message.get('track_id')
        
        self.tracks[track_id] = {
            'publisher': writer,
            'created_at': datetime.utcnow().isoformat() + 'Z'
        }
        self.publishers[track_id] = writer
        
        # Send PUBLISH_OK
        response = {
            "type": "PUBLISH_OK",
            "track_id": track_id,
            "timestamp": datetime.utcnow().isoformat() + 'Z'
        }
        await self.send_message(writer, response)
        
        print(f"MOQT: Track {track_id} published")
    
    async def handle_object(self, writer: asyncio.StreamWriter, message: dict):
        """Handle OBJECT message - forward to subscribers"""
        track_id = message.get('track_id')
        
        # Verify this writer is the publisher of this track
        if track_id not in self.publishers or self.publishers[track_id] != writer:
            print(f"MOQT: Unauthorized object publish for track {track_id}")
            return
        
        # Forward to all subscribers
        if track_id in self.subscribers:
            dead_subscribers = set()
            
            for subscriber in self.subscribers[track_id]:
                try:
                    await self.send_message(subscriber, message)
                except Exception as e:
                    print(f"MOQT: Error forwarding to subscriber: {e}")
                    dead_subscribers.add(subscriber)
            
            # Remove dead subscribers
            self.subscribers[track_id] -= dead_subscribers
            
            print(f"MOQT: Forwarded object on track {track_id} to {len(self.subscribers[track_id])} subscribers")
    
    async def handle_unsubscribe(self, writer: asyncio.StreamWriter, message: dict):
        """Handle UNSUBSCRIBE message"""
        track_id = message.get('track_id')
        
        if track_id in self.subscribers:
            self.subscribers[track_id].discard(writer)
        
        # Send UNSUBSCRIBE_OK
        response = {
            "type": "UNSUBSCRIBE_OK",
            "track_id": track_id,
            "timestamp": datetime.utcnow().isoformat() + 'Z'
        }
        await self.send_message(writer, response)
        
        print(f"MOQT: Client unsubscribed from track {track_id}")
    
    async def send_message(self, writer: asyncio.StreamWriter, message: dict):
        """Send a message to a client"""
        data = json.dumps(message).encode('utf-8')
        length = struct.pack('!I', len(data))
        writer.write(length + data)
        await writer.drain()
    
    async def cleanup_client(self, writer: asyncio.StreamWriter):
        """Clean up when a client disconnects"""
        # Remove from publishers
        tracks_to_remove = []
        for track_id, pub_writer in self.publishers.items():
            if pub_writer == writer:
                tracks_to_remove.append(track_id)
        
        for track_id in tracks_to_remove:
            del self.publishers[track_id]
            if track_id in self.tracks:
                del self.tracks[track_id]
            print(f"MOQT: Track {track_id} removed (publisher disconnected)")
        
        # Remove from subscribers
        for track_id, subscribers in self.subscribers.items():
            subscribers.discard(writer)
    
    async def start(self):
        """Start the MOQT relay server"""
        server = await asyncio.start_server(
            self.handle_client,
            self.host,
            self.port
        )
        
        addr = server.sockets[0].getsockname()
        print(f"MOQT Relay Server started on {addr}")
        
        async with server:
            await server.serve_forever()

if __name__ == '__main__':
    relay = MOQTRelay()
    asyncio.run(relay.start())
