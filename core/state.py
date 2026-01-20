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
    last_dex_price: Optional[float] = None
    last_cex_price: Optional[float] = None
    last_cex_update_time: float = 0.0
    price_window: list = field(default_factory=list)  # [(timestamp, price), ...]
    
    # Position
    position: float = 0.0
    entry_price: float = 0.0
    
    # Execution tracking
    last_fill_time: float = 0.0
    
    # Open orders (one buy, one sell max)
    open_orders: Dict[str, Optional[OpenOrder]] = field(default_factory=lambda: {"buy": None, "sell": None})
    
    # Lock for thread safety
    _lock: Lock = field(default_factory=Lock)
    
    @property
    def last_price(self):
        """Alias for last_dex_price for backward compatibility."""
        return self.last_dex_price

    def update_dex_price(self, price: float):
        """Update DEX price (Anchor for orders)."""
        with self._lock:
            self.last_dex_price = price

    def update_cex_price(self, price: float, window_sec: int = 3600):
        """Update CEX price (Source for Volatility) and maintain sliding window.
        
        Note: We keep a longer history (default 1h) to support both 
        short-term guard (5s) and long-term recovery checks (5m+).
        """
        with self._lock:
            now = time.time()
            self.last_cex_price = price
            self.last_cex_update_time = now
            self.price_window.append((now, price))
            
            # Clean up old data
            cutoff = now - window_sec
            self.price_window = [(t, p) for t, p in self.price_window if t > cutoff]
    
    def get_volatility_bps(self, window_sec: Optional[int] = None) -> float:
        """
        Calculate volatility in bps over the price window.
        
        Args:
            window_sec: Optional window size in seconds. If None, uses all available data.
            
        Returns:
            Volatility in basis points, or 0 if insufficient data
        """
        with self._lock:
            if not self.price_window:
                return 0.0
                
            now = time.time()
            if window_sec:
                cutoff = now - window_sec
                prices = [p for t, p in self.price_window if t > cutoff]
            else:
                prices = [p for _, p in self.price_window]
            
            if len(prices) < 2:
                return 0.0
            
            if prices[-1] == 0:
                return float("inf")
            
            volatility = (max(prices) - min(prices)) / prices[-1] * 10000
            return volatility
    
    def get_cex_amplitude(self, window_sec: int) -> float:
        """
        Calculate Realized Amplitude: (Max - Min) / Mid
        Returns amplitude in BPS.
        """
        with self._lock:
            if not self.price_window:
                return 0.0
            
            now = time.time()
            cutoff = now - window_sec
            prices = [p for t, p in self.price_window if t > cutoff]
            
            if not prices:
                return 0.0
            
            max_p = max(prices)
            min_p = min(prices)
            
            if min_p == 0: 
                return 0.0
                
            mid_p = (max_p + min_p) / 2
            
            if mid_p == 0:
                return 0.0
                
            # Amplitude ratio
            amp = (max_p - min_p) / mid_p
            return amp * 10000 # Convert to bps
            
    def check_cex_velocity(self, window_sec: float, threshold_ticks: int) -> bool:
        """
        Check if price is moving too fast (consecutive ticks in same direction).
        
        Args:
            window_sec: Time window to look back
            threshold_ticks: Number of consecutive same-direction ticks to trigger
            
        Returns:
            True if velocity/trend detected, False otherwise
        """
        with self._lock:
            if len(self.price_window) < threshold_ticks + 1:
                return False
                
            now = time.time()
            cutoff = now - window_sec
            
            # Get recent ticks within window (in reverse order: newest first)
            recent_ticks = [(t, p) for t, p in reversed(self.price_window) if t > cutoff]
            
            if len(recent_ticks) < threshold_ticks + 1:
                return False
            
            # Check consecutive changes
            # We need at least 'threshold_ticks' comparisons (requires threshold_ticks + 1 points)
            target_count = 0
            direction = 0 # 1 for up, -1 for down
            
            # Iterate through recent ticks (newest to oldest)
            for i in range(len(recent_ticks) - 1):
                curr_p = recent_ticks[i][1]
                prev_p = recent_ticks[i+1][1]
                
                diff = curr_p - prev_p
                if diff == 0:
                    continue # Ignore flat ticks? Or counting as 'not directional'? Let's ignore flat.
                
                curr_dir = 1 if diff > 0 else -1
                
                if direction == 0:
                    direction = curr_dir
                    target_count = 1
                elif curr_dir == direction:
                    target_count += 1
                else:
                    # Direction changed, streak broken
                    break
                
                if target_count >= threshold_ticks:
                    return True
                    
            return False
    
    def update_position(self, qty: float, entry_price: float = 0.0):
        """Update position quantity and entry price."""
        with self._lock:
            self.position = qty
            self.entry_price = entry_price
            logger.info(f"Position updated: {qty} @ {entry_price}")
    
    def record_fill(self):
        """Record the time of a fill."""
        with self._lock:
            self.last_fill_time = time.time()
            logger.info(f"Recorded fill at {self.last_fill_time}")
    
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
    
    def get_orders_to_cancel(self, buy_bounds: tuple, sell_bounds: tuple) -> list[OpenOrder]:
        """
        Get orders that need to be cancelled due to price distance.
        
        Args:
            buy_bounds: (min_dist, max_dist) for buy orders
            sell_bounds: (min_dist, max_dist) for sell orders
            
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
                
                # Determine bounds for this side
                if side == "buy":
                    min_dist, max_dist = buy_bounds
                else:
                    min_dist, max_dist = sell_bounds
                
                # Calculate distance in bps
                distance_bps = abs(order.price - self.last_price) / self.last_price * 10000
                
                if distance_bps < min_dist:
                    logger.warning(
                        f"Order too close: {side} @ {order.price}, "
                        f"last_price={self.last_price}, distance={distance_bps:.2f}bps < {min_dist:.2f}bps"
                    )
                    to_cancel.append(order)
                elif distance_bps > max_dist:
                    logger.warning(
                        f"Order too far: {side} @ {order.price}, "
                        f"last_price={self.last_price}, distance={distance_bps:.2f}bps > {max_dist:.2f}bps"
                    )
                    to_cancel.append(order)
            
            return to_cancel
