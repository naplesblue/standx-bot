"""Binance Futures WebSocket client for volatility monitoring."""
import json
import asyncio
import logging
import time
from typing import Optional, Callable

import websockets
from websockets.client import WebSocketClientProtocol

logger = logging.getLogger(__name__)


class BinanceWSClient:
    """WebSocket client for Binance Futures market data (bookTicker, kline, and depth)."""
    
    WS_URL = "wss://fstream.binance.com/ws"
    
    def __init__(self, symbol: str, enable_kline: bool = False, enable_depth: bool = False, depth_levels: int = 10):
        self.symbol = symbol.lower()
        self.enable_kline = enable_kline
        self.enable_depth = enable_depth
        self.depth_levels = min(depth_levels, 20)  # depth20 stream has max 20 levels
        self._ws: Optional[WebSocketClientProtocol] = None
        self._running = False
        self._callbacks: list[Callable[[float], None]] = []
        self._kline_callbacks: list[Callable[[float], None]] = []
        self._depth_callbacks: list[Callable[[float, float, float], None]] = []
        self._msg_count = 0
        self._last_log_time = 0
    
    def on_price(self, callback: Callable[[float], None]):
        """Register callback for price updates."""
        self._callbacks.append(callback)

    def on_kline(self, callback: Callable[[float], None]):
        """Register callback for closed kline notional volume updates."""
        self._kline_callbacks.append(callback)

    def on_depth(self, callback: Callable[[float, float, float], None]):
        """Register callback for orderbook depth imbalance updates.
        
        Args:
            callback(bid_depth, ask_depth, imbalance): 
                - bid_depth: sum of bid quantities
                - ask_depth: sum of ask quantities
                - imbalance: (bid - ask) / (bid + ask), range [-1, 1]
        """
        self._depth_callbacks.append(callback)
    
    async def run(self):
        """Run the connection loop with auto-reconnection."""
        self._running = True
        logger.info(f"Starting Binance WS for {self.symbol}...")
        
        while self._running:
            try:
                # Build stream URL based on enabled features
                streams = [f"{self.symbol}@bookTicker"]
                if self.enable_kline:
                    streams.append(f"{self.symbol}@kline_1s")
                if self.enable_depth:
                    streams.append(f"{self.symbol}@depth20@100ms")
                
                if len(streams) > 1:
                    stream_url = f"{self.WS_URL}/stream?streams={'/'.join(streams)}"
                else:
                    stream_url = f"{self.WS_URL}/{streams[0]}"
                    
                logger.info(f"Connecting to {stream_url}")
                
                async with websockets.connect(stream_url) as ws:
                    self._ws = ws
                    logger.info("Binance WS connected")
                    
                    while self._running:
                        try:
                            message = await ws.recv()
                            data = json.loads(message)
                            self._msg_count += 1
                            
                            # Handle combined stream format
                            if "stream" in data:
                                stream_name = data.get("stream", "")
                                payload = data.get("data", {})
                            else:
                                stream_name = ""
                                payload = data

                            # Parse bookTicker: mid price
                            if payload and "b" in payload and "a" in payload and "e" not in payload:
                                bid = float(payload["b"])
                                ask = float(payload["a"])
                                mid_price = (bid + ask) / 2
                                
                                for cb in self._callbacks:
                                    try:
                                        cb(mid_price)
                                    except Exception as e:
                                        logger.error(f"Binance price callback error: {e}")

                            # Parse kline: closed 1s volume
                            if payload and payload.get("e") == "kline":
                                kline = payload.get("k", {})
                                if kline.get("x"):
                                    quote_vol = float(kline.get("q", 0))
                                    for cb in self._kline_callbacks:
                                        try:
                                            cb(quote_vol)
                                        except Exception as e:
                                            logger.error(f"Binance kline callback error: {e}")

                            # Parse depth20: orderbook imbalance
                            if payload and "bids" in payload and "asks" in payload:
                                bids = payload.get("bids", [])
                                asks = payload.get("asks", [])
                                
                                # Sum quantities up to depth_levels
                                bid_depth = sum(float(qty) for _, qty in bids[:self.depth_levels])
                                ask_depth = sum(float(qty) for _, qty in asks[:self.depth_levels])
                                
                                total = bid_depth + ask_depth
                                imbalance = (bid_depth - ask_depth) / total if total > 0 else 0.0
                                
                                for cb in self._depth_callbacks:
                                    try:
                                        cb(bid_depth, ask_depth, imbalance)
                                    except Exception as e:
                                        logger.error(f"Binance depth callback error: {e}")
                                        
                            # Heartbeat log
                            now = time.time()
                            if now - self._last_log_time >= 30:
                                logger.info(f"[Heartbeat] Binance WS alive, {self._msg_count} msgs")
                                self._last_log_time = now
                                
                        except websockets.ConnectionClosed:
                            logger.warning("Binance WS connection closed")
                            break
                        except Exception as e:
                            logger.error(f"Binance WS error: {e}")
                            break
                            
            except Exception as e:
                logger.error(f"Binance connection failed: {e}")
                
            if self._running:
                logger.info("Reconnecting Binance WS in 5s...")
                await asyncio.sleep(5)
    
    async def close(self):
        """Stop the client."""
        self._running = False
        if self._ws:
            await self._ws.close()
