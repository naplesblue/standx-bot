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
    """WebSocket client for Binance Futures market data (bookTicker and kline)."""
    
    WS_URL = "wss://fstream.binance.com/ws"
    
    def __init__(self, symbol: str, enable_kline: bool = False):
        self.symbol = symbol.lower()
        self.enable_kline = enable_kline
        self._ws: Optional[WebSocketClientProtocol] = None
        self._running = False
        self._callbacks: list[Callable[[float], None]] = []
        self._kline_callbacks: list[Callable[[float], None]] = []
        self._msg_count = 0
        self._last_log_time = 0
    
    def on_price(self, callback: Callable[[float], None]):
        """Register callback for price updates."""
        self._callbacks.append(callback)

    def on_kline(self, callback: Callable[[float], None]):
        """Register callback for closed kline notional volume updates."""
        self._kline_callbacks.append(callback)
    
    async def run(self):
        """Run the connection loop with auto-reconnection."""
        self._running = True
        logger.info(f"Starting Binance WS for {self.symbol}...")
        
        while self._running:
            try:
                if self.enable_kline:
                    stream_url = (
                        f"{self.WS_URL}/stream?streams="
                        f"{self.symbol}@bookTicker/{self.symbol}@kline_1s"
                    )
                else:
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
                            
                            payload = data.get("data") if self.enable_kline else data

                            # Parse bookTicker: mid price
                            if payload and "b" in payload and "a" in payload:
                                bid = float(payload["b"])
                                ask = float(payload["a"])
                                # Use mid price
                                mid_price = (bid + ask) / 2
                                
                                for cb in self._callbacks:
                                    try:
                                        cb(mid_price)
                                    except Exception as e:
                                        logger.error(f"Binance callback error: {e}")

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
