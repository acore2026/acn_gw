#!/usr/bin/env python3
"""
MOQT Relay - 使用moq-py实现
保持与原有API完全兼容
"""

import sys
import asyncio
import json
import struct
import logging
from pathlib import Path
from typing import Optional, Dict, Set, Any
from datetime import datetime

# 添加moq-py到路径
moq_py_path = Path(__file__).parent / 'moq-py'
if str(moq_py_path) not in sys.path:
    sys.path.insert(0, str(moq_py_path))

from moq import MOQRelay as MOQPyRelay
from moq.encoding import FullTrackName, Location
from logger_config import moqt_logger as logger, LOG_DIR


def setup_moq_py_logging():
    """
    配置moq-py的日志输出到文件
    将所有MOQT相关日志统一保存到 logs/moqt.log
    """
    # 创建文件处理器
    moq_file_handler = logging.FileHandler(LOG_DIR / 'moqt.log', mode='a')
    moq_file_handler.setLevel(logging.INFO)
    moq_file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    
    # 为moq-py的所有logger添加处理器
    moq_py_loggers = [
        'moq.relay',
        'moq.relay.relay',
        'moq.transport',
        'moq.transport.quic_transport',
        'moq.session',
        'moq.session.session',
        'moq.pub',
        'moq.pub.publisher',
        'moq.sub',
        'moq.sub.subscriber'
    ]
    
    for logger_name in moq_py_loggers:
        moq_logger = logging.getLogger(logger_name)
        # 避免重复添加处理器
        if not any(isinstance(h, logging.FileHandler) and 
                   getattr(h, 'baseFilename', '') == str(LOG_DIR / 'moqt.log')
                   for h in moq_logger.handlers):
            moq_logger.addHandler(moq_file_handler)
        moq_logger.setLevel(logging.INFO)
    
    logger.info(f"Configured moq-py logging to {LOG_DIR / 'moqt.log'}")


# 初始化moq-py日志配置
setup_moq_py_logging()


class MockWriter:
    """
    模拟asyncio.StreamWriter，用于兼容测试API
    """
    def __init__(self, session_id: str = None):
        self.session_id = session_id or f"mock_{id(self)}"
        self._closed = False
        self._buffer = b""
    
    def write(self, data: bytes):
        if not self._closed:
            self._buffer += data
    
    async def drain(self):
        pass
    
    def close(self):
        self._closed = True
    
    async def wait_closed(self):
        pass
    
    def is_closing(self):
        return self._closed


