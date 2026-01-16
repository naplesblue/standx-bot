# StandX Maker Bot

StandX Maker Points 活动的双边挂单做市机器人。在 mark price 两侧挂限价单获取积分，价格靠近时自动撤单避免成交。

本版本加入 CEX 价格引导功能，利用 Binance 数据提前感知市场波动，实现 "先知先觉" 的风控。

**原作者**: [@frozenraspberry](https://x.com/frozenraspberry)

## 策略特性

### 1. CEX 价格引导 (CEX Price Leading)
机器人支持连接 Binance Futures WebSocket 获取实时价格 (BookTicker)。
*   **用途**：利用 CEX (Binance) 的数据来计算市场波动率，触发熔断。
*   **优势**：CEX 价格通常领先 DEX 几秒，能在 StandX 价格剧烈波动前提前撤单防御。
*   **安全性 (Data Staleness Guard)**：如果 Binance 数据发生中断或延迟超过 `binance_staleness_sec` (默认5秒)，机器人会自动识别 "致盲" 风险，**强制撤销所有挂单并暂停运行**，直到数据恢复。

### 2. 双数据流架构
*   **StandX 流**：用于获取 Mark Price，作为挂单的基准锚点 (Anchor)，确保挂单价格贴合 DEX 盘口，避免基差风险。
*   **Binance 流**：用于计算 Volatility，作为风控的触发器。

### 3. 高级风控 (已包含)
*   **波动率熔断**: 高波动时撤单暂停。
*   **冷却机制**: 成交后暂停接单。
*   **自愈式止损**: 触发止损后暂停观察，行情平稳后自动恢复。
*   **智能平仓**: 优先 Maker 限价平仓赚积分。

## 安装

```bash
pip install -r requirements.txt
```

## 配置

参考 `config.example.yaml`：

```yaml
wallet:
  chain: bsc
  private_key: "YOUR_PRIVATE_KEY_HERE"

symbol: BTC-USD
binance_symbol: BTCUSDT  # [新增] 设置 Binance 对应交易对，启用 CEX 引导

# 挂单参数
order_distance_bps: 20
cancel_distance_bps: 10
rebalance_distance_bps: 30
order_size_btc: 0.01

# 仓位与安全
max_position_btc: 0.1
stop_loss_usd: 50.0

# 高级参数
binance_staleness_sec: 5.0  # [新增] Binance 数据最大允许延迟(秒)
taker_fee_rate: 0.0004
min_profit_bps: 2
fill_cooldown_sec: 10
volatility_pause_sec: 30
volatility_window_sec: 5
volatility_threshold_bps: 5

# 恢复模式
stop_loss_cooldown_sec: 600
recovery_window_sec: 300
recovery_volatility_bps: 25
recovery_check_interval_sec: 300
```

## 运行

```bash
python main.py
```

## 注意事项

1.  **网络要求**：启用 `binance_symbol` 后，服务器必须能连通 Binance API (`wss://fstream.binance.com`)。
2.  **断线保护**：如果无法连接 Binance，机器人会因为 CEX 数据陈旧机制 (Staleness Guard) 而持续处于暂停状态（Cancel All & Pause）。这是设计好的安全行为。

## 许可证

MIT License
