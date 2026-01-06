"""WebSocket client for StandX Perps API.

Handles two WebSocket connections:
1. Market stream (wss://perps.standx.com/ws-stream/v1) - price data
2. User stream (wss://perps.standx.com/ws-api/v1) - order/position updates
"""
import json
import asyncio
import logging
from typing import Optional, Callable, Awaitable

import websockets
from websockets.client import WebSocketClientProtocol

from .auth import StandXAuth


logger = logging.getLogger(__name__)


class MarketWSClient:
    """WebSocket client for market data stream."""
    
    WS_URL = "wss://perps.standx.com/ws-stream/v1"
    
    def __init__(self):
        self._ws: Optional[WebSocketClientProtocol] = None
        self._running = False
        self._callbacks: dict[str, list[Callable]] = {}
    
    async def connect(self):
        """Connect to market data stream."""
        logger.info(f"Connecting to market stream: {self.WS_URL}")
        self._ws = await websockets.connect(self.WS_URL)
        self._running = True
        logger.info("Market stream connected")
    
    async def subscribe_price(self, symbol: str):
        """Subscribe to price channel for a symbol."""
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        
        msg = {"subscribe": {"channel": "price", "symbol": symbol}}
        await self._ws.send(json.dumps(msg))
        logger.info(f"Subscribed to price channel for {symbol}")
    
    def on_price(self, callback: Callable[[dict], None]):
        """Register callback for price updates."""
        if "price" not in self._callbacks:
            self._callbacks["price"] = []
        self._callbacks["price"].append(callback)
    
    async def run(self):
        """Run the message receive loop."""
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        
        while self._running:
            try:
                message = await asyncio.wait_for(self._ws.recv(), timeout=30)
                data = json.loads(message)
                
                # Handle ping/pong
                if data.get("ping"):
                    await self._ws.send(json.dumps({"pong": data["ping"]}))
                    continue
                
                # Dispatch to callbacks
                channel = data.get("channel")
                if channel in self._callbacks:
                    for callback in self._callbacks[channel]:
                        try:
                            callback(data)
                        except Exception as e:
                            logger.error(f"Callback error: {e}")
                            
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                try:
                    await self._ws.send(json.dumps({"ping": 1}))
                except Exception as e:
                    logger.error(f"Ping failed: {e}")
                    break
            except websockets.ConnectionClosed:
                logger.warning("Market stream connection closed")
                break
            except Exception as e:
                logger.error(f"Error in market stream: {e}")
                break
        
        self._running = False
    
    async def close(self):
        """Close the WebSocket connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None


class UserWSClient:
    """WebSocket client for user data stream (orders, positions)."""
    
    WS_URL = "wss://perps.standx.com/ws-api/v1"
    
    def __init__(self, auth: StandXAuth):
        self._auth = auth
        self._ws: Optional[WebSocketClientProtocol] = None
        self._running = False
        self._session_id: Optional[str] = None
        self._callbacks: dict[str, list[Callable]] = {}
    
    async def connect(self):
        """Connect to user data stream."""
        import uuid
        
        logger.info(f"Connecting to user stream: {self.WS_URL}")
        self._ws = await websockets.connect(self.WS_URL)
        self._session_id = str(uuid.uuid4())
        self._running = True
        logger.info("User stream connected")
        
        # Authenticate
        await self._authenticate()
    
    async def _authenticate(self):
        """Authenticate the WebSocket connection."""
        if not self._ws or not self._auth.token:
            raise RuntimeError("WebSocket not connected or not authenticated")
        
        msg = {
            "session_id": self._session_id,
            "request_id": str(__import__("uuid").uuid4()),
            "method": "auth:login",
            "params": json.dumps({"token": self._auth.token}),
        }
        
        await self._ws.send(json.dumps(msg))
        logger.info("User stream authentication sent")
        
        # Wait for auth response
        response = await self._ws.recv()
        data = json.loads(response)
        
        if data.get("code") != 0:
            raise RuntimeError(f"User stream auth failed: {data}")
        
        logger.info("User stream authenticated")
    
    def on_order(self, callback: Callable[[dict], None]):
        """Register callback for order updates."""
        if "order" not in self._callbacks:
            self._callbacks["order"] = []
        self._callbacks["order"].append(callback)
    
    def on_position(self, callback: Callable[[dict], None]):
        """Register callback for position updates."""
        if "position" not in self._callbacks:
            self._callbacks["position"] = []
        self._callbacks["position"].append(callback)
    
    def on_trade(self, callback: Callable[[dict], None]):
        """Register callback for trade updates."""
        if "trade" not in self._callbacks:
            self._callbacks["trade"] = []
        self._callbacks["trade"].append(callback)
    
    async def run(self):
        """Run the message receive loop."""
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        
        while self._running:
            try:
                message = await asyncio.wait_for(self._ws.recv(), timeout=30)
                data = json.loads(message)
                
                # Handle ping/pong
                if data.get("ping"):
                    await self._ws.send(json.dumps({"pong": data["ping"]}))
                    continue
                
                # Dispatch to callbacks based on channel or type
                channel = data.get("channel")
                if channel in self._callbacks:
                    for callback in self._callbacks[channel]:
                        try:
                            callback(data)
                        except Exception as e:
                            logger.error(f"Callback error: {e}")
                            
            except asyncio.TimeoutError:
                # Send ping
                try:
                    await self._ws.send(json.dumps({"ping": 1}))
                except Exception as e:
                    logger.error(f"Ping failed: {e}")
                    break
            except websockets.ConnectionClosed:
                logger.warning("User stream connection closed")
                break
            except Exception as e:
                logger.error(f"Error in user stream: {e}")
                break
        
        self._running = False
    
    async def close(self):
        """Close the WebSocket connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
