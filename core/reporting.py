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
    
    # Regex to extract percentages
    tier1_pattern = re.compile(r"Tier 1.*:\s+(\d+\.\d+)%")
    tier2_pattern = re.compile(r"Tier 2.*:\s+(\d+\.\d+)%")
    tier3_pattern = re.compile(r"Tier 3.*:\s+(\d+\.\d+)%")
    tier4_pattern = re.compile(r"Tier 4.*:\s+(\d+\.\d+)%")
    
    # Regex for stats
    stats_pattern = re.compile(r"Stats: (\d+) Orders, (\d+) Cancels, (\d+) Fills")
    
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
                    
                    st = stats_pattern.search(line)
                    if st:
                        stats["orders"] += int(st.group(1))
                        stats["cancels"] += int(st.group(2))
                        stats["fills"] += int(st.group(3))

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
