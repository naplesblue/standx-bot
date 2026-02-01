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
                
                # Debug log for received messages
                logger.debug(f"User stream message: channel={channel}")
                
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


class TradingWSClient:
    """
    WebSocket client for trading operations via ws-api/v1.
    
    Provides order:new and order:cancel methods with request_id tracking.
    Supports timeout and HTTP fallback on failure.
    """
    
    WS_URL = "wss://perps.standx.com/ws-api/v1"
    RECONNECT_DELAY = 3
    REQUEST_TIMEOUT = 5.0  # seconds
    
    def __init__(self, auth: StandXAuth, http_client=None):
        self._auth = auth
        self._http_client = http_client  # HTTP fallback
        self._ws: Optional[WebSocketClientProtocol] = None
        self._running = False
        self._session_id = str(__import__('uuid').uuid4())
        
        # Request tracking: request_id -> Future
        self._pending_requests: dict = {}
        
        # Message count for heartbeat
        self._msg_count = 0
        self._last_heartbeat = 0
    
    async def connect(self):
        """Connect to trading WS and authenticate."""
        logger.info(f"Connecting to {self.WS_URL}")
        self._ws = await websockets.connect(
            self.WS_URL,
            # Server sends pings every 10s. Disable client pings to avoid "keepalive ping timeout"
            # if server doesn't respond to client pings.
            ping_interval=None,
            close_timeout=5,
        )
        logger.info("Trading WS connected")
        await self._authenticate()
    
    async def _authenticate(self):
        """Authenticate with auth:login method."""
        request_id = str(__import__('uuid').uuid4())
        
        msg = {
            "session_id": self._session_id,
            "request_id": request_id,
            "method": "auth:login",
            "params": __import__('json').dumps({"token": self._auth.token})
        }
        
        await self._ws.send(__import__('json').dumps(msg))
        logger.info("Trading WS auth sent")
        
        # Wait for auth response
        try:
            response = await asyncio.wait_for(self._ws.recv(), timeout=5.0)
            data = __import__('json').loads(response)
            if data.get("code") not in (0, 200):
                raise RuntimeError(f"Trading WS auth failed: {data}")
            logger.info("Trading WS authenticated")
        except asyncio.TimeoutError:
            raise RuntimeError("Trading WS auth timeout")
    
    async def new_order(
        self,
        symbol: str,
        side: str,
        qty: str,
        price: str,
        cl_ord_id: str,
        order_type: str = "limit",
        time_in_force: str = "gtc",
        reduce_only: bool = False,
    ) -> dict:
        """
        Place a new order via WebSocket.
        
        Falls back to HTTP if WS fails.
        """
        params = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "cl_ord_id": cl_ord_id,
            "order_type": order_type,
            "time_in_force": time_in_force,
            "reduce_only": reduce_only,
        }
        
        try:
            return await self._send_order_request("order:new", params)
        except Exception as e:
            logger.warning(f"WS order:new failed, falling back to HTTP: {e}")
            if self._http_client:
                return await self._http_client.new_order(
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    price=price,
                    cl_ord_id=cl_ord_id,
                    order_type=order_type,
                    time_in_force=time_in_force,
                    reduce_only=reduce_only,
                )
            raise
    
    async def cancel_order(self, cl_ord_id: str) -> dict:
        """
        Cancel an order via WebSocket.
        
        Falls back to HTTP if WS fails.
        """
        params = {"cl_ord_id": cl_ord_id}
        
        try:
            return await self._send_order_request("order:cancel", params)
        except Exception as e:
            logger.warning(f"WS order:cancel failed, falling back to HTTP: {e}")
            if self._http_client:
                return await self._http_client.cancel_order(cl_ord_id)
            raise
    
    async def _send_order_request(self, method: str, params: dict) -> dict:
        """Send an order request and wait for response."""
        # Check connection (compatible with different websockets versions)
        ws_valid = False
        if self._ws:
            try:
                ws_valid = getattr(self._ws, 'open', True) and not getattr(self._ws, 'closed', False)
            except:
                ws_valid = False
        
        if not ws_valid:
            raise RuntimeError("Trading WS not connected")
        
        request_id = str(__import__('uuid').uuid4())
        
        # Sign the request
        params_json = __import__('json').dumps(params)
        sig_headers = self._auth.sign_request(params_json)
        
        msg = {
            "session_id": self._session_id,
            "request_id": request_id,
            "method": method,
            "header": {
                "x-request-id": sig_headers["x-request-id"],
                "x-request-timestamp": sig_headers["x-request-timestamp"],
                "x-request-signature": sig_headers["x-request-signature"],
            },
            "params": params_json,
        }
        
        # Create a Future for this request
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending_requests[request_id] = future
        
        try:
            await self._ws.send(__import__('json').dumps(msg))
            logger.debug(f"Trading WS sent {method}: {request_id}")
            
            # Wait for response with timeout
            response = await asyncio.wait_for(future, timeout=self.REQUEST_TIMEOUT)
            return response
        except asyncio.TimeoutError:
            logger.error(f"Trading WS request timeout: {method} {request_id}")
            raise
        finally:
            self._pending_requests.pop(request_id, None)
    
    async def run(self):
        """Run the message receive loop with auto-reconnection."""
        self._running = True
        
        while self._running:
            try:
                # Check if connection is valid (compatible with different websockets versions)
                ws_closed = False
                if not self._ws:
                    ws_closed = True
                else:
                    try:
                        # Try different ways to check connection state
                        ws_closed = getattr(self._ws, 'closed', None) or not self._ws.open
                    except AttributeError:
                        # Fallback: try to check state
                        try:
                            from websockets.protocol import State
                            ws_closed = self._ws.state != State.OPEN
                        except:
                            ws_closed = True
                
                if ws_closed:
                    try:
                        await self.connect()
                    except Exception as e:
                        logger.error(f"Trading WS connection failed: {e}")
                        await asyncio.sleep(self.RECONNECT_DELAY)
                        continue
                
                # Receive and dispatch messages
                try:
                    raw = await asyncio.wait_for(self._ws.recv(), timeout=1.0)
                    self._msg_count += 1
                    
                    data = __import__('json').loads(raw)
                    request_id = data.get("request_id")
                    
                    # Resolve pending request
                    if request_id and request_id in self._pending_requests:
                        future = self._pending_requests[request_id]
                        if not future.done():
                            future.set_result(data)
                    
                    # Log heartbeat periodically
                    now = __import__('time').time()
                    if now - self._last_heartbeat > 30:
                        logger.info(f"[Heartbeat] Trading WS alive, {self._msg_count} msgs")
                        self._last_heartbeat = now
                        
                except asyncio.TimeoutError:
                    continue
                except websockets.ConnectionClosed as e:
                    logger.warning(f"Trading WS connection closed: {e}")
                    self._ws = None
                    
            except Exception as e:
                logger.error(f"Trading WS error: {e}")
                self._ws = None
                if self._running:
                    await asyncio.sleep(self.RECONNECT_DELAY)
    
    async def close(self):
        """Close the WebSocket connection."""
        self._running = False
        # Fail all pending requests
        for request_id, future in self._pending_requests.items():
            if not future.done():
                future.set_exception(RuntimeError("Connection closed"))
        self._pending_requests.clear()
        
        if self._ws:
            await self._ws.close()
            self._ws = None
