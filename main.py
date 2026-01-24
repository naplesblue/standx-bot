"""StandX Maker Bot - Main entry point.

Usage:
    python main.py
    python main.py --config custom_config.yaml
"""
import sys
import signal
import asyncio
import logging
import argparse
import time

from config import load_config
from api.auth import StandXAuth
from api.http_client import StandXHTTPClient
from api.ws_client import MarketWSClient, UserWSClient
from api.binance_client import BinanceWSClient
from api.telegram import TelegramBot
from core.state import State
from core.maker import Maker
from referral import check_if_referred, apply_referral, REFERRAL_CODE


from logging.handlers import RotatingFileHandler
import os

# Configure logging with rotation
log_file = "standx_bot.log"
handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S"))

logging.basicConfig(
    level=logging.INFO,
    handlers=[handler, logging.StreamHandler()]
)

# Silence noisy third-party libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Configure separate logger for efficiency reports
efficiency_logger = logging.getLogger("standx.efficiency")
efficiency_logger.setLevel(logging.INFO)
efficiency_logger.propagate = False  # Don't duplicate in main log

eff_handler = RotatingFileHandler("efficiency.log", maxBytes=5*1024*1024, backupCount=3)
eff_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s", "%Y-%m-%d %H:%M:%S"))
efficiency_logger.addHandler(eff_handler)

logger = logging.getLogger(__name__)


