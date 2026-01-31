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
        
        stats = {"bookTicker": 0, "kline": 0, "depthUpdate": 0, "unknown": 0}
        count = 0
        
        while count < 50:  # Check 50 messages
            message = await ws.recv()
            data = json.loads(message)
            
            # Handle flat format (no stream wrapper)
            if "stream" in data:
                payload = data.get("data", {})
            else:
                payload = data
            
            event_type = payload.get("e", "unknown")
            
            if event_type == "bookTicker":
                bid = float(payload["b"])
                ask = float(payload["a"])
                mid = (bid + ask) / 2
                stats["bookTicker"] += 1
                if stats["bookTicker"] <= 3:  # Print first 3
                    print(f"✅ [bookTicker] mid={mid:.2f}")
                    
            elif event_type == "kline":
                kline = payload.get("k", {})
                close = float(kline.get("c", 0))
                closed = kline.get("x", False)
                stats["kline"] += 1
                if stats["kline"] <= 3:
                    print(f"✅ [kline] close={close:.2f}, closed={closed}")
                    
            elif event_type == "depthUpdate":
                bids = payload.get("b", [])
                asks = payload.get("a", [])
                bid_depth = sum(float(qty) for _, qty in bids[:10])
                ask_depth = sum(float(qty) for _, qty in asks[:10])
                total = bid_depth + ask_depth
                imbalance = (bid_depth - ask_depth) / total if total > 0 else 0
                stats["depthUpdate"] += 1
                if stats["depthUpdate"] <= 3:
                    print(f"✅ [depthUpdate] imbalance={imbalance:.3f}")
            else:
                stats["unknown"] += 1
                print(f"❓ [unknown] e={event_type}")
            
            count += 1
        
        print(f"\n=== SUMMARY (50 messages) ===")
        print(f"bookTicker: {stats['bookTicker']}")
        print(f"kline:      {stats['kline']}")
        print(f"depthUpdate: {stats['depthUpdate']}")
        print(f"unknown:    {stats['unknown']}")
        
        if stats["bookTicker"] > 0 and stats["depthUpdate"] > 0:
            print("\n🎉 ALL CEX DATA PARSING WORKS!")
        else:
            print("\n❌ SOME PARSING FAILED!")

if __name__ == "__main__":
    asyncio.run(main())
