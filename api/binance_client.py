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
    """WebSocket client for Binance Futures market data (bookTicker)."""
    
    WS_URL = "wss://fstream.binance.com/ws"
    
    def __init__(self, symbol: str):
        self.symbol = symbol.lower()
        self._ws: Optional[WebSocketClientProtocol] = None
        self._running = False
        self._callbacks: list[Callable[[float], None]] = []
        self._msg_count = 0
        self._last_log_time = 0
    
    def on_price(self, callback: Callable[[float], None]):
        """Register callback for price updates."""
        self._callbacks.append(callback)
    
    async def run(self):
        """Run the connection loop with auto-reconnection."""
        self._running = True
        logger.info(f"Starting Binance WS for {self.symbol}...")
        
        while self._running:
            try:
                stream_url = f"{self.WS_URL}/{self.symbol}@bookTicker"
                logger.info(f"Connecting to {stream_url}")
                
                async with websockets.connect(stream_url) as ws:
                    self._ws = ws
                    logger.info("Binance WS connected")
                    
                    while self._running:
                        try:
                            message = await ws.recv()
                            data = json.loads(message)
                            self._msg_count += 1
                            
                            # Parse bookTicker: mid price
                            # {
                            #   "e": "bookTicker",
                            #   "s": "BTCUSDT",
                            #   "b": "96000.1",  // bid
                            #   "B": "5.2",      // bidQty
                            #   "a": "96000.2",  // ask
                            #   "A": "2.1",      // askQty
                            #   "T": 123456789,  // transaction time
                            #   "E": 123456789   // event time
                            # }
                            if "b" in data and "a" in data:
                                bid = float(data["b"])
                                ask = float(data["a"])
                                # Use mid price
                                mid_price = (bid + ask) / 2
                                
                                for cb in self._callbacks:
                                    try:
                                        cb(mid_price)
                                    except Exception as e:
                                        logger.error(f"Binance callback error: {e}")
                                        
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
