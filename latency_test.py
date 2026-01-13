
import asyncio
import time
import httpx
import websockets
import statistics
import logging

# Configure logging
logging.basicConfig(level=logging.ERROR)

HTTP_URL = "https://perps.standx.com/api/query_symbol_price?symbol=BTC-USD"
WS_URL = "wss://perps.standx.com/ws-stream/v1"
ITERATIONS = 20

async def measure_http_latency(client):
    """Measure single HTTP request latency."""
    start = time.perf_counter()
    try:
        resp = await client.get(HTTP_URL)
        resp.raise_for_status()
        end = time.perf_counter()
        return (end - start) * 1000  # ms
    except Exception as e:
        print(f"HTTP Error: {e}")
        return None

async def measure_ws_latency():
    """Measure WebSocket connection + handshake latency."""
    start = time.perf_counter()
    try:
        async with websockets.connect(WS_URL, close_timeout=1) as ws:
            # Wait for connection to be fully established (which it is upon entry)
            pass
        end = time.perf_counter()
        return (end - start) * 1000 # ms
    except Exception as e:
        print(f"WS Error: {e}")
        return None

def print_stats(name, latencies):
    if not latencies:
        print(f"{name}: No successful tests.")
        return

    min_lat = min(latencies)
    max_lat = max(latencies)
    avg_lat = statistics.mean(latencies)
    stdev = statistics.stdev(latencies) if len(latencies) > 1 else 0

    print(f"\n[{name} Test Results ({len(latencies)} samples)]")
    print(f"  Avg:    {avg_lat:.2f} ms")
    print(f"  Min:    {min_lat:.2f} ms")
    print(f"  Max:    {max_lat:.2f} ms")
    print(f"  Jitter: {stdev:.2f} ms")

async def main():
    print(f"Starting Latency Test (Samples: {ITERATIONS})...")
    print(f"Location: Local -> StandX Servers")
    
    # HTTP Test
    print(f"\nTesting HTTP RTT ({HTTP_URL})...")
    http_latencies = []
    async with httpx.AsyncClient() as client:
        # Warmup
        await measure_http_latency(client)
        
        for i in range(ITERATIONS):
            lat = await measure_http_latency(client)
            if lat:
                http_latencies.append(lat)
                print(f"  #{i+1}: {lat:.2f} ms", end="\r")
                await asyncio.sleep(0.1)
    print(" " * 20, end="\r") # Clear line
    
    # WebSocket Test
    print(f"Testing WS Connect RTT ({WS_URL})...")
    ws_latencies = []
    # Warmup
    await measure_ws_latency()
    
    for i in range(ITERATIONS):
        lat = await measure_ws_latency()
        if lat:
            ws_latencies.append(lat)
            print(f"  #{i+1}: {lat:.2f} ms", end="\r")
            await asyncio.sleep(0.1)
    print(" " * 20, end="\r") # Clear line

    # Report
    print("="*40)
    print_stats("HTTP REST", http_latencies)
    print_stats("WebSocket", ws_latencies)
    print("="*40)
    
    if http_latencies and statistics.mean(http_latencies) > 200:
        print("\n\u26a0\ufe0f  WARNING: High latency detected (>200ms).")
        print("    High-frequency quoting may be unstable.")
        print("    Consider using a VPS in AWS Tokyo/Singapore (closest to most exchanges).")

if __name__ == "__main__":
    asyncio.run(main())
