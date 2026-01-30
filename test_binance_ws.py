#!/usr/bin/env python3
"""Test script to verify Binance WS price data reception."""
import asyncio
import json
import websockets

SYMBOL = "btcusdt"
WS_URL = f"wss://fstream.binance.com/ws/stream?streams={SYMBOL}@bookTicker/{SYMBOL}@kline_1s/{SYMBOL}@depth20@100ms"

async def main():
    print(f"Connecting to: {WS_URL}")
    
    async with websockets.connect(WS_URL) as ws:
        print("Connected! Waiting for messages...\n")
        
        count = 0
        while count < 10:  # Print first 10 messages
            message = await ws.recv()
            print(f"RAW[{count}]: {message[:200]}...")  # Print first 200 chars
            
            data = json.loads(message)
            
            stream = data.get("stream", "unknown")
            payload = data.get("data", data)  # If no "data" key, use data itself
            
            if "bookTicker" in stream:
                bid = float(payload.get("b", 0))
                ask = float(payload.get("a", 0))
                mid = (bid + ask) / 2
                print(f"[bookTicker] bid={bid:.2f}, ask={ask:.2f}, mid={mid:.2f}")
            elif "kline" in stream:
                kline = payload.get("k", {})
                close = float(kline.get("c", 0))
                vol = float(kline.get("q", 0))
                closed = kline.get("x", False)
                print(f"[kline_1s] close={close:.2f}, vol={vol:.2f}, closed={closed}")
            elif "depth20" in stream:
                bids = payload.get("bids", [])
                asks = payload.get("asks", [])
                if bids and asks:
                    bid_depth = sum(float(qty) for _, qty in bids[:10])
                    ask_depth = sum(float(qty) for _, qty in asks[:10])
                    imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth) if (bid_depth + ask_depth) > 0 else 0
                    print(f"[depth20] bid_depth={bid_depth:.4f}, ask_depth={ask_depth:.4f}, imbalance={imbalance:.3f}")
            else:
                print(f"[{stream}] {payload}")
            
            count += 1
        
        print("\nTest complete!")

if __name__ == "__main__":
    asyncio.run(main())
