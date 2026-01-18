# StandX Maker Bot

StandX Maker Points 活动的双边挂单做市机器人。在 mark price 两侧挂限价单获取积分，价格靠近时自动撤单避免成交。

本版本加入 CEX 价格引导功能，利用 Binance 数据提前感知市场波动，实现 "先知先觉" 的风控。

**原作者**: [@frozenraspberry](https://x.com/frozenraspberry)

## 策略特性

### 1. CEX 价格引导 (CEX Price Leading)
机器人支持连接 Binance Futures WebSocket 获取实时价格 (BookTicker)。
*   **用途**：利用 CEX (Binance) 的数据来计算市场波动率，以及监控 **CEX/DEX 价差偏离**。
*   **优势**：CEX 价格通常领先 DEX 几秒，在 StandX 价格剧烈波动前提前撤单防御。

### 2. 双重熔断机制
*   **价差熔断 (Spread Guard)**: 
    *   实时计算 `abs(Binance - StandX)` 偏离度。
    *   如果偏离超过 `spread_threshold_bps` (默认20bps)，立即撤单并暂停。
    *   **日志记录**: 触发时会记录详细的 Binance 和 StandX 对比价格。
    *   **恢复机制**: 只有当偏离度回落至 `spread_recovery_bps` (默认10bps) 以下，并持续稳定 `spread_recovery_sec` (默认10秒) 后，才恢复挂单。
*   **断线熔断 (Staleness Guard)**: 
    *   如果 Binance 数据发生中断或延迟超过 5秒，机器人会自动识别 "致盲" 风险，强制撤销所有挂单并暂停运行，直到数据恢复。

### 3. 效率监测 (Efficiency Monitor) [新增]
*   **指标统计**: 机器人会自动统计挂单距离 Mark Price 的偏离度分布。
*   **定期报告**: 每 5 分钟在日志中输出一次效率报告，显示挂单在各区间的累积时长占比：
    *   Tier 1 (0-10bps): 最佳积分区间
    *   Tier 2 (10-30bps): 次佳区间
    *   Tier 3 (30-100bps): 低效区间
*   **日志优化**: 使用 `standx_bot.log` 文件记录，自动轮转（单文件最大10MB，保留5个备份），防止磁盘爆满。

### 4. 其他特性 (已包含)
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
binance_symbol: BTCUSDT  # 设置 Binance 对应交易对，启用 CEX 引导

# 挂单参数
order_distance_bps: 20
cancel_distance_bps: 10
rebalance_distance_bps: 30
order_size_btc: 0.01

# 仓位与安全
max_position_btc: 0.1
stop_loss_usd: 50.0

# 高级风控 - 价差熔断
spread_threshold_bps: 20     # 偏离超过 20bps 触发熔断
spread_recovery_bps: 10      # 偏离小于 10bps 允许尝试恢复
spread_recovery_sec: 10      # 需持续满足恢复条件 10秒

# 高级风控 - 其他
binance_staleness_sec: 5.0   # Binance 数据最大允许延迟
taker_fee_rate: 0.0004
min_profit_bps: 2
fill_cooldown_sec: 10

# 恢复模式 (止损后)
stop_loss_cooldown_sec: 600
recovery_window_sec: 300     # 恢复前观察窗口
recovery_volatility_bps: 25  # 恢复阈值(波动率)
recovery_check_interval_sec: 300
```

## 运行

```bash
python main.py
```

## 工具

### 监控脚本
独立监控脚本 `monitor.py` (需单独配置)

### 延迟/价差测试
```bash
python check_spread.py  # 实时查看 CEX/DEX 价差
```

## 许可证

MIT License
