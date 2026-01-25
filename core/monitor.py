"""Efficiency Monitor for tracking market making performance."""
import time
from typing import Optional, Dict

class EfficiencyMonitor:
    """Tracks time spent in different spread efficiency buckets."""
    
    def __init__(self):
        self._stats = {
            "tier1_notional_time": 0.0,  # 0-10bps (100%)
            "tier2_notional_time": 0.0,  # 10-30bps (50%)
            "out_of_band_notional_time": 0.0,  # >30bps (0%)
            "warmup_notional_time": 0.0,  # < min_rest_sec
            "total_order_notional_time": 0.0,
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
        self._order_id = {"buy": None, "sell": None}
        self._order_start = {"buy": None, "sell": None}
        self._min_rest_sec = 3.0
        self._last_report_time = time.time()
    
    def update(
        self,
        mark_price: float,
        buy_order: Optional[object],
        sell_order: Optional[object],
        dt: float,
        min_rest_sec: float = 3.0,
    ):
        """
        Update efficiency stats based on current orders.
        
        Args:
            mark_price: Current market price (DEX)
            buy_order: Active buy order (None if no order)
            sell_order: Active sell order (None if no order)
            dt: Time duration since last update (seconds)
            min_rest_sec: Minimum resting time before points accrue
        """
        if dt <= 0 or mark_price <= 0:
            return

        self._min_rest_sec = min_rest_sec
        self._stats["total_time"] += dt
        now = time.time()

        self._sync_order_state("buy", buy_order, now)
        self._sync_order_state("sell", sell_order, now)

        for side, order in (("buy", buy_order), ("sell", sell_order)):
            if not order:
                continue

            start_time = self._order_start.get(side)
            if start_time is None:
                continue

            notional = abs(order.qty) * mark_price
            self._stats["total_order_notional_time"] += notional * dt

            if now - start_time < min_rest_sec:
                self._stats["warmup_notional_time"] += notional * dt
                continue

            distance_bps = abs(order.price - mark_price) / mark_price * 10000

            if distance_bps <= 10:
                self._stats["tier1_notional_time"] += notional * dt
            elif distance_bps <= 30:
                self._stats["tier2_notional_time"] += notional * dt
            else:
                self._stats["out_of_band_notional_time"] += notional * dt

    def _sync_order_state(self, side: str, order: Optional[object], now: float):
        if not order:
            self._order_id[side] = None
            self._order_start[side] = None
            return

        if self._order_id.get(side) != order.cl_ord_id:
            self._order_id[side] = order.cl_ord_id
            self._order_start[side] = now

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
        total_notional_time = self._stats["total_order_notional_time"]
        if total == 0 or total_notional_time == 0:
            return "Efficiency: No Data"

        tier1 = self._stats["tier1_notional_time"]
        tier2 = self._stats["tier2_notional_time"]
        out_of_band = self._stats["out_of_band_notional_time"]
        warmup = self._stats["warmup_notional_time"]

        t1 = tier1 / total_notional_time * 100
        t2 = tier2 / total_notional_time * 100
        t0 = out_of_band / total_notional_time * 100
        tw = warmup / total_notional_time * 100

        point_weighted = tier1 + tier2 * 0.5
        points_efficiency = point_weighted / total_notional_time
        eligible_ratio = (tier1 + tier2) / total_notional_time
        
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
            f"  Points Bands (Notional-weighted):\n"
            f"    0-10bps (100%): {t1:6.2f}%\n"
            f"    10-30bps (50%): {t2:6.2f}%\n"
            f"    >30bps (0%):    {t0:6.2f}%\n"
            f"    Warmup (<{self._min_rest_sec:.0f}s):   {tw:6.2f}%\n"
            f"  Points Efficiency:\n"
            f"    Eligible Ratio:      {eligible_ratio * 100:6.2f}%\n"
            f"    Weighted Efficiency: {points_efficiency * 100:6.2f}%\n"
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
