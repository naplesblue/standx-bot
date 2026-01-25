"""
Shared reporting logic for efficiency statistics.
"""
import os
import re
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

def parse_efficiency_log(log_path: str, hours: int = 6) -> dict:
    """Parse efficiency log and aggregate stats for the last N hours."""
    if not os.path.exists(log_path):
        logger.error(f"Log file not found: {log_path}")
        return None

    now = datetime.now()
    cutoff_time = now - timedelta(hours=hours)
    
    stats = {
        "band_0_10_time": 0.0,
        "band_10_30_time": 0.0,
        "band_out_time": 0.0,
        "warmup_time": 0.0,
        "eligible_ratio_time": 0.0,
        "weighted_efficiency_time": 0.0,
        "warmup_threshold": None,
        "tier1_time": 0.0,
        "tier2_time": 0.0,
        "tier3_time": 0.0,
        "tier4_time": 0.0,
        "total_time": 0.0,
        "orders": 0,
        "cancels": 0,
        "fills": 0,
        "report_count": 0
    }
    
    # Regex to extract timestamp
    # Relaxed regex to match various formats containing timestamp and keyword
    timestamp_pattern = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*Efficiency Report")
    
    # Regex to extract duration
    duration_pattern = re.compile(r"\(Last (\d+\.?\d*)s\):")
    
    # Regex to extract percentages (legacy tiers)
    tier1_pattern = re.compile(r"Tier 1.*:\s+(\d+\.\d+)%")
    tier2_pattern = re.compile(r"Tier 2.*:\s+(\d+\.\d+)%")
    tier3_pattern = re.compile(r"Tier 3.*:\s+(\d+\.\d+)%")
    tier4_pattern = re.compile(r"Tier 4.*:\s+(\d+\.\d+)%")

    # Regex to extract points bands (new format)
    band_0_10_pattern = re.compile(r"0-10bps.*:\s+(\d+\.\d+)%")
    band_10_30_pattern = re.compile(r"10-30bps.*:\s+(\d+\.\d+)%")
    band_out_pattern = re.compile(r">30bps.*:\s+(\d+\.\d+)%")
    warmup_pattern = re.compile(r"Warmup\s+\(<(\d+\.?\d*)s\):\s+(\d+\.\d+)%")
    eligible_pattern = re.compile(r"Eligible Ratio:\s+(\d+\.\d+)%")
    weighted_pattern = re.compile(r"Weighted Efficiency:\s+(\d+\.\d+)%")
    
    # Regex for stats
    # Regex for stats (Multi-line format compatible)
    # New format:
    #   Operations:
    #     Orders:  X
    #     Cancels: Y
    #     Fills:   Z
    orders_pattern = re.compile(r"Orders:\s+(\d+)")
    cancels_pattern = re.compile(r"Cancels:\s+(\d+)")
    fills_pattern = re.compile(r"Fills:\s+(\d+)")
    
    try:
        current_entry_time = None
        current_duration = 0.0
        
        # Check main log and rotated logs (up to .5)
        files_to_check = [log_path]
        for i in range(1, 6):
            rotated = f"{log_path}.{i}"
            if os.path.exists(rotated):
                files_to_check.append(rotated)
        
        for file_path in files_to_check:
            # logger.info(f"Parsing {file_path}...")
            try:
                with open(file_path, 'r') as f:
                    lines = f.readlines()
            except Exception:
                continue
                
            for line in lines:
                # Check for header and timestamp
                ts_match = timestamp_pattern.search(line)
                if ts_match:
                    ts_str = ts_match.group(1)
                    entry_time = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                    
                    if entry_time > cutoff_time:
                        current_entry_time = entry_time
                        
                        # Extract duration of this block
                        dur_match = duration_pattern.search(line)
                        if dur_match:
                            current_duration = float(dur_match.group(1))
                            stats["total_time"] += current_duration
                            stats["report_count"] += 1
                        else:
                            current_duration = 0.0
                    else:
                        current_entry_time = None # Skip this block
                        
                elif current_entry_time:
                    # We are inside a valid block, parse stats
                    t1 = tier1_pattern.search(line)
                    if t1: stats["tier1_time"] += float(t1.group(1)) * current_duration / 100
                    
                    t2 = tier2_pattern.search(line)
                    if t2: stats["tier2_time"] += float(t2.group(1)) * current_duration / 100
                    
                    t3 = tier3_pattern.search(line)
                    if t3: stats["tier3_time"] += float(t3.group(1)) * current_duration / 100
                    
                    t4 = tier4_pattern.search(line)
                    if t4: stats["tier4_time"] += float(t4.group(1)) * current_duration / 100

                    b1 = band_0_10_pattern.search(line)
                    if b1: stats["band_0_10_time"] += float(b1.group(1)) * current_duration / 100

                    b2 = band_10_30_pattern.search(line)
                    if b2: stats["band_10_30_time"] += float(b2.group(1)) * current_duration / 100

                    bout = band_out_pattern.search(line)
                    if bout: stats["band_out_time"] += float(bout.group(1)) * current_duration / 100

                    warm = warmup_pattern.search(line)
                    if warm:
                        stats["warmup_threshold"] = float(warm.group(1))
                        stats["warmup_time"] += float(warm.group(2)) * current_duration / 100

                    eligible = eligible_pattern.search(line)
                    if eligible:
                        stats["eligible_ratio_time"] += float(eligible.group(1)) * current_duration / 100

                    weighted = weighted_pattern.search(line)
                    if weighted:
                        stats["weighted_efficiency_time"] += float(weighted.group(1)) * current_duration / 100
                    
                    
                    # Parse operations from separate lines
                    ord_match = orders_pattern.search(line)
                    if ord_match: stats["orders"] += int(ord_match.group(1))
                    
                    cnl_match = cancels_pattern.search(line)
                    if cnl_match: stats["cancels"] += int(cnl_match.group(1))
                    
                    fil_match = fills_pattern.search(line)
                    if fil_match: stats["fills"] += int(fil_match.group(1))

    except Exception as e:
        logger.error(f"Error parsing log: {e}")
        return None
        
    return stats


