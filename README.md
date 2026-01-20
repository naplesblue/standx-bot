# StandX Maker Bot

StandX Maker Points 活动的双边挂单做市机器人。在 mark price 两侧挂限价单获取积分，价格靠近时自动撤单避免成交。

本版本加入 CEX 价格引导功能，利用 Binance 数据提前感知市场波动，实现 "先知先觉" 的风控。

## 策略特性

### 1. CEX 价格引导 (CEX Price Leading)
机器人支持连接 Binance Futures WebSocket 获取实时价格 (BookTicker)。
*   **用途**：利用 CEX (Binance) 的数据来计算市场波动率，以及监控 **CEX/DEX 价差偏离**。
*   **优势**：CEX 价格通常领先 DEX 几秒，在 StandX 价格剧烈波动前提前撤单防御。

### 2. 三重熔断机制 (Advanced Risk Control)
*   **价差熔断 (Spread Guard)**: 
    *   实时计算 `abs(Binance - StandX)` 偏离度。如果偏离超过阈值，暂停交易。
*   **波幅熔断 (Realized Amplitude Guard)** [新增]:
    *   监控 Binance 过去 10秒 的 **真实波幅** `(Max-Min)/Mid`。
    *   如果波幅超过设定的阈值 (如挂单距离的 50%)，意味着 CEX 剧烈震荡，立即暂停。
*   **趋势熔断 (Price Velocity Guard)** [新增]:
    *   监控价格变动速率。如果 1秒 内连续出现 3次 同方向跳变，视为单边行情启动，提前预警暂停。
*   **断线熔断 (Staleness Guard)**: 
    *   监测 Binance 数据新鲜度，延迟超标自动熔断。


### 3. 效率监测 (Efficiency Monitor) [新增]
*   **指标统计**: 机器人会自动统计挂单距离 Mark Price 的偏离度分布。
*   **定期报告**: 每 5 分钟在日志(`efficiency.log`)中输出报告，包含：
    *   Tier 1 (0-10bps): 最佳积分区间占比
    *   Tier 2 (10-30bps): 次佳区间占比
    *   Tier 3 (30-100bps): 低效区间占比
    *   **Stats**: 统计周期内的 **下单数(Orders)**、**撤单数(Cancels)**、**成交数(Fills)**。
    *   **PnL**: 实时统计 **已实现盈亏 (Realized PnL)** 和 **交易手续费 (Fees Paid)**。
    *   **精准统计**: 修复了漏单问题，现支持统计 **部分成交 (Partial Fills)** 和 **仓位变动** 推断成交。
*   **日志优化**: 自动轮转（单文件最大10MB，保留5个备份），防止磁盘爆满。

### 4. 远程监控 (Telegram Bot) [升级]
配置 Telegram 后，机器人支持两项功能：
1.  **自动推送**: 每 6 小时自动推送效率报告（配合 Cron 脚本）。
2.  **交互查询**: 在 Telegram Bot 发送 `/status` 指令，机器人会立即回复过去 4 小时的效率汇总。
    *   **安全保护**: 仅响应 `config.yaml` 中配置的 `telegram_chat_id` 用户的指令，拒绝 unauthorized 访问。

**配置**:
在 `config.yaml` 中添加：
```yaml
telegram_bot_token: "YOUR_BOT_TOKEN"
telegram_chat_id: "YOUR_CHAT_ID"
```

**运行自动推送 (Crontab)**:
```bash
python report_efficiency.py --hours 6
```

### 5. 其他特性 (已包含)
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

# ⚠️ 高级风控 - 波幅与趋势 [新增]
# 支持小数位设置 (e.g. 9.5)
amplitude_window_sec: 10          # 波幅计算窗口
amplitude_ratio_threshold: 0.5    # 波幅阈值 (Order_Distance 的倍数)
velocity_check_window_sec: 1.0    # 趋势计算窗口
velocity_tick_threshold: 3        # 触发趋势预警的连续 Tick 数

# 恢复模式 (止损后)
stop_loss_cooldown_sec: 600
recovery_window_sec: 300     # 恢复前观察窗口
recovery_volatility_bps: 25  # 恢复阈值(波动率)
recovery_check_interval_sec: 300

# 消息通知 (Telegram)
webhook_url: ""              # (Legacy) 通用 Webhook URL
telegram_bot_token: ""       # Telegram Bot Token (从 BotFather 获取)
telegram_chat_id: ""         # Telegram Chat ID (接收通知的用户 ID)
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

**原作者**: [@frozenraspberry](https://x.com/frozenraspberry)