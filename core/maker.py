"""Market making logic for StandX Maker Bot.

Event-driven design:
- Price updates trigger order checks
- Order placement runs when conditions are met
"""
import uuid
import logging
import asyncio
from typing import Optional

import requests

from config import Config
from core.state import State, OpenOrder
from core.monitor import EfficiencyMonitor


logger = logging.getLogger(__name__)


def send_notify(title: str, message: str, priority: str = "normal"):
    """Send notification via Telegram.
    
    Requires environment variables:
        NOTIFY_URL: Notification service URL
        NOTIFY_API_KEY: API key for the notification service
    """
    import os
    notify_url = os.environ.get("NOTIFY_URL", "")
    notify_api_key = os.environ.get("NOTIFY_API_KEY", "")
    
    if not notify_url:
        return  # Notification not configured
    
    try:
        headers = {}
        if notify_api_key:
            headers["X-API-Key"] = notify_api_key
        
        requests.post(
            notify_url,
            json={"title": title, "message": message, "channel": "alert", "priority": priority},
            headers=headers,
            timeout=5,
        )
    except:
        pass  # Don't let notification failure affect trading


class Maker:
    """Market making logic."""
    
    def __init__(self, config: Config, client: StandXHTTPClient, state: State):
        self.config = config
        self.client = client
        self.state = state
        self._running = False
        self._pending_check = asyncio.Event()
        self._reduce_log_file = None  # Will be set by main.py
        
        # Recovery mode state
        self._stop_loss_active = False
        self._next_recovery_check = 0.0

        # Spread Guard state
        self._last_spread_warn_time = 0.0
        
        # Performance Monitor
        self.monitor = EfficiencyMonitor()
        self._last_tick_time = 0.0
    
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
    
    
    def on_price_update(self, price: float):
        """
        Called when StandX price updates.
        Updates Anchor Price for orders.
        """
        self.state.update_dex_price(price)
        
        # Signal check
        self._pending_check.set()

    
    def on_cex_price_update(self, price: float):
        """
        Called when Binance price updates.
        Updates Volatility window and signals check.
        """
        # Keep 1h history to support Recovery Mode (5m window)
        self.state.update_cex_price(price, window_sec=3600)
        
        # Signal check (high volatility should trigger immediate reaction)
        self._pending_check.set()
    
    async def run(self):
        """Run the event-driven maker loop."""
        self._running = True
        logger.info("Maker started (event-driven mode)")
        
        while self._running:
            try:
                # Wait for price update signal (with timeout for periodic checks)
                try:
                    await asyncio.wait_for(self._pending_check.wait(), timeout=5.0)
                    self._pending_check.clear()
                except asyncio.TimeoutError:
                    # Periodic check even without price updates
                    pass
                
                await self._tick()
                
            except Exception as e:
                logger.error(f"Maker tick error: {e}", exc_info=True)
                await asyncio.sleep(1)  # Brief pause on error
        
        logger.info("Maker stopped")
    
    async def stop(self):
        """Stop the maker loop."""
        self._running = False
        self._pending_check.set()  # Wake up the loop
    
    async def _tick(self):
        """Single iteration of the maker logic."""
        import time
        now = time.time()
        if self._last_tick_time > 0:
            dt = now - self._last_tick_time
        else:
            dt = 0
        self._last_tick_time = now

        # Wait for price data
        # Wait for price data
        if self.state.last_dex_price is None:
            logger.debug("Waiting for DEX price data...")
            return

        # Step -3: Check Binance Staleness (If configured)
        if self.config.binance_symbol:
            import time
            time_since_cex = time.time() - self.state.last_cex_update_time
            if time_since_cex > self.config.binance_staleness_sec:
                 logger.warning(
                     f"Binance Data Stale: {time_since_cex:.1f}s > {self.config.binance_staleness_sec}s. "
                     "Cancelling orders and pausing..."
                 )
                 # Cancel all orders
                 try:
                    orders_to_cancel = []
                    if self.state.has_order("buy"):
                         orders_to_cancel.append(self.state.get_order("buy").cl_ord_id)
                    if self.state.has_order("sell"):
                         orders_to_cancel.append(self.state.get_order("sell").cl_ord_id)
                     
                    if orders_to_cancel:
                         await self.client.cancel_orders(orders_to_cancel)
                         self.state.clear_all_orders()
                         for _ in orders_to_cancel: self.monitor.record_cancel()
                 except Exception as e:
                     logger.error(f"StalenessGuard: Failed to cancel orders: {e}")
                 
                 return

        # Step -2: Check Recovery Mode
        if self._stop_loss_active:
            import time
            now = time.time()
            
            if now < self._next_recovery_check:
                # Still in cooldown/wait period
                logger.debug(f"Recovery mode active. Waiting... ({self._next_recovery_check - now:.0f}s left)")
                await asyncio.sleep(5) # Sleep to avoid busy loop logs
                return
            
            # Check stability
            # We use the configured recovery window (e.g. 5 mins)
            volatility = self.state.get_volatility_bps(window_sec=self.config.recovery_window_sec)
            
            if volatility > self.config.recovery_volatility_bps:
                logger.warning(
                    f"Recovery Check: Market still volatile ({volatility:.2f}bps > {self.config.recovery_volatility_bps}bps). "
                    f"Waiting another {self.config.recovery_check_interval_sec}s..."
                )
                self._next_recovery_check = now + self.config.recovery_check_interval_sec
                return
            else:
                logger.info(
                    f"Recovery Check: Market stabilized ({volatility:.2f}bps <= {self.config.recovery_volatility_bps}bps). "
                    "Resuming trading..."
                )
                self._stop_loss_active = False
                send_notify(
                    "行情恢复平稳",
                    f"波动率 {volatility:.2f}bps，开始恢复挂单。",
                    priority="normal"
                )
        
        # Step -1.5: Spread Guard (CEX vs DEX Deviation)
        # Only check if active (have both prices)
        if self.config.binance_symbol and self.state.last_cex_price and self.state.last_dex_price:
            import time
            dex_price = self.state.last_dex_price
            cex_price = self.state.last_cex_price
            
            if dex_price > 0:
                spread_bps = abs(cex_price - dex_price) / dex_price * 10000
                now = time.time()
                
                # Check 1: Trigger Guard
                if spread_bps > self.config.spread_threshold_bps:
                    # Reset recovery timer
                    self._spread_stable_start_time = None
                    
                    if not self._spread_guard_active:
                        logger.warning(
                            f"Spread Guard TRIGGERED: Spread {spread_bps:.1f}bps > {self.config.spread_threshold_bps}bps. "
                            f"Prices: Binance={cex_price:.2f}, StandX={dex_price:.2f}. "
                            "Cancelling orders and pausing..."
                        )
                        self._spread_guard_active = True
                        # Cancel orders immediately
                        try:
                            # Reuse cancellation logic - move to helper method potentially in future
                            orders_to_cancel = []
                            if self.state.has_order("buy"): orders_to_cancel.append(self.state.get_order("buy").cl_ord_id)
                            if self.state.has_order("sell"): orders_to_cancel.append(self.state.get_order("sell").cl_ord_id)
                            if orders_to_cancel:
                                await self.client.cancel_orders(orders_to_cancel)
                                self.state.clear_all_orders()
                                for _ in orders_to_cancel: self.monitor.record_cancel()
                        except Exception as e:
                            logger.error(f"SpreadGuard: Failed to cancel orders: {e}")
                    else:
                        # Log periodically
                        if now - self._last_spread_warn_time > 10:
                             logger.warning(f"Spread Guard Active: Spread {spread_bps:.1f}bps")
                             self._last_spread_warn_time = now
                    
                    return # Pause
                
                # Check 2: Recovery Logic (Only if guard is active)
                if self._spread_guard_active:
                    if spread_bps < self.config.spread_recovery_bps:
                        if self._spread_stable_start_time is None:
                            self._spread_stable_start_time = now
                            logger.info(f"Spread stabilizing ({spread_bps:.1f}bps)... waiting for {self.config.spread_recovery_sec}s")
                        
                        stable_duration = now - self._spread_stable_start_time
                        if stable_duration >= self.config.spread_recovery_sec:
                            logger.info(f"Spread Stabilized ({spread_bps:.1f}bps for {stable_duration:.1f}s). Resuming...")
                            self._spread_guard_active = False
                            self._spread_stable_start_time = None
                        else:
                            return # Still waiting for timer
                            
                    else:
                        # Spread is between recovery and threshold, OR jumped back up
                        # If it jumped up > threshold, it's handled above.
                        # If it is between (e.g. 15bps, threshold 20, recovery 10), we are NOT stable.
                        if self._spread_stable_start_time is not None:
                            logger.info(f"Spread unstable again ({spread_bps:.1f}bps). Resetting timer.")
                            self._spread_stable_start_time = None
                        
                        return # Stay allowed to pause
        
        # Step -1: Check volatility guard (Legacy removed)
        # Replaced by Spread Guard and Staleness Guard
        pass
        
        # Update Efficiency Stats
        if self.state.last_dex_price:
            buy_price = None
            sell_price = None
            if self.state.has_order("buy"):
                buy_price = self.state.get_order("buy").price
            if self.state.has_order("sell"):
                sell_price = self.state.get_order("sell").price
            
            self.monitor.update(self.state.last_dex_price, buy_price, sell_price, dt)
            
            if self.monitor.should_report(300): # 5 minutes
                # Use dedicated logger for efficiency reports
                logging.getLogger("standx.efficiency").info(self.monitor.get_report())

        # Step -2: Check cool-down
        import time
        time_since_fill = time.time() - self.state.last_fill_time
        if time_since_fill < self.config.fill_cooldown_sec:
           logger.debug(f"Cool-down active: {time_since_fill:.1f}s < {self.config.fill_cooldown_sec}s")
           return
        
        # Step 0: Check stop loss
        stop_triggered = await self._check_stop_loss()
        if stop_triggered:
            return  # Stop everything if stop loss triggers
        
        # Step 1: Check if should reduce position (> 50% and profitable)
        # We do this BEFORE max position check to allow exiting even if full
        reduced = await self._check_and_reduce_position()
        if reduced:
            return  # Skip this tick after reducing
        
        # Step 2: Check position limit
        if abs(self.state.position) >= self.config.max_position_btc:
            logger.warning(
                f"Position too large: {self.state.position} >= {self.config.max_position_btc}, "
                "pausing market making"
            )
            return
        
        if reduced:
            return  # Skip this tick after reducing
        
        # Step 2: Calculate skew and targets
        skew_bps = self._get_skew_bps()
        
        # Buy target: increase distance if skew > 0 (long), decrease if skew < 0 (short)
        buy_target = max(0, self.config.order_distance_bps + skew_bps)
        
        # Sell target: decrease distance if skew > 0 (long), increase if skew < 0 (short)
        sell_target = max(0, self.config.order_distance_bps - skew_bps)
        
        # Calculate tolerant bounds
        # Lower bound: target - (order - cancel) => target - tolerance
        tolerance_lower = max(1, self.config.order_distance_bps - self.config.cancel_distance_bps)
        # Upper bound: target + (rebalance - order) => target + tolerance
        tolerance_upper = max(1, self.config.rebalance_distance_bps - self.config.order_distance_bps)
        
        buy_bounds = (max(0, buy_target - tolerance_lower), buy_target + tolerance_upper)
        sell_bounds = (max(0, sell_target - tolerance_lower), sell_target + tolerance_upper)
        
        if abs(skew_bps) > 1:
            logger.debug(
                f"Skew: {skew_bps:.1f}bps | "
                f"Buy T:{buy_target:.1f} [{buy_bounds[0]:.1f}, {buy_bounds[1]:.1f}] | "
                f"Sell T:{sell_target:.1f} [{sell_bounds[0]:.1f}, {sell_bounds[1]:.1f}]"
            )
        
        # Step 3: Check and cancel orders
        orders_to_cancel = self.state.get_orders_to_cancel(buy_bounds, sell_bounds)
        
        if orders_to_cancel:
            for order in orders_to_cancel:
                logger.info(f"Cancelling order: {order.cl_ord_id}")
                try:
                    await self.client.cancel_order(order.cl_ord_id)
                    self.state.set_order(order.side, None)
                    self.monitor.record_cancel()
                except Exception as e:
                    logger.error(f"Failed to cancel order {order.cl_ord_id}: {e}")
                    send_notify(
                        "StandX 撤单失败",
                        f"{self.config.symbol} 撤单失败: {e}",
                        priority="high"
                    )
            
            # Don't place new orders this tick
            return
        
        # Step 4: Check volatility (redundant with guard but kept for logging/metrics if needed)
        # We already handled critical volatility at the start of _tick
        pass
        
        # Step 5: Place missing orders
        await self._place_missing_orders(buy_target, sell_target)
    
    def _get_skew_bps(self) -> float:
        """Calculate inventory skew in bps."""
        if self.config.max_skew_bps <= 0 or self.config.max_position_btc <= 0:
            return 0.0
        
        ratio = self.state.position / self.config.max_position_btc
        # Clamp ratio to [-1, 1] just in case
        ratio = max(-1.0, min(1.0, ratio))
        
        return ratio * self.config.max_skew_bps
    
    async def _place_missing_orders(self, buy_target_bps: float, sell_target_bps: float):
        """Place buy and sell orders if missing."""
        last_price = self.state.last_price
        if last_price is None:
            return
        
        # Define targets
        buy_target_price = last_price * (1 - buy_target_bps / 10000)
        sell_target_price = last_price * (1 + sell_target_bps / 10000)
        
        # Override with Maker Exit Logic if we have a position
        # If we have a position, we want to close it with a Limit Order at Entry + Fee + Profit
        position_qty = self.state.position
        entry_price = self.state.entry_price
        
        if entry_price > 0 and position_qty != 0:
            # Calculate break-even exit price including taker fee (for safety comparison) and maker rebate benefit
            # Taker Fee Rate: self.config.taker_fee_rate (e.g. 0.0004)
            # Min Profit: self.config.min_profit_bps (e.g. 2 bps)
            
            required_margin = self.config.taker_fee_rate + (self.config.min_profit_bps / 10000)
            
            if position_qty > 0: # Long Position -> Sell Order is the Exit
                # We want to sell higher than entry
                exit_price = entry_price * (1 + required_margin)
                # Ensure we don't sell below current market if it's already higher (taking profit)
                # But actually, standard skew logic might already handle "taking profit" if skew is high.
                # Here we enforce a "minimum" exit price to ensure profitability.
                
                # If the standard skew-based target is LOWER than our required exit, force it UP to exit price.
                if sell_target_price < exit_price:
                    logger.info(f"Maker Exit: Adjusting Sell Target {sell_target_price:.2f} -> {exit_price:.2f} (Entry: {entry_price})")
                    sell_target_price = max(sell_target_price, exit_price)
                    
            elif position_qty < 0: # Short Position -> Buy Order is the Exit
                # We want to buy lower than entry
                exit_price = entry_price * (1 - required_margin)
                
                # If standard skew-based target is HIGHER than our required exit, force it DOWN.
                if buy_target_price > exit_price:
                    logger.info(f"Maker Exit: Adjusting Buy Target {buy_target_price:.2f} -> {exit_price:.2f} (Entry: {entry_price})")
                    buy_target_price = min(buy_target_price, exit_price)

        # Place buy order if missing
        if not self.state.has_order("buy"):
            await self._place_order("buy", buy_target_price)
        
        # Place sell order if missing
        if not self.state.has_order("sell"):
            await self._place_order("sell", sell_target_price)
    
    async def _place_order(self, side: str, price: float):
        """Place a single order."""
        import math
        cl_ord_id = f"mm-{side}-{uuid.uuid4().hex[:8]}"
        
        # Different tick sizes for different symbols
        if self.config.symbol.startswith("BTC"):
            tick_size = 0.01
            price_decimals = 2
        else:
            tick_size = 0.1
            price_decimals = 1
        
        # Align price to tick (floor for buy, ceil for sell)
        if side == "buy":
            aligned_price = math.floor(price / tick_size) * tick_size
        else:
            aligned_price = math.ceil(price / tick_size) * tick_size
        price_str = f"{aligned_price:.{price_decimals}f}"
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
                self.monitor.record_order()
                logger.info(f"Order placed successfully: {cl_ord_id}")
            else:
                error_msg = response.get("message", str(response))
                logger.error(f"Order failed: {response}")
                send_notify(
                    "StandX 下单失败",
                    f"{self.config.symbol} {side} 下单失败: {error_msg}",
                    priority="high"
                )
                
        except Exception as e:
            logger.error(f"Failed to place {side} order: {e}")
            send_notify(
                "StandX 下单异常",
                f"{self.config.symbol} {side} 下单异常: {e}",
                priority="high"
            )
    
    def set_reduce_log_file(self, filepath: str):
        """Set the file path for reduce position logging."""
        self._reduce_log_file = filepath
    
    def _write_reduce_log(self, action: str, qty_change: float, reason: str):
        """Write reduce position log."""
        if not self._reduce_log_file:
            return
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self._reduce_log_file, "a") as f:
                f.write(f"{timestamp},{action},{qty_change:+.4f},{reason}\n")
        except:
            pass
    
    async def _check_and_reduce_position(self) -> bool:
        """
        Check if position should be reduced and execute.
        
        Logic:
        - If abs(position) > max_position * 0.5 AND uPNL > 0
        - Reduce to max_position * 0.4 using market order
        
        Returns:
            True if reduction was executed, False otherwise
        """
        # Modified Logic: Aggressive Profit Taking
        # If we have ANY position and are in profit (covering taker fees), CLOSE IT.
        # This overrides the "threshold" logic.
        
        # If config doesn't have min_profit_usd, default to 0 (or safe small value)
        min_profit_usd = getattr(self.config, 'min_profit_usd', 0.0)
        
        current_pos = abs(self.state.position)
        if current_pos == 0:
            return False
        # Check uPNL
        try:
            positions = await self.client.query_positions(self.config.symbol)
            if not positions:
                return False
            upnl = positions[0].upnl
            
            # CONDITION: Profit > Min Threshold
            # We treat this as a "Panic Exit" or "Opportunity Exit" to clear inventory.
            should_reduce = False
            
            if upnl > min_profit_usd:
                 # Only reduce if we are holding position
                 should_reduce = True
                 logger.info(f"Aggressive Profit Take: uPNL ${upnl:.2f} > ${min_profit_usd:.2f}")

            if not should_reduce:
                return False
            # Calculate reduce quantity (Full Close)
            reduce_qty = current_pos
            
            # Determine side
            if self.state.position > 0:
                reduce_side = "sell"
            else:
                reduce_side = "buy"
            
            logger.info(
                f"Closing position (Market): {self.state.position:+.4f}, "
                f"qty={reduce_qty:.4f}, side={reduce_side}, uPNL=${upnl:.2f}"
            )
            
            # Place market order to reduce
            cl_ord_id = f"reduce-{uuid.uuid4().hex[:8]}"
            qty_str = f"{reduce_qty:.3f}"
            
            response = await self.client.new_order(
                symbol=self.config.symbol,
                side=reduce_side,
                qty=qty_str,
                price="0",  # Market order
                cl_ord_id=cl_ord_id,
                order_type="market",
                reduce_only=True,
            )
            
            if response.get("code") == 0 or "id" in response:
                logger.info(f"Close order placed: {cl_ord_id}")
                self.monitor.record_order()
                self._write_reduce_log("CLOSE", -reduce_qty if reduce_side == "sell" else reduce_qty, f"aggressive_exit_upnl_{upnl:.2f}")
                send_notify(
                    "仓位止盈 (Market)",
                    f"{self.config.symbol} 市价止盈 {reduce_qty:.4f}，uPNL=${upnl:.2f}",
                    priority="normal"
                )
                return True
            else:
                logger.error(f"Close order failed: {response}")
                    
        except Exception as e:
            logger.error(f"Failed to check/reduce position: {e}")
    
    async def _check_stop_loss(self) -> bool:
        """
        Check if stop loss is triggered.
        If uPNL < -stop_loss_usd:
            1. Cancel all open orders
            2. Close position (market)
            3. Stop bot
        """
        if self.config.stop_loss_usd <= 0:
            return False
        try:
            positions = await self.client.query_positions(self.config.symbol)
            if not positions:
                return False
            upnl = positions[0].upnl
            
            # Check critical stop loss
            if upnl < -self.config.stop_loss_usd:
                logger.critical(
                    f"STOP LOSS TRIGGERED: uPNL ${upnl:.2f} < -${self.config.stop_loss_usd:.2f}"
                )
                
                # 1. Cancel all orders
                try:
                    open_orders = await self.client.query_open_orders(self.config.symbol)
                    for order in open_orders:
                        await self.client.cancel_order(order.cl_ord_id)
                        self.monitor.record_cancel()
                except Exception as e:
                    logger.error(f"StopLoss: Failed to cancel orders: {e}")
                
                # 2. Close position
                qty = abs(positions[0].qty)
                if qty > 0:
                    side = "sell" if positions[0].qty > 0 else "buy"
                    logger.critical(f"StopLoss: Closing position {qty} {side}")
                    
                    try:
                        await self.client.new_order(
                            symbol=self.config.symbol,
                            side=side,
                            qty=f"{qty:.3f}",
                            price="0",
                            order_type="market",
                            reduce_only=True,
                            cl_ord_id=f"stoploss-{uuid.uuid4().hex[:8]}"
                        )
                        self.monitor.record_order()
                    except Exception as e:
                        logger.error(f"StopLoss: Failed to close position: {e}")
                
                # 3. Notify and Enter Recovery Mode
                send_notify(
                    "紧急止损触发!", 
                    f"触发止损 ${self.config.stop_loss_usd}，当前亏损 ${upnl:.2f}。进入恢复模式，暂停 {self.config.stop_loss_cooldown_sec}秒。",
                    priority="high"
                )
                
                logger.critical(f"Stop loss executed. Entering recovery mode (wait {self.config.stop_loss_cooldown_sec}s)...")
                import time
                self._stop_loss_active = True
                self._next_recovery_check = time.time() + self.config.stop_loss_cooldown_sec
                
                return True
                
        except Exception as e:
            logger.error(f"Error checking stop loss: {e}")
        
        return False
