"""Efficiency Monitor for tracking market making performance."""
import time
from typing import Optional, Dict

class EfficiencyMonitor:
    """Tracks time spent in different spread efficiency buckets."""
    
    def __init__(self):
        self._stats = {
            "tier1": 0.0,  # 0-10bps
            "tier2": 0.0,  # 10-30bps
            "tier3": 0.0,  # 30-100bps
            "tier4": 0.0,  # >100bps (Inefficient)
            "total_time": 0.0,
            "orders": 0,
            "cancels": 0,
            "fills": 0,
            "realized_pnl": 0.0,
            "fees_paid": 0.0,
        }
        # Synced stats from HTTP API (Report Only)
        self._synced_stats = {
            "fills": None,
            "realized_pnl": None,
            "equity": None,
            "balance": None
        }
        self._last_report_time = time.time()
    
    def update(self, mark_price: float, buy_price: Optional[float], sell_price: Optional[float], dt: float):
        """
        Update efficiency stats based on current orders.
        
        Args:
            mark_price: Current market price (DEX)
            buy_price: Active buy order price (None if no order)
            sell_price: Active sell order price (None if no order)
            dt: Time duration since last update (seconds)
        """
        if dt <= 0 or mark_price <= 0:
            return

        self._stats["total_time"] += dt
        
        # Calculate max deviation of any active order
        max_bps = 9999.0 # Default if no orders
        
        buy_bps = 9999.0
        if buy_price:
            buy_bps = abs(buy_price - mark_price) / mark_price * 10000
            
        sell_bps = 9999.0
        if sell_price:
            sell_bps = abs(sell_price - mark_price) / mark_price * 10000
            
        # We consider the "Efficiency" of the bot to be defined by its best active quote? 
        # Or should it be 'avg'? The prompt implies "Orders falling in..."
        # If we have both, we take the worst one? Or track separately?
        # User requirement: "Statistics of orders falling in..."
        # Usually implies tracking the *presence* of valid quotes.
        # Let's count efficiency if *at least one side* is in the bucket? 
        # Or strictly *both*?
        # Standard MM practice: You get credit if you are quoting.
        # Let's average the presence derived from active sides for simplicity in single metric,
        # or just track "Best Bid/Ask" which represents the spread quality.
        # Let's use the 'worst' of the active orders to represent "Bot Efficiency" 
        # (i.e. if one side is missing, efficiency is low).
        
        # Actually user said "accumulated duration of orders falling in...".
        # Let's consider the state efficient if *both* orders are within range (ideal MM),
        # or at least *one* if we are directional closing.
        # For general monitoring, let's take the MAX deviation of active orders.
        # If an order is missing, we treat it as infinite deviation (inefficient).
        
        relevant_bps = []
        if buy_price: relevant_bps.append(buy_bps)
        if sell_price: relevant_bps.append(sell_bps)
        
        if not relevant_bps:
            current_tier = "tier4" # No orders
        else:
            # We track the "worst" deviation of active orders to be conservative.
            # If we only have 1 order, we track that one.
            worst_active_bps = max(relevant_bps)
            
            if worst_active_bps <= 10:
                current_tier = "tier1"
            elif worst_active_bps <= 30:
                current_tier = "tier2"
            elif worst_active_bps <= 100:
                current_tier = "tier3"
            else:
                current_tier = "tier4"
        
        self._stats[current_tier] += dt

    def record_order(self):
        """Record an order placement."""
        self._stats["orders"] += 1
        
    def record_cancel(self):
        """Record an order cancellation."""
        self._stats["cancels"] += 1
        
    def record_fill(self, pnl: float = 0.0, fee: float = 0.0):
        """Record a fill event with optional PnL and fee."""
        self._stats["fills"] += 1
        self._stats["realized_pnl"] += pnl
        self._stats["fees_paid"] += fee

    def update_synced_stats(self, fills: int, pnl: float, equity: float, balance: float):
        """Update synced stats from reliable HTTP source."""
        self._synced_stats["fills"] = fills
        self._synced_stats["realized_pnl"] = pnl
        self._synced_stats["equity"] = equity
        self._synced_stats["balance"] = balance

    def should_report(self, interval: int = 300) -> bool:
        """Check if it's time to report stats."""
        return time.time() - self._last_report_time >= interval

    def get_report(self) -> str:
        """Generate and reset statistics report."""
        total = self._stats["total_time"]
        if total == 0:
            return "Efficiency: No Data"
            
        t1 = self._stats["tier1"] / total * 100
        t2 = self._stats["tier2"] / total * 100
        t3 = self._stats["tier3"] / total * 100
        t4 = self._stats["tier4"] / total * 100
        
        # Prefer synced stats for PnL/Fills if available
        fills = self._synced_stats["fills"] if self._synced_stats["fills"] is not None else self._stats["fills"]
        pnl = self._synced_stats["realized_pnl"] if self._synced_stats["realized_pnl"] is not None else self._stats["realized_pnl"]
        equity = self._synced_stats["equity"]
        balance = self._synced_stats["balance"]
        
        report = (
            f"Efficiency Report (Last {total:.1f}s):\n"
        )
        
        if equity is not None:
            report += (
                f"  Account:\n"
                f"    Equity:  ${equity:.2f}\n"
                f"    Balance: ${balance:.2f}\n" 
            )
            
        report += (
            f"  Spread Efficiency:\n"
            f"    Tier 1 (0-10bps):   {t1:6.2f}%\n"
            f"    Tier 2 (10-30bps):  {t2:6.2f}%\n"
            f"    Tier 3 (30-100bps): {t3:6.2f}%\n"
            f"    Tier 4 (>100bps):   {t4:6.2f}%\n"
            f"  Operations:\n"
            f"    Orders:  {self._stats['orders']}\n"
            f"    Cancels: {self._stats['cancels']}\n"
            f"    Fills:   {fills}\n"
            f"    PnL:     Realized ${pnl:.4f}\n"
            f"    Fees:    ${self._stats['fees_paid']:.4f}\n" 
        )
        
        # Reset stats
        self._stats = {k: 0.0 if isinstance(v, float) else 0 for k, v in self._stats.items()}
        self._stats["total_time"] = 0.0
        self._last_report_time = time.time()
        
        return report
