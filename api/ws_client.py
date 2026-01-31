"""WebSocket client for StandX Perps API.

Handles two WebSocket connections:
1. Market stream (wss://perps.standx.com/ws-stream/v1) - price data
2. User stream (wss://perps.standx.com/ws-api/v1) - order/position updates

Both clients support auto-reconnection.
"""
import json
import asyncio
import logging
from typing import Optional, Callable

import websockets
from websockets.client import WebSocketClientProtocol

from .auth import StandXAuth


logger = logging.getLogger(__name__)


class MarketWSClient:
    """WebSocket client for market data stream with auto-reconnection."""
    
    WS_URL = "wss://perps.standx.com/ws-stream/v1"
    RECONNECT_DELAY = 5  # seconds
    
    def __init__(self):
        self._ws: Optional[WebSocketClientProtocol] = None
        self._running = False
        self._callbacks: dict[str, list[Callable]] = {}
        self._subscribed_symbols: list[str] = []
        self._msg_count = 0
        self._last_log_time = 0
    
    async def connect(self):
        """Connect to market data stream."""
        logger.info(f"Connecting to market stream: {self.WS_URL}")
        self._ws = await websockets.connect(
            self.WS_URL,
            ping_interval=None,  # Server sends ping, we just respond
            ping_timeout=60,     # Long timeout to avoid false disconnects
            close_timeout=10,
        )
        self._running = True
        logger.info("Market stream connected")
    
    async def subscribe_price(self, symbol: str):
        """Subscribe to price channel for a symbol."""
        if symbol not in self._subscribed_symbols:
            self._subscribed_symbols.append(symbol)
        
        if self._ws:
            msg = {"subscribe": {"channel": "price", "symbol": symbol}}
            await self._ws.send(json.dumps(msg))
            logger.info(f"Subscribed to price channel for {symbol}")
    
    def on_price(self, callback: Callable[[dict], None]):
        """Register callback for price updates."""
        if "price" not in self._callbacks:
            self._callbacks["price"] = []
        self._callbacks["price"].append(callback)
    
    async def _reconnect(self):
        """Reconnect and resubscribe."""
        logger.info(f"Reconnecting in {self.RECONNECT_DELAY} seconds...")
        await asyncio.sleep(self.RECONNECT_DELAY)
        
        try:
            await self.connect()
            # Resubscribe to all symbols
            for symbol in self._subscribed_symbols:
                msg = {"subscribe": {"channel": "price", "symbol": symbol}}
                await self._ws.send(json.dumps(msg))
                logger.info(f"Resubscribed to price channel for {symbol}")
        except Exception as e:
            logger.error(f"Reconnection failed: {e}")
            return False
        
        return True
    
    async def run(self):
        """Run the message receive loop with auto-reconnection."""
        self._running = True
        
        while self._running:
            if not self._ws:
                if not await self._reconnect():
                    continue
            
            try:
                # Use timeout to allow periodic shutdown check
                try:
                    message = await asyncio.wait_for(self._ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue  # Check _running and retry
                data = json.loads(message)
                self._msg_count += 1
                
                # Log heartbeat every 10 seconds
                import time
                now = time.time()
                if now - self._last_log_time >= 10:
                    logger.info(f"[Heartbeat] Market WS alive, {self._msg_count} msgs total")
                    self._last_log_time = now
                
                # Handle server ping (JSON-based)
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
                            
            except websockets.ConnectionClosed as e:
                logger.warning(f"Market stream connection closed: {e}")
                self._ws = None
                if self._running:
                    continue  # Will reconnect in next iteration
            except Exception as e:
                logger.error(f"Error in market stream: {e}")
                self._ws = None
                if self._running:
                    # Short sleep with shutdown check
                    for _ in range(2):
                        if not self._running:
                            break
                        await asyncio.sleep(0.5)
                    continue
    
    async def close(self):
        """Close the WebSocket connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None


class UserWSClient:
    """WebSocket client for user data stream (orders, positions) with auto-reconnection.
    
    Uses Market Stream endpoint (ws-stream/v1) which supports order/position subscriptions.
    """
    
    # Market Stream endpoint supports order/position subscriptions
    WS_URL = "wss://perps.standx.com/ws-stream/v1"
    RECONNECT_DELAY = 5  # seconds
    
    def __init__(self, auth: StandXAuth):
        self._auth = auth
        self._ws: Optional[WebSocketClientProtocol] = None
        self._running = False
        self._callbacks: dict[str, list[Callable]] = {}
    
    async def connect(self):
        """Connect to user data stream."""
        logger.info(f"Connecting to user stream: {self.WS_URL}")
        self._ws = await websockets.connect(
            self.WS_URL,
            ping_interval=None,  # Server sends ping, we just respond
            ping_timeout=60,     # Long timeout to avoid false disconnects
            close_timeout=10,
        )
        self._running = True
        logger.info("User stream connected")
        
        # Authenticate and subscribe in one message
        await self._authenticate()
    
    async def _authenticate(self):
        """Authenticate and subscribe to order/position channels.
        
        Market Stream uses combined auth+subscribe format:
        { "auth": { "token": "<jwt>", "streams": [{ "channel": "order" }, ...] } }
        """
        if not self._ws or not self._auth.token:
            raise RuntimeError("WebSocket not connected or not authenticated")
        
        # Combined auth + subscribe message (per StandX docs)
        msg = {
            "auth": {
                "token": self._auth.token,
                "streams": [
                    {"channel": "order"},
                    {"channel": "position"}
                ]
            }
        }
        
        await self._ws.send(json.dumps(msg))
        logger.info("User stream auth+subscribe sent")
        
        # Wait for auth response
        response = await self._ws.recv()
        data = json.loads(response)
        
        logger.info(f"Auth response: {data}")
        
        # Market Stream returns: { "seq": 1, "channel": "auth", "data": { "code": 0, "message": "success" } }
        # code: 0 or 200 both indicate success
        if data.get("channel") == "auth":
            auth_data = data.get("data", {})
            code = auth_data.get("code")
            if code not in (0, 200):
                raise RuntimeError(f"User stream auth failed: {data}")
        
        logger.info("User stream authenticated and subscribed to order/position")
    
    async def _reconnect(self):
        """Reconnect and re-authenticate."""
        logger.info(f"Reconnecting user stream in {self.RECONNECT_DELAY} seconds...")
        await asyncio.sleep(self.RECONNECT_DELAY)
        
        try:
            await self.connect()
        except Exception as e:
            logger.error(f"User stream reconnection failed: {e}")
            return False
        
        return True
    
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
        """Run the message receive loop with auto-reconnection."""
        self._running = True
        
        while self._running:
            if not self._ws:
                if not await self._reconnect():
                    continue
            
            try:
                # Use timeout to allow periodic shutdown check
                try:
                    message = await asyncio.wait_for(self._ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue  # Check _running and retry
                data = json.loads(message)
                
                # Handle server ping (JSON-based)
                if data.get("ping"):
                    await self._ws.send(json.dumps({"pong": data["ping"]}))
                    continue
                
                # Dispatch to callbacks based on channel
                channel = data.get("channel")
                
                # Log all received messages to diagnose missing callbacks
                logger.info(f"User stream message: {data}")
                
                if channel in self._callbacks:
                    for callback in self._callbacks[channel]:
                        try:
                            callback(data)
                        except Exception as e:
                            logger.error(f"Callback error: {e}")
                            
            except websockets.ConnectionClosed as e:
                logger.warning(f"User stream connection closed: {e}")
                self._ws = None
                if self._running:
                    continue  # Will reconnect in next iteration
            except Exception as e:
                logger.error(f"Error in user stream: {e}")
                self._ws = None
                if self._running:
                    # Short sleep with shutdown check
                    for _ in range(2):
                        if not self._running:
                            break
                        await asyncio.sleep(0.5)
                    continue
    
    async def close(self):
        """Close the WebSocket connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
