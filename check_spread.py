import asyncio
import logging
import argparse
from datetime import datetime

from api.ws_client import MarketWSClient
from api.binance_client import BinanceWSClient

# Configure logging to console only
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("spread_checker")

# Suppress other loggers
logging.getLogger("api.ws_client").setLevel(logging.WARNING)
logging.getLogger("api.binance_client").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.ERROR)

class PriceMonitor:
    def __init__(self, standx_symbol: str, binance_symbol: str):
        self.standx_symbol = standx_symbol
        self.binance_symbol = binance_symbol
        self.latest_standx = 0.0
        self.latest_binance = 0.0
        self.last_standx_time = 0.0
        self.last_binance_time = 0.0

    def on_standx_price(self, data):
        # Data format from ws_client.py: {"data": {"last_price": ...}}
        try:
            price_data = data.get("data", {})
            price = float(price_data.get("last_price", 0))
            if price > 0:
                self.latest_standx = price
                self.last_standx_time = datetime.now().timestamp()
        except Exception:
            pass

    def on_binance_price(self, price):
        # Binance client passes float directly
        self.latest_binance = price
        self.last_binance_time = datetime.now().timestamp()

    async def run(self):
        logger.info(f"Starting Price Monitor: StandX({self.standx_symbol}) vs Binance({self.binance_symbol})")
        
        # Initialize clients
        standx_ws = MarketWSClient()
        binance_ws = BinanceWSClient(self.binance_symbol)

        # Setup callbacks
        standx_ws.on_price(self.on_standx_price)
        binance_ws.on_price(self.on_binance_price)

        # Start connections
        await standx_ws.connect()
        await standx_ws.subscribe_price(self.standx_symbol)

        # Create tasks
        tasks = [
            asyncio.create_task(standx_ws.run()),
            asyncio.create_task(binance_ws.run())
        ]

        logger.info("Waiting for price data...")
        
        try:
            while True:
                await asyncio.sleep(1)
                
                s_price = self.latest_standx
                b_price = self.latest_binance
                
                if s_price == 0 or b_price == 0:
                    continue

                diff = s_price - b_price
                diff_pct = (diff / b_price) * 100
                diff_bps = diff_pct * 100

                now = datetime.now()
                # Check for staleness
                now_ts = now.timestamp()
                s_stale = (now_ts - self.last_standx_time) > 5
                b_stale = (now_ts - self.last_binance_time) > 5
                
                status = ""
                if s_stale: status += "[StandX Stale] "
                if b_stale: status += "[Binance Stale] "

                logger.info(
                    f"Binance: {b_price:.2f} | StandX: {s_price:.2f} | "
                    f"Diff: {diff:+.2f} ({diff_bps:+.1f} bps) {status}"
                )

        except asyncio.CancelledError:
            pass
        finally:
            await standx_ws.close()
            await binance_ws.close()
            for t in tasks: t.cancel()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--standx", default="BTC-USD", help="StandX symbol")
    parser.add_argument("--binance", default="BTCUSDT", help="Binance symbol")
    args = parser.parse_args()

    try:
        asyncio.run(PriceMonitor(args.standx, args.binance).run())
    except KeyboardInterrupt:
        pass
