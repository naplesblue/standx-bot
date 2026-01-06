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

from config import load_config
from api.auth import StandXAuth
from api.http_client import StandXHTTPClient
from api.ws_client import MarketWSClient, UserWSClient
from core.state import State
from core.maker import Maker


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
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
    
    # Initialize clients
    http_client = StandXHTTPClient(auth)
    market_ws = MarketWSClient()
    user_ws = UserWSClient(auth)
    
    # Initialize state
    state = State()
    
    # Initialize maker
    maker = Maker(config, http_client, state)
    
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
        
        # Register price callback
        def on_price(data):
            price_data = data.get("data", {})
            last_price = price_data.get("last_price")
            if last_price:
                state.update_price(float(last_price), config.volatility_window_sec)
                logger.debug(f"Price update: {last_price}")
        
        market_ws.on_price(on_price)
        
        # Register order callback
        def on_order(data):
            logger.info(f"Order update: {data}")
            # TODO: Handle order status changes
        
        user_ws.on_order(on_order)
        
        # Initialize state from exchange
        await maker.initialize()
        
        # Start all tasks
        tasks = [
            asyncio.create_task(market_ws.run(), name="market_ws"),
            asyncio.create_task(user_ws.run(), name="user_ws"),
            asyncio.create_task(maker.run(), name="maker"),
            asyncio.create_task(shutdown_event.wait(), name="shutdown"),
        ]
        
        logger.info("Bot started, press Ctrl+C to stop")
        
        # Wait for shutdown or any task to complete
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        
        # Cancel pending tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
    finally:
        # Cleanup
        logger.info("Cleaning up...")
        await maker.stop()
        await market_ws.close()
        await user_ws.close()
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