async def main(config_path: str):
    """Main async entry point."""
    
    # Load config
    logger.info(f"Loading config from {config_path}")
    config = load_config(config_path)
    logger.info(f"Symbol: {config.symbol}, Order size: {config.order_size_btc} BTC")
    
    # Initialize authentication
    logger.info("Initializing authentication...")
    auth = StandXAuth()
    await auth.authenticate(config.wallet.chain, config.wallet.private_key)
    logger.info("Authentication successful")
    
    # Check and apply referral if needed
    try:
        is_referred = await check_if_referred(auth)
        if not is_referred:
            logger.info(f"Account not referred, applying referral code: {REFERRAL_CODE}")
            result = await apply_referral(auth, "frozenbanana")
            if result.get("success") or result.get("code") == 0:
                logger.info("Referral applied successfully")
            else:
                logger.warning(f"Referral failed: {result}")
        else:
            logger.debug("Account already referred")
    except Exception as e:
        logger.warning(f"Referral check/apply failed: {e}")
    
    # Initialize clients
    http_client = StandXHTTPClient(auth)
    
    # Set latency log file based on config name
    config_name = config_path.replace(".yaml", "").replace(".yml", "")
    latency_log_file = f"latency_{config_name}.log"
    http_client.set_latency_log_file(latency_log_file)
    logger.info(f"Latency logging to: {latency_log_file}")
    
    market_ws = MarketWSClient()
    user_ws = UserWSClient(auth)
    
    # Initialize Binance WS Check
    binance_ws = None
    if config.binance_symbol:
        logger.info(f"Initializing Binance WS for {config.binance_symbol}...")
        binance_ws = BinanceWSClient(config.binance_symbol)
    else:
        logger.info("Binance WS not configured, using StandX price for volatility.")
    
    # Initialize Telegram Bot
    telegram_bot = None
    if config.telegram_bot_token and config.telegram_chat_id:
        logger.info("Initializing Telegram Bot...")
        telegram_bot = TelegramBot(config.telegram_bot_token, config.telegram_chat_id, http_client)
    else:
        logger.info("Telegram Bot not configured, skipping.")
    
    state = State()
    
    # Initialize maker
    maker = Maker(config, http_client, state)
    
    # Set reduce position log file
    reduce_log_file = f"reduce_{config_name}.log"
    maker.set_reduce_log_file(reduce_log_file)
    logger.info(f"Reduce position logging to: {reduce_log_file}")
    
    # Setup shutdown handler
    shutdown_event = asyncio.Event()
    
    def handle_shutdown(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        shutdown_event.set()
    
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    
    try:
        # Connect WebSockets
        await market_ws.connect()
        await market_ws.subscribe_price(config.symbol)
        
        await user_ws.connect()
        
        # Register price callback - triggers order checks
        def on_price(data):
            price_data = data.get("data", {})
            last_price = price_data.get("last_price")
            if last_price:
                maker.on_price_update(float(last_price))
                logger.debug(f"Price update: {last_price}")
        
        market_ws.on_price(on_price)
        
        # Wire Binance WS Callbacks
        if binance_ws:
            def on_binance_price(price: float):
                maker.on_cex_price_update(price)
                # Note: Dont double confirm price here, handled in maker
            
            binance_ws.on_price(on_binance_price)
            # await binance_ws.run() # Handled by task list below
        
        # Register order callback to detect fills
        def on_order(data):
            order_data = data.get("data", {})
            status = order_data.get("status")
            cl_ord_id = order_data.get("cl_ord_id", "")
            side = order_data.get("side")
            
            logger.info(f"Order update: cl_ord_id={cl_ord_id}, status={status}, side={side}")
            
            if status and status.lower() in ("filled", "partially_filled", "cancelled", "rejected"):
                # Record fill immediately upon receipt
                if status.lower() in ("filled", "partially_filled"):
                    state.record_fill()
                    # Only record fill in monitor if it's a new fill event
                    # Extract PnL/Fee if available (not always present in order update, check API docs/response)
                    realized_pnl = float(order_data.get("realized_pnl", 0))
                    fee = float(order_data.get("cum_fee", 0)) # or fee field
                    
                    # Note: WS might send multiple updates for same partial fill state.
                    # Ideally we should diff cum_qty, but for now we rely on API to send "trade" events separate from "order" events for precise pnl.
                    # Assuming order update contains cumulative PnL, we need to be careful not to double count.
                    # Actually, 'realized_pnl' in order update is usually cumulative for that order.
                    # But monitor is stateless between fills.
                    # Let's just track it nicely. If we get repeated updates, we might over-count if we just add.
                    # BUT, usually 'filled' is final. 'partially_filled' keeps coming.
                    # Better approach: Just record the fill count here. PnL tracking might be better in 'on_trade' if available.
                    # For now, we will add 0 pnl here and rely on position update or separate trade stream if needed.
                    # Wait, user asked for realized PnL.
                    # Let's try to get it from the message.
                    pnl = float(order_data.get("realized_pnl", 0))
                    
                    maker.monitor.record_fill(pnl=pnl)
                    logger.info(f"Fill detected ({status}) and recorded: {cl_ord_id}, PnL={pnl}")

                if side in ("buy", "sell"):
                    current_order = state.get_order(side)
                    if current_order and current_order.cl_ord_id == cl_ord_id:
                        if status.lower() in ("filled", "cancelled", "rejected"):
                            logger.info(f"Order {status}: clearing {side} from state")
                            state.set_order(side, None)
                        elif status.lower() == "partially_filled":
                            remaining_qty = (
                                order_data.get("leaves_qty")
                                or order_data.get("remaining_qty")
                                or order_data.get("left_qty")
                            )
                            if remaining_qty is not None:
                                try:
                                    state.update_order_qty(side, float(remaining_qty))
                                except Exception:
                                    pass
                        
                        # Trigger a check to potentially place new order
                        maker._pending_check.set()
        
        user_ws.on_order(on_order)
        
        # Register position callback to track fills
        def on_position(data):
            pos_data = data.get("data", {})
            qty = float(pos_data.get("qty", 0))
            symbol = pos_data.get("symbol", "")
            
            pending_price = pos_data.get("entry_price", None)
            entry_price = float(pending_price) if pending_price is not None else 0.0
            
            if symbol == config.symbol:
                logger.info(f"Position update: {symbol} qty={qty} @ {entry_price}")
                
                # Check for position change to detect hidden fills
                previous_qty = state.position
                if abs(qty - previous_qty) > 1e-6:
                     # Position changed -> implies a trade happened
                     # We record it only if it wasn't just recorded by on_order (heuristic)
                     import time
                     time_since_last_fill = time.time() - state.last_fill_time
                     if time_since_last_fill > 1.0: # If > 1s since last order-based fill record
                         logger.info(f"Fill detected via Position Change: {previous_qty} -> {qty}")
                         state.record_fill()
                         maker.monitor.record_fill()
                
                state.update_position(qty, entry_price)
        
        user_ws.on_position(on_position)
        
        # Initialize state from exchange
        await maker.initialize()

        # Background task to sync stats
        async def sync_stats_task(interval: int = 60):
            logger.info(f"Starting stats sync task (interval={interval}s)")
            from datetime import datetime
            
            while not shutdown_event.is_set():
                try:
                    await asyncio.sleep(interval)
                    if shutdown_event.is_set(): break

                    # 1. Query Balance (Equity)
                    try:
                        bal_res = await http_client.query_balance()
                        data = bal_res.get("data", {})
                        equity = float(data.get("equity", 0))
                        balance = float(data.get("balance", 0))
                    except Exception as e:
                        logger.warning(f"Sync: Failed to query balance: {e}")
                        equity = 0.0
                        balance = 0.0

                    # 2. Query Orders (Fills & PnL in current report window)
                    try:
                        # Use query_history_orders which maps to /api/query_orders
                        orders = await http_client.query_history_orders(limit=100)
                        
                        # EfficiencyMonitor uses _last_report_time.
                        window_start = maker.monitor._last_report_time
                        
                        fills_count = 0
                        realized_pnl = 0.0
                        
                        for o in orders:
                            if o.status in ("filled", "partially_filled"):
                                try:
                                    t_str = o.updated_at.replace("Z", "+00:00")
                                    dt = datetime.fromisoformat(t_str)
                                    ts = dt.timestamp()
                                    
                                    if ts >= window_start:
                                        fills_count += 1
                                        realized_pnl += o.realized_pnl
                                except Exception:
                                    pass
                                    
                        maker.monitor.update_synced_stats(fills_count, realized_pnl, equity, balance)
                        
                    except Exception as e:
                        logger.warning(f"Sync: Failed to query orders: {e}")

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Sync task error: {e}")
                    await asyncio.sleep(5)

        # Start all tasks
        tasks = [
            asyncio.create_task(sync_stats_task(), name="sync_stats"),
            asyncio.create_task(market_ws.run(), name="market_ws"),
            asyncio.create_task(user_ws.run(), name="user_ws"),
            asyncio.create_task(maker.run(), name="maker"),
            asyncio.create_task(shutdown_event.wait(), name="shutdown"),
        ]
        
        if binance_ws:
             tasks.append(asyncio.create_task(binance_ws.run(), name="binance_ws"))

        if telegram_bot:
             tasks.append(asyncio.create_task(telegram_bot.run(), name="telegram_bot"))
        
        logger.info("Bot started, press Ctrl+C to stop")
        
        # Wait for shutdown or any task to complete
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        
        # Stop all running components first
        await maker.stop()
        await market_ws.close()
        await user_ws.close()
        if binance_ws:
            await binance_ws.close()
        if telegram_bot:
            telegram_bot.stop()
        
        # Cancel pending tasks with timeout
        for task in pending:
            task.cancel()
        
        if pending:
            # Wait up to 3 seconds for tasks to finish
            await asyncio.wait(pending, timeout=3.0)
        
    finally:
        # Cancel all open orders on exit
        logger.info("Cleaning up...")
        try:
            orders_to_cancel = []
            if state.has_order("buy"):
                orders_to_cancel.append(state.get_order("buy").cl_ord_id)
            if state.has_order("sell"):
                orders_to_cancel.append(state.get_order("sell").cl_ord_id)
            
            if orders_to_cancel:
                logger.info(f"Cancelling {len(orders_to_cancel)} orders on exit: {orders_to_cancel}")
                await http_client.cancel_orders(orders_to_cancel)
                state.clear_all_orders()
                logger.info("All orders cancelled successfully")
        except Exception as e:
            logger.error(f"Failed to cancel orders on exit: {e}")
        
        await http_client.close()
        logger.info("Shutdown complete")


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="StandX Maker Bot")
    parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Path to config file (default: config.yaml)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(args.config))