def generate_efficiency_report_text(stats: dict, hours: int, balance_data: dict = None, realized_pnl: float = None) -> str:
    """Generate formatted efficiency report text."""
    if not stats or stats["total_time"] == 0:
        return f"⚠️ StandX Bot Efficiency Report\n\nNo data found for the last {hours} hours. Bot may be down or logs missing."
    
    # Calculate percentages
    total = stats["total_time"]
    use_points = (
        stats["band_0_10_time"]
        + stats["band_10_30_time"]
        + stats["band_out_time"]
        + stats["warmup_time"]
    ) > 0
    if use_points:
        b1_pct = stats["band_0_10_time"] / total * 100
        b2_pct = stats["band_10_30_time"] / total * 100
        bout_pct = stats["band_out_time"] / total * 100
        warmup_pct = stats["warmup_time"] / total * 100
        eligible_pct = stats["eligible_ratio_time"] / total * 100
        weighted_pct = stats["weighted_efficiency_time"] / total * 100
    else:
        t1_pct = stats["tier1_time"] / total * 100
        t2_pct = stats["tier2_time"] / total * 100
        t3_pct = stats["tier3_time"] / total * 100
        t4_pct = stats["tier4_time"] / total * 100
    
    # Duration in hours
    duration_hours = total / 3600
    orders_per_hour = stats['orders'] / duration_hours if duration_hours > 0 else 0
    cancels_per_hour = stats['cancels'] / duration_hours if duration_hours > 0 else 0
    
    balance_section = ""
    if balance_data:
        equity = float(balance_data.get("equity", 0) or 0)
        bal = float(balance_data.get("balance", 0) or 0)
        upnl = float(balance_data.get("upnl", 0) or 0)
        if realized_pnl is not None:
             upnl = realized_pnl # Use provided realized pnl from Position API
        else:
             # Fallback or use un-realized from balance? NO, user asked for accumulated realized.
             # Balance data usually has 'upnl' (unrealized) and 'pnl_freeze' (realized).
             # If realized_pnl param is passed, we use it as "PnL" display.
             pass
             
        balance_section = (
            f"*Account:*\n"
            f"💰 Equity:  ${equity:,.2f}\n"
            f"💵 Balance: ${bal:,.2f}\n"
            f"📈 PnL (Realized): ${upnl:,.2f}\n\n"
        )
    
    if use_points:
        warmup_threshold = stats["warmup_threshold"] or 3
        message = (
            f"📊 *StandX Bot Efficiency Report (Last {hours}h)*\n"
            f"⏱️ Duration Monitored: {duration_hours:.1f} hours\n\n"
            f"{balance_section}"
            f"*Points Bands (Notional-weighted):*\n"
            f"🟢 0-10bps (100%):  *{b1_pct:.1f}%*\n"
            f"🟡 10-30bps (50%): {b2_pct:.1f}%\n"
            f"🔴 >30bps (0%):     {bout_pct:.1f}%\n"
            f"🟤 Warmup (<{warmup_threshold:.0f}s): {warmup_pct:.1f}%\n\n"
            f"*Points Efficiency:*\n"
            f"✅ Eligible Ratio:      {eligible_pct:.1f}%\n"
            f"⭐ Weighted Efficiency: {weighted_pct:.1f}%\n\n"
            f"*Operations:*\n"
            f"📥 Total Orders:  {stats['orders']} ({orders_per_hour:.0f}/h)\n"
            f"🔄 Total Cancels: {stats['cancels']} ({cancels_per_hour:.0f}/h)\n"
            f"✅ Total Fills:   {stats['fills']}\n"
        )
    else:
        message = (
            f"📊 *StandX Bot Efficiency Report (Last {hours}h)*\n"
            f"⏱️ Duration Monitored: {duration_hours:.1f} hours\n\n"
            f"{balance_section}"
            f"*Spread Efficiency:*\n"
            f"🟢 Tier 1 (0-10bps):  *{t1_pct:.1f}%*\n"
            f"🟡 Tier 2 (10-30bps): {t2_pct:.1f}%\n"
            f"🟠 Tier 3 (30-100bps):{t3_pct:.1f}%\n"
            f"🔴 Inefficient:       {t4_pct:.1f}%\n\n"
            f"*Operations:*\n"
            f"📥 Total Orders:  {stats['orders']} ({orders_per_hour:.0f}/h)\n"
            f"🔄 Total Cancels: {stats['cancels']} ({cancels_per_hour:.0f}/h)\n"
            f"✅ Total Fills:   {stats['fills']}\n"
        )
    return message
