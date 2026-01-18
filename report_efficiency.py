"""
Efficiency Report Generator & Notification Script.

Parses efficiency.log for the last 6 hours and sends a summary to Telegram.
"""
import os
import re
import time
import json
import logging
import argparse
from datetime import datetime, timedelta
import requests
from config import load_config

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
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
    # Log format: 2026-01-18 17:00:00 | Efficiency Report (Last 300.0s):
    timestamp_pattern = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| Efficiency Report")
    
    # Regex to extract percentages
    tier1_pattern = re.compile(r"Tier 1.*:\s+(\d+\.\d+)%")
    tier2_pattern = re.compile(r"Tier 2.*:\s+(\d+\.\d+)%")
    tier3_pattern = re.compile(r"Tier 3.*:\s+(\d+\.\d+)%")
    tier4_pattern = re.compile(r"Tier 4.*:\s+(\d+\.\d+)%")
    
    # Regex for stats
    # Stats: 25 Orders, 22 Cancels, 1 Fills
    stats_pattern = re.compile(r"Stats: (\d+) Orders, (\d+) Cancels, (\d+) Fills")
    
    try:
        current_entry_time = None
        current_duration = 0.0
        
        # We might need to check rotated logs too, but start with main file
        # Ideally, we should check efficiency.log and efficiency.log.1 etc.
        files_to_check = [log_path]
        for i in range(1, 6):
            rotated = f"{log_path}.{i}"
            if os.path.exists(rotated):
                files_to_check.append(rotated)
        
        # Determine total duration line from header: Efficiency Report (Last 300.0s):
        duration_pattern = re.compile(r"\(Last (\d+\.?\d*)s\):")

        # Process logs (oldest to newest if possible, but order matters less for aggregation)
        # We just need to filter by timestamp.
        
        processed_entries = 0
        
        for file_path in files_to_check:
            logger.info(f"Parsing {file_path}...")
            with open(file_path, 'r') as f:
                lines = f.readlines()
                
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

def send_telegram_report(stats: dict, config):
    """Send formatted report to Telegram."""
    if not config.telegram_bot_token or not config.telegram_chat_id:
        logger.error("Telegram not configured in config.yaml")
        return

    if stats["total_time"] == 0:
        logger.warning("No data found for the last 6 hours.")
        message = "⚠️ StandX Bot Efficiency Report\n\nNo data found for the last 6 hours. Bot may be down or logs missing."
    else:
        # Calculate percentages
        total = stats["total_time"]
        t1_pct = stats["tier1_time"] / total * 100
        t2_pct = stats["tier2_time"] / total * 100
        t3_pct = stats["tier3_time"] / total * 100
        t4_pct = stats["tier4_time"] / total * 100
        
        # Calculate rates per hour or minute?
        # Duration in hours
        duration_hours = total / 3600
        orders_per_hour = stats['orders'] / duration_hours if duration_hours > 0 else 0
        cancels_per_hour = stats['cancels'] / duration_hours if duration_hours > 0 else 0
        
        message = (
            f"📊 *StandX Bot Efficiency Report (Last 6h)*\n"
            f"⏱️ Duration Monitored: {duration_hours:.1f} hours\n\n"
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

    # Send
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": config.telegram_chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info("Report sent to Telegram successfully.")
        else:
            logger.error(f"Failed to send Telegram message: {response.text}")
    except Exception as e:
        logger.error(f"Error sending Telegram request: {e}")

def main():
    parser = argparse.ArgumentParser(description="Generate 6h Efficiency Report")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--hours", type=int, default=6, help="Hours to look back")
    args = parser.parse_args()
    
    config = load_config(args.config)
    log_file = "efficiency.log" # Assumed in current dir
    
    logger.info(f"Generating report for last {args.hours} hours...")
    stats = parse_efficiency_log(log_file, args.hours)
    
    if stats:
        send_telegram_report(stats, config)

if __name__ == "__main__":
    main()
