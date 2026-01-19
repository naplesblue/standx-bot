"""
Efficiency Report Generator & Notification Script.

Parses efficiency.log for the last N hours and sends a summary to Telegram.
Includes account balance information.
"""
import os
import re
import time
import json
import logging
import asyncio
import argparse
from datetime import datetime, timedelta
import httpx
from config import load_config
from core.reporting import parse_efficiency_log, generate_efficiency_report_text
from api.auth import StandXAuth
from api.http_client import StandXHTTPClient

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

async def get_balance(config):
    """Authenticate and query balance."""
    try:
        # Check if auth required (only if we want balance)
        if not config.wallet or not config.wallet.private_key:
            return None
            
        auth = StandXAuth()
        await auth.authenticate(config.wallet.chain, config.wallet.private_key)
        
        client = StandXHTTPClient(auth)
        try:
            balance = await client.query_balance()
            return balance
        finally:
            await client.close()
    except Exception as e:
        logger.error(f"Failed to query balance: {e}")
        return None

async def send_telegram_report(stats: dict, config, hours: int, balance_data: dict = None):
    """Send formatted report to Telegram."""
    if not config.telegram_bot_token or not config.telegram_chat_id:
        logger.error("Telegram not configured in config.yaml")
        return

    message = generate_efficiency_report_text(stats, hours, balance_data)

    # Send
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": config.telegram_chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json=payload)
            if response.status_code == 200:
                logger.info("Report sent to Telegram successfully.")
            else:
                logger.error(f"Failed to send Telegram message: {response.text}")
    except Exception as e:
        logger.error(f"Error sending Telegram request: {e}")

async def main_async():
    parser = argparse.ArgumentParser(description="Generate Efficiency Report")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--hours", type=int, default=6, help="Hours to look back")
    args = parser.parse_args()
    
    config = load_config(args.config)
    log_file = "efficiency.log" # Assumed in current dir
    
    logger.info(f"Generating report for last {args.hours} hours...")
    stats = parse_efficiency_log(log_file, args.hours)
    
    if stats:
        # Query balance
        balance_data = await get_balance(config)
        await send_telegram_report(stats, config, args.hours, balance_data)

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
