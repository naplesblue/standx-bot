"""State management for StandX Maker Bot.

Maintains:
- Current last_price
- Price window for volatility calculation
- Position
- Open orders (buy/sell)
"""
import time
import logging
from typing import Optional, Dict
from dataclasses import dataclass, field
from threading import Lock


logger = logging.getLogger(__name__)


@dataclass
class OpenOrder:
    """Represents an open order we're tracking."""
    cl_ord_id: str
    side: str
    price: float
    qty: float


@dataclass
class State:
    """Bot state container."""
    
    # Price data
    last_price: Optional[float] = None
    price_window: list = field(default_factory=list)  # [(timestamp, price), ...]
    
    # Position
    position: float = 0.0
    
    # Open orders (one buy, one sell max)
    open_orders: Dict[str, Optional[OpenOrder]] = field(default_factory=lambda: {"buy": None, "sell": None})
    
    # Lock for thread safety
    _lock: Lock = field(default_factory=Lock)
    
    def update_price(self, price: float, window_sec: int = 5):
        """Update price and maintain sliding window."""
        with self._lock:
            now = time.time()
            self.last_price = price
            self.price_window.append((now, price))
            
            # Clean up old data
            cutoff = now - window_sec
            self.price_window = [(t, p) for t, p in self.price_window if t > cutoff]
    
    def get_volatility_bps(self) -> float:
        """
        Calculate volatility in bps over the price window.
        
        Returns:
            Volatility in basis points, or inf if insufficient data
        """
        with self._lock:
            if len(self.price_window) < 2:
                return float("inf")
            
            prices = [p for _, p in self.price_window]
            if prices[-1] == 0:
                return float("inf")
            
            volatility = (max(prices) - min(prices)) / prices[-1] * 10000
            return volatility
    
    def update_position(self, qty: float):
        """Update position quantity."""
        with self._lock:
            self.position = qty
            logger.info(f"Position updated: {qty}")
    
    def set_order(self, side: str, order: Optional[OpenOrder]):
        """Set or clear an open order."""
        with self._lock:
            self.open_orders[side] = order
            if order:
                logger.info(f"Order set: {side} {order.qty} @ {order.price} (cl_ord_id: {order.cl_ord_id})")
            else:
                logger.info(f"Order cleared: {side}")
    
    def get_order(self, side: str) -> Optional[OpenOrder]:
        """Get current order for a side."""
        with self._lock:
            return self.open_orders.get(side)
    
    def has_order(self, side: str) -> bool:
        """Check if we have an order on a side."""
        with self._lock:
            return self.open_orders.get(side) is not None
    
    def clear_all_orders(self):
        """Clear all tracked orders."""
        with self._lock:
            self.open_orders = {"buy": None, "sell": None}
            logger.info("All orders cleared")
    
    def get_orders_to_cancel(self, cancel_distance_bps: float, rebalance_distance_bps: float) -> list[OpenOrder]:
        """
        Get orders that need to be cancelled due to price distance.
        
        Args:
            cancel_distance_bps: Min distance - cancel if closer than this (too close)
            rebalance_distance_bps: Max distance - cancel if farther than this (too far)
            
        Returns:
            List of orders to cancel
        """
        with self._lock:
            if self.last_price is None:
                return []
            
            to_cancel = []
            
            for side, order in self.open_orders.items():
                if order is None:
                    continue
                
                # Calculate distance in bps
                distance_bps = abs(order.price - self.last_price) / self.last_price * 10000
                
                if distance_bps < cancel_distance_bps:
                    logger.warning(
                        f"Order too close: {side} @ {order.price}, "
                        f"last_price={self.last_price}, distance={distance_bps:.2f}bps"
                    )
                    to_cancel.append(order)
                elif distance_bps > rebalance_distance_bps:
                    logger.warning(
                        f"Order too far: {side} @ {order.price}, "
                        f"last_price={self.last_price}, distance={distance_bps:.2f}bps"
                    )
                    to_cancel.append(order)
            
            return to_cancel
