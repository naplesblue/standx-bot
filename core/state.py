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
from collections import deque


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
    last_dex_update_time: float = 0.0
    last_cex_update_time: float = 0.0
    cex_price_window: deque = field(default_factory=deque)  # [(timestamp, price), ...]
    dex_price_window: deque = field(default_factory=deque)  # [(timestamp, price), ...]
    cex_volume_window: deque = field(default_factory=deque)  # [(timestamp, notional), ...]
    last_cex_volume_update_time: float = 0.0
    
    # Orderbook imbalance data
    imbalance_window: deque = field(default_factory=deque)  # [(timestamp, imbalance), ...]
    last_imbalance: float = 0.0
    last_imbalance_update_time: float = 0.0
    
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

    def update_dex_price(self, price: float, window_sec: int = 3600):
        """Update DEX price (Anchor for orders) and maintain sliding window."""
        with self._lock:
            now = time.time()
            self.last_dex_price = price
            self.last_dex_update_time = now
            self.dex_price_window.append((now, price))

            cutoff = now - window_sec
            while self.dex_price_window and self.dex_price_window[0][0] <= cutoff:
                self.dex_price_window.popleft()

    def update_cex_price(self, price: float, window_sec: int = 3600):
        """Update CEX price (Source for Volatility) and maintain sliding window.
        
        Note: We keep a longer history (default 1h) to support both 
        short-term guard (5s) and long-term recovery checks (5m+).
        """
        with self._lock:
            now = time.time()
            self.last_cex_price = price
            self.last_cex_update_time = now
            self.cex_price_window.append((now, price))
            
            # Clean up old data using efficient deque popleft
            cutoff = now - window_sec
            while self.cex_price_window and self.cex_price_window[0][0] <= cutoff:
                self.cex_price_window.popleft()

    def update_cex_volume(self, notional: float, window_sec: int = 3600):
        """Update CEX notional volume (1s kline) and maintain sliding window."""
        with self._lock:
            now = time.time()
            self.last_cex_volume_update_time = now
            self.cex_volume_window.append((now, notional))

            cutoff = now - window_sec
            while self.cex_volume_window and self.cex_volume_window[0][0] <= cutoff:
                self.cex_volume_window.popleft()

    def get_cex_volume_ratio(self, window_sec: int, min_samples: int) -> tuple[float, float, float, int]:
        """
        Return volume ratio vs baseline: (ratio, current, average, sample_count).
        Ratio is computed against the average of the baseline window excluding current.
        """
        with self._lock:
            if not self.cex_volume_window:
                return 0.0, 0.0, 0.0, 0

            now = time.time()
            cutoff = now - window_sec
            
            # Note: iter(deque) is efficient, converting to list for slicing/math is acceptable 
            # as long as we don't rebuild the whole list for pruning.
            samples = [v for t, v in self.cex_volume_window if t > cutoff]

            if len(samples) < min_samples + 1:
                return 0.0, 0.0, 0.0, len(samples)

            current = samples[-1]
            baseline = samples[:-1]
            avg = sum(baseline) / len(baseline) if baseline else 0.0
            if avg <= 0:
                return 0.0, current, avg, len(baseline)

            ratio = current / avg
            return ratio, current, avg, len(baseline)

    def update_imbalance(self, bid_depth: float, ask_depth: float, window_sec: int = 10):
        """Update orderbook imbalance data and maintain sliding window.
        
        Args:
            bid_depth: Sum of bid quantities
            ask_depth: Sum of ask quantities
            window_sec: Time window to keep history
        """
        with self._lock:
            now = time.time()
            total = bid_depth + ask_depth
            imbalance = (bid_depth - ask_depth) / total if total > 0 else 0.0
            
            self.last_imbalance = imbalance
            self.last_imbalance_update_time = now
            self.imbalance_window.append((now, imbalance))
            
            cutoff = now - window_sec
            while self.imbalance_window and self.imbalance_window[0][0] <= cutoff:
                self.imbalance_window.popleft()

    def get_imbalance_signal(self, window_sec: int, threshold: float) -> int:
        """Detect sustained imbalance direction in orderbook.
        
        Args:
            window_sec: Time window to analyze
            threshold: Minimum average imbalance magnitude to trigger signal
            
        Returns:
            1: Sustained buy pressure (bid > ask), price likely to rise
            -1: Sustained sell pressure (ask > bid), price likely to fall
            0: No clear signal or insufficient data
        """
        with self._lock:
            if not self.imbalance_window:
                return 0
            
            now = time.time()
            cutoff = now - window_sec
            recent = [v for t, v in self.imbalance_window if t > cutoff]
            
            if len(recent) < 3:  # Need at least 3 samples
                return 0
            
            avg_imbalance = sum(recent) / len(recent)
            
            if avg_imbalance > threshold:
                return 1  # Buy pressure
            elif avg_imbalance < -threshold:
                return -1  # Sell pressure
            return 0

    def _get_window(self, source: str):
        if source == "cex":
            return self.cex_price_window
        if source == "dex":
            return self.dex_price_window
        if self.cex_price_window:
            return self.cex_price_window
        return self.dex_price_window

    def get_volatility_bps(self, window_sec: Optional[int] = None, source: str = "auto") -> float:
        """
        Calculate volatility in bps over the price window.
        
        Args:
            window_sec: Optional window size in seconds. If None, uses all available data.
            
        Returns:
            Volatility in basis points, or 0 if insufficient data
        """
        with self._lock:
            window = self._get_window(source)
            if not window:
                return 0.0
                
            now = time.time()
            if window_sec:
                cutoff = now - window_sec
                prices = [p for t, p in window if t > cutoff]
            else:
                prices = [p for _, p in window]
            
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
            if not self.cex_price_window:
                return 0.0
            
            now = time.time()
            cutoff = now - window_sec
            prices = [p for t, p in self.cex_price_window if t > cutoff]
            
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
            direction = self._get_consecutive_direction(self.cex_price_window, window_sec, threshold_ticks)
            return direction != 0

    def get_trend_direction(self, window_sec: float, threshold_ticks: int, source: str = "auto") -> int:
        """
        Return trend direction based on consecutive ticks.
        1 for up, -1 for down, 0 for no clear trend.
        """
        with self._lock:
            window = self._get_window(source)
            return self._get_consecutive_direction(window, window_sec, threshold_ticks)

    def _get_consecutive_direction(self, window: list, window_sec: float, threshold_ticks: int) -> int:
        if len(window) < threshold_ticks + 1:
            return 0

        now = time.time()
        cutoff = now - window_sec

        # Get recent ticks within window (in reverse order: newest first)
        recent_ticks = [(t, p) for t, p in reversed(window) if t > cutoff]

        if len(recent_ticks) < threshold_ticks + 1:
            return 0

        target_count = 0
        direction = 0  # 1 for up, -1 for down

        for i in range(len(recent_ticks) - 1):
            curr_p = recent_ticks[i][1]
            prev_p = recent_ticks[i + 1][1]

            diff = curr_p - prev_p
            if diff == 0:
                continue

            curr_dir = 1 if diff > 0 else -1

            if direction == 0:
                direction = curr_dir
                target_count = 1
            elif curr_dir == direction:
                target_count += 1
            else:
                break

            if target_count >= threshold_ticks:
                return direction

        return 0
    
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

    def update_order_qty(self, side: str, qty: float):
        """Update open order quantity."""
        with self._lock:
            order = self.open_orders.get(side)
            if order:
                order.qty = qty
                logger.info(f"Order qty updated: {side} {qty}")
    
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
    
    def get_orders_to_cancel(self, buy_bounds: tuple, sell_bounds: tuple) -> dict:
        """
        Get orders that need to be cancelled due to price distance.
        
        Args:
            buy_bounds: (min_dist, max_dist) for buy orders
            sell_bounds: (min_dist, max_dist) for sell orders
            
        Returns:
            dict with:
              - 'orders': List of orders to cancel
              - 'cex_triggered_sides': List of sides cancelled due to CEX danger
        """
        with self._lock:
            if self.last_dex_price is None:
                return {'orders': [], 'cex_triggered_sides': []}
            
            to_cancel = []
            cex_triggered_sides = []
            
            for side, order in self.open_orders.items():
                if order is None:
                    continue
                
                # Determine bounds for this side
                if side == "buy":
                    min_dist, max_dist = buy_bounds
                else:
                    min_dist, max_dist = sell_bounds
                
                # Calculate distance from DEX price (primary reference for order placement)
                dex_distance_bps = abs(order.price - self.last_dex_price) / self.last_dex_price * 10000
                
                # CEX check: only trigger cancel when CEX HAS CROSSED or is ABOUT TO CROSS the order
                # Use a tight threshold (2 bps) to avoid false positives from normal DEX/CEX spread
                CEX_DANGER_THRESHOLD_BPS = 2.0  # Only panic if CEX is within 2 bps of order
                cex_in_danger = False
                if self.last_cex_price and self.last_cex_price > 0:
                    if side == "buy":
                        # Buy order danger: CEX price has fallen to within 2 bps of order or below
                        cex_to_order = self.last_cex_price - order.price
                        cex_to_order_bps = cex_to_order / self.last_cex_price * 10000
                        if cex_to_order_bps < CEX_DANGER_THRESHOLD_BPS:
                            cex_in_danger = True
                            logger.warning(
                                f"CEX CROSSED (buy): CEX={self.last_cex_price:.2f} at/below order={order.price:.2f}, "
                                f"gap={cex_to_order_bps:.2f}bps"
                            )
                    else:  # sell
                        # Sell order danger: CEX price has risen to within 2 bps of order or above
                        cex_to_order = order.price - self.last_cex_price
                        cex_to_order_bps = cex_to_order / self.last_cex_price * 10000
                        if cex_to_order_bps < CEX_DANGER_THRESHOLD_BPS:
                            cex_in_danger = True
                            logger.warning(
                                f"CEX CROSSED (sell): CEX={self.last_cex_price:.2f} at/above order={order.price:.2f}, "
                                f"gap={cex_to_order_bps:.2f}bps"
                            )
                
                # Decision: cancel if DEX says too close OR CEX is in danger zone
                if dex_distance_bps < min_dist:
                    logger.warning(
                        f"Order too close (DEX): {side} @ {order.price:.2f}, "
                        f"dex={self.last_dex_price:.2f}, distance={dex_distance_bps:.2f}bps < {min_dist:.2f}bps"
                    )
                    to_cancel.append(order)
                elif cex_in_danger:
                    # CEX triggered danger already logged above
                    to_cancel.append(order)
                    cex_triggered_sides.append(side)
                elif dex_distance_bps > max_dist:
                    logger.warning(
                        f"Order too far (DEX): {side} @ {order.price:.2f}, "
                        f"dex={self.last_dex_price:.2f}, distance={dex_distance_bps:.2f}bps > {max_dist:.2f}bps"
                    )
                    to_cancel.append(order)
            
            return {'orders': to_cancel, 'cex_triggered_sides': cex_triggered_sides}


