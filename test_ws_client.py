#!/usr/bin/env python3
"""
简单 WebSocket 客户端测试脚本
用于验证 ACF 服务器的连接功能
"""

import asyncio
import websockets
import json
import sys

async def test_websocket_connection():
    """测试 WebSocket 连接"""
    uri = "ws://localhost:9002"
    
    print(f"正在连接 ACF 服务器: {uri}")
    
    try:
        async with websockets.connect(uri) as websocket:
            print("✓ WebSocket 连接成功建立")
            
            # 发送 SETUP 消息
            setup_msg = {
                "type": "SETUP",
                "timestamp": "2024-01-01T00:00:00Z",
                "payload": {
                    "src_agent_id": "test-client-001"
                }
            }
            
            print(f"发送 SETUP 消息: {json.dumps(setup_msg)}")
            await websocket.send(json.dumps(setup_msg))
            
            # 等待响应
            response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            print(f"收到响应: {response}")
            
            # 解析响应
            data = json.loads(response)
            if data.get("type") == "SETUP" and data.get("payload", {}).get("status") == "OK":
                print("✓ SETUP 握手成功")
            else:
                print(f"✗ SETUP 响应异常: {data}")
            
            # 保持连接几秒钟
            print("保持连接 3 秒...")
            await asyncio.sleep(3)
            
            print("✓ 测试完成，连接正常")
            
    except websockets.exceptions.InvalidStatusCode as e:
        print(f"✗ HTTP 握手失败: 状态码 {e.status_code}")
    except websockets.exceptions.ConnectionClosed as e:
        print(f"✗ 连接被关闭: {e}")
    except asyncio.TimeoutError:
        print("✗ 超时: 未收到响应")
    except ConnectionRefusedError:
        print(f"✗ 连接被拒绝: 服务器可能未启动或端口 9002 未开放")
    except Exception as e:
        print(f"✗ 错误: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_websocket_connection())
