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
import httpx
from config import load_config

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

from core.reporting import parse_efficiency_log, generate_efficiency_report_text

def send_telegram_report(stats: dict, config, hours: int):
    """Send formatted report to Telegram."""
    if not config.telegram_bot_token or not config.telegram_chat_id:
        logger.error("Telegram not configured in config.yaml")
        return

    message = generate_efficiency_report_text(stats, hours)

    # Send
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": config.telegram_chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        response = httpx.post(url, json=payload, timeout=10)
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
        send_telegram_report(stats, config, args.hours)

if __name__ == "__main__":
    main()