class MOQTRelay:
    """
    MOQT Relay - 使用moq-py实现，保持API兼容
    """
    
    def __init__(self, host: str = '0.0.0.0', port: int = 9003,
                 cert_file: Optional[str] = None,
                 key_file: Optional[str] = None,
                 cache_dir: Optional[str] = None):
        """
        初始化Relay
        
        参数与原始实现保持一致，新增cache_dir参数
        """
        self.host = host
        self.port = port
        self.cert_file = cert_file
        self.key_file = key_file
        
        # 默认缓存目录
        if cache_dir is None:
            cache_dir = str(Path(__file__).parent / '.relay_cache')
        
        # 创建moq-py的MOQRelay实例
        self._relay = MOQPyRelay(
            host=host,
            port=port,
            cache_dir=cache_dir,
            max_memory_cache=100 * 1024 * 1024,      # 100MB
            max_disk_cache=1024 * 1024 * 1024,       # 1GB
            cert_file=cert_file,
            key_file=key_file
        )
        
        # 兼容层数据结构
        self._subscribers: Dict[str, Set[MockWriter]] = {}
        self._publishers: Dict[str, MockWriter] = {}
        self._tracks: Dict[str, dict] = {}
        
        logger.info(f"MOQTRelay initialized: {host}:{port}")
    
    async def start(self):
        """启动Relay"""
        logger.info(f"Starting MOQT Relay on {self.host}:{self.port}")
        await self._relay.start()
        logger.info("MOQT Relay started successfully")
    
    async def stop(self):
        """停止Relay"""
        logger.info("Stopping MOQT Relay...")
        await self._relay.stop()
        logger.info("MOQT Relay stopped")
    
    def get_cache_stats(self) -> dict:
        """获取缓存统计"""
        return self._relay.get_cache_stats()
    
    # ========== 测试兼容属性 ==========
    
    @property
    def subscribers(self) -> Dict[str, Set[MockWriter]]:
        """获取订阅者字典 (track_id -> set of writers)"""
        return self._subscribers
    
    @property
    def publishers(self) -> Dict[str, MockWriter]:
        """获取发布者字典 (track_id -> writer)"""
        return self._publishers
    
    @property
    def tracks(self) -> Dict[str, dict]:
        """获取轨道字典 (track_id -> track_info)"""
        return self._tracks
    
    # ========== 测试兼容方法 ==========
    
    async def handle_subscribe(self, writer: MockWriter, msg: dict):
        """
        处理订阅请求 (JSON格式)
        
        消息格式: {
            "type": "SUBSCRIBE",
            "track_id": "track-name",
            ...
        }
        """
        track_id = msg.get("track_id")
        if not track_id:
            await self.send_message(writer, {
                "type": "ERROR",
                "error": "Missing track_id"
            })
            return
        
        # 记录订阅
        if track_id not in self._subscribers:
            self._subscribers[track_id] = set()
        self._subscribers[track_id].add(writer)
        
        # 初始化track信息
        if track_id not in self._tracks:
            self._tracks[track_id] = {
                "id": track_id,
                "created_at": datetime.now().isoformat(),
                "subscriber_count": 0
            }
        
        self._tracks[track_id]["subscriber_count"] = len(self._subscribers[track_id])
        
        # 发送确认
        await self.send_message(writer, {
            "type": "SUBSCRIBE_OK",
            "track_id": track_id
        })
        
        logger.info(f"Subscription added for track: {track_id}")
    
    async def handle_publish(self, writer: MockWriter, msg: dict):
        """处理发布请求"""
        track_id = msg.get("track_id")
        if not track_id:
            await self.send_message(writer, {
                "type": "ERROR",
                "error": "Missing track_id"
            })
            return
        
        # 检查是否已有发布者
        if track_id in self._publishers:
            await self.send_message(writer, {
                "type": "ERROR",
                "error": f"Track {track_id} already has a publisher"
            })
            return
        
        # 记录发布者
        self._publishers[track_id] = writer
        
        # 初始化track信息
        if track_id not in self._tracks:
            self._tracks[track_id] = {
                "id": track_id,
                "created_at": datetime.now().isoformat(),
                "publisher": writer.session_id
            }
        
        # 发送确认
        await self.send_message(writer, {
            "type": "PUBLISH_OK",
            "track_id": track_id
        })
        
        logger.info(f"Publication registered for track: {track_id}")
    
    async def handle_object(self, writer: MockWriter, msg: dict):
        """处理对象消息（转发给订阅者）"""
        track_id = msg.get("track_id")
        if not track_id:
            return
        
        # 验证发布者权限
        if track_id not in self._publishers or self._publishers[track_id] != writer:
            await self.send_message(writer, {
                "type": "ERROR",
                "error": "Not authorized to publish to this track"
            })
            return
        
        # 转发给所有订阅者
        if track_id in self._subscribers:
            dead_subscribers = set()
            
            for subscriber in self._subscribers[track_id]:
                try:
                    if subscriber.is_closing():
                        dead_subscribers.add(subscriber)
                    else:
                        await self.send_message(subscriber, msg)
                except Exception as e:
                    logger.warning(f"Failed to forward to subscriber: {e}")
                    dead_subscribers.add(subscriber)
            
            # 清理断开的订阅者
            for dead in dead_subscribers:
                self._subscribers[track_id].discard(dead)
                logger.info(f"Removed dead subscriber from {track_id}")
            
            # 如果没有订阅者了，清理track
            if not self._subscribers[track_id]:
                del self._subscribers[track_id]
                logger.info(f"No more subscribers for track: {track_id}")
    
    async def handle_unsubscribe(self, writer: MockWriter, msg: dict):
        """处理取消订阅"""
        track_id = msg.get("track_id")
        if not track_id:
            return
        
        if track_id in self._subscribers:
            self._subscribers[track_id].discard(writer)
            
            if not self._subscribers[track_id]:
                del self._subscribers[track_id]
                logger.info(f"Removed track {track_id} (no subscribers)")
            else:
                logger.info(f"Unsubscribed from {track_id}")
        
        # 更新track统计
        if track_id in self._tracks:
            self._tracks[track_id]["subscriber_count"] = len(
                self._subscribers.get(track_id, set())
            )
    
    async def cleanup_client(self, writer: MockWriter):
        """清理断开连接的客户端"""
        # 从发布者中移除
        tracks_to_remove = []
        for track_id, pub_writer in list(self._publishers.items()):
            if pub_writer == writer:
                tracks_to_remove.append(track_id)
        
        for track_id in tracks_to_remove:
            del self._publishers[track_id]
            logger.info(f"Removed publisher for track: {track_id}")
        
        # 从订阅者中移除
        for track_id, subscribers in list(self._subscribers.items()):
            if writer in subscribers:
                subscribers.discard(writer)
                if not subscribers:
                    del self._subscribers[track_id]
                    logger.info(f"Removed track {track_id} (no subscribers)")
        
        writer.close()
        logger.info(f"Cleaned up client: {writer.session_id}")
    
    async def send_message(self, writer: MockWriter, msg: dict):
        """
        发送JSON消息（带4字节长度前缀）
        
        格式: [4字节长度(大端)] + [JSON数据]
        """
        try:
            data = json.dumps(msg).encode('utf-8')
            length = struct.pack('>I', len(data))  # 4字节大端
            writer.write(length + data)
            await writer.drain()
        except Exception as e:
            logger.error(f"Failed to send message: {e}")


# 保持向后兼容：导出MOQTRelay
__all__ = ['MOQTRelay', 'MockWriter']
