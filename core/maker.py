"""Market making logic for StandX Maker Bot.

Implements the main loop:
1. Check position - stop if too large
2. Check and cancel orders that are too close to price
3. Check volatility - wait if too high
4. Place missing buy/sell orders
"""
import uuid
import logging
import asyncio
from typing import Optional

from config import Config
from api.http_client import StandXHTTPClient
from core.state import State, OpenOrder


logger = logging.getLogger(__name__)


class Maker:
    """Market making logic."""
    
    def __init__(self, config: Config, client: StandXHTTPClient, state: State):
        self.config = config
        self.client = client
        self.state = state
        self._running = False
    
    async def initialize(self):
        """Initialize state from exchange."""
        logger.info("Initializing state from exchange...")
        
        # Get current position
        positions = await self.client.query_positions(self.config.symbol)
        if positions:
            self.state.update_position(positions[0].qty)
        else:
            self.state.update_position(0.0)
        
        # Get current open orders
        orders = await self.client.query_open_orders(self.config.symbol)
        
        for order in orders:
            if order.side == "buy":
                self.state.set_order("buy", OpenOrder(
                    cl_ord_id=order.cl_ord_id,
                    side="buy",
                    price=float(order.price),
                    qty=float(order.qty),
                ))
            elif order.side == "sell":
                self.state.set_order("sell", OpenOrder(
                    cl_ord_id=order.cl_ord_id,
                    side="sell",
                    price=float(order.price),
                    qty=float(order.qty),
                ))
        
        logger.info(
            f"Initialized: position={self.state.position}, "
            f"buy_order={self.state.has_order('buy')}, "
            f"sell_order={self.state.has_order('sell')}"
        )
    
    async def run(self):
        """Run the main maker loop."""
        self._running = True
        logger.info("Maker loop started")
        
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"Maker tick error: {e}", exc_info=True)
            
            await asyncio.sleep(self.config.loop_interval_sec)
        
        logger.info("Maker loop stopped")
    
    async def stop(self):
        """Stop the maker loop."""
        self._running = False
    
    async def _tick(self):
        """Single iteration of the maker loop."""
        # Wait for price data
        if self.state.last_price is None:
            logger.debug("Waiting for price data...")
            return
        
        # Step 1: Check position
        if abs(self.state.position) >= self.config.max_position_btc:
            logger.warning(
                f"Position too large: {self.state.position} >= {self.config.max_position_btc}, "
                "pausing market making"
            )
            return
        
        # Step 2: Check and cancel orders that are too close
        orders_to_cancel = self.state.get_orders_to_cancel(self.config.cancel_distance_bps)
        
        if orders_to_cancel:
            cl_ord_ids = [o.cl_ord_id for o in orders_to_cancel]
            logger.info(f"Cancelling {len(cl_ord_ids)} orders: {cl_ord_ids}")
            
            try:
                await self.client.cancel_orders(cl_ord_ids)
                
                # Clear cancelled orders from state
                for order in orders_to_cancel:
                    self.state.set_order(order.side, None)
                
            except Exception as e:
                logger.error(f"Failed to cancel orders: {e}")
            
            # Don't place new orders this tick
            return
        
        # Step 3: Check volatility
        volatility = self.state.get_volatility_bps()
        if volatility > self.config.volatility_threshold_bps:
            logger.debug(
                f"Volatility too high: {volatility:.2f}bps > {self.config.volatility_threshold_bps}bps"
            )
            return
        
        # Step 4: Place missing orders
        await self._place_missing_orders()
    
    async def _place_missing_orders(self):
        """Place buy and sell orders if missing."""
        last_price = self.state.last_price
        if last_price is None:
            return
        
        # Calculate order prices
        buy_price = last_price * (1 - self.config.order_distance_bps / 10000)
        sell_price = last_price * (1 + self.config.order_distance_bps / 10000)
        
        # Place buy order if missing
        if not self.state.has_order("buy"):
            await self._place_order("buy", buy_price)
        
        # Place sell order if missing
        if not self.state.has_order("sell"):
            await self._place_order("sell", sell_price)
    
    async def _place_order(self, side: str, price: float):
        """Place a single order."""
        cl_ord_id = f"mm-{side}-{uuid.uuid4().hex[:8]}"
        
        # Format price and qty
        price_str = f"{price:.2f}"
        qty_str = f"{self.config.order_size_btc:.3f}"
        
        logger.info(f"Placing {side} order: {qty_str} @ {price_str} (cl_ord_id: {cl_ord_id})")
        
        try:
            response = await self.client.new_order(
                symbol=self.config.symbol,
                side=side,
                qty=qty_str,
                price=price_str,
                cl_ord_id=cl_ord_id,
            )
            
            if response.get("code") == 0:
                # Update local state
                self.state.set_order(side, OpenOrder(
                    cl_ord_id=cl_ord_id,
                    side=side,
                    price=price,
                    qty=self.config.order_size_btc,
                ))
                logger.info(f"Order placed successfully: {cl_ord_id}")
            else:
                logger.error(f"Order failed: {response}")
                
        except Exception as e:
            logger.error(f"Failed to place {side} order: {e}")
