"""StandX Server Latency Test Script.

Tests:
1. HTTP API latency (public endpoint)
2. WebSocket connection latency
"""
import time
import asyncio
import statistics

import httpx
import websockets


async def test_http_latency(url: str, count: int = 10) -> list[float]:
    """Test HTTP GET latency to a URL."""
    latencies = []
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for i in range(count):
            start = time.time()
            try:
                response = await client.get(url)
                latency = (time.time() - start) * 1000
                latencies.append(latency)
                print(f"  [{i+1}/{count}] HTTP: {latency:.0f}ms (status: {response.status_code})")
            except Exception as e:
                print(f"  [{i+1}/{count}] HTTP failed: {e}")
            
            await asyncio.sleep(0.5)
    
    return latencies


async def test_websocket_latency(url: str, count: int = 10) -> list[float]:
    """Test WebSocket connection + first message latency."""
    latencies = []
    
    for i in range(count):
        start = time.time()
        try:
            ws = await websockets.connect(url, ping_interval=None, close_timeout=5)
            
            # Subscribe to price
            import json
            await ws.send(json.dumps({"subscribe": {"channel": "price", "symbol": "BTC-USD"}}))
            
            # Wait for first message
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            
            latency = (time.time() - start) * 1000
            latencies.append(latency)
            print(f"  [{i+1}/{count}] WebSocket: {latency:.0f}ms (got message)")
            
            await ws.close()
        except Exception as e:
            print(f"  [{i+1}/{count}] WebSocket failed: {e}")
        
        await asyncio.sleep(0.5)
    
    return latencies


def print_stats(name: str, latencies: list[float]):
    """Print latency statistics."""
    if not latencies:
        print(f"\n{name}: No successful measurements")
        return
    
    print(f"\n{name} Statistics ({len(latencies)} samples):")
    print(f"  Min:    {min(latencies):.0f}ms")
    print(f"  Max:    {max(latencies):.0f}ms")
    print(f"  Avg:    {statistics.mean(latencies):.0f}ms")
    if len(latencies) > 1:
        print(f"  Median: {statistics.median(latencies):.0f}ms")
        print(f"  Stdev:  {statistics.stdev(latencies):.0f}ms")


async def main():
    print("=" * 50)
    print("StandX Server Latency Test")
    print("=" * 50)
    
    # Test HTTP API
    print("\n1. Testing HTTP API (public endpoint)...")
    http_url = "https://perps.standx.com/api/query_symbol_price?symbol=BTC-USD"
    http_latencies = await test_http_latency(http_url)
    
    # Test WebSocket
    print("\n2. Testing WebSocket connection...")
    ws_url = "wss://perps.standx.com/ws-stream/v1"
    ws_latencies = await test_websocket_latency(ws_url)
    
    # Print summary
    print("\n" + "=" * 50)
    print("Summary")
    print("=" * 50)
    print_stats("HTTP API", http_latencies)
    print_stats("WebSocket", ws_latencies)


if __name__ == "__main__":
    asyncio.run(main())
