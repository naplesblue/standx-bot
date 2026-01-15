# StandX Maker Bot

StandX Maker Points 活动的双边挂单做市机器人。在 mark price 两侧挂限价单获取积分，价格靠近时自动撤单避免成交。

本版本加入了高级风控特性，包括波动率熔断、智能平仓与冷却机制。

**原作者**: [@frozenraspberry](https://x.com/frozenraspberry)

## 策略原理

StandX 的 Maker Points 活动奖励挂单行为：订单在盘口停留超过 3 秒即可获得积分，无需成交。本机器人通过：

1.  在 mark price 两侧按配置距离挂买卖单
2.  实时监控价格，价格靠近时撤单避免成交
3.  **波动率熔断**：高波动时自动暂停挂单
4.  **智能平仓**：若意外成交，优先使用 Limit 单（Maker）止盈平仓，赚取积分；仅在盈利覆盖手续费时使用 Market 单平仓。

## 新增特性 (Advanced Features)

### 1. 波动率熔断 (Volatility Guard)
当市场短期波动率（基于 n 秒内的最高/最低价振幅）超过设定阈值 `volatility_threshold_bps` 时，机器人将由 `volatility_pause_sec` 控制暂停挂单一段时间（默认 30秒）。这有效防止在 "插针" 行情中被有毒流量成交。

### 2. 冷却机制 (Cool-down)
每当发生一笔成交（Fill）后，机器人会强制进入冷却期 `fill_cooldown_sec`（默认 10秒）。这给予市场喘息时间，防止在单边趋势中连续接飞刀，导致瞬间满仓。

### 3. (Maker Exit) 智能做市平仓
当持有仓位时，机器人不再盲目等待原来的 Skew 调整。如果不触及紧急止损或激进止盈线，它会尝试在 `成本价 + Taker手续费 + 微利` 的位置挂出平仓单。
*   **优势**：把被套的 "事故" 转化为赚取 Maker 积分的 "机会"。

### 4. (Aggressive Profit Take) 激进止盈
如果持仓盈利（uPNL）超过了 `min_profit_usd`（足以覆盖 Taker 费），机器人会不再等待，**立即市价平仓**。这是为了快速释放仓位，回归无风险的挂单挖矿状态。

## 安装

```bash
pip install -r requirements.txt
```

## 配置

复制配置模板并填写钱包私钥：

```bash
cp config.example.yaml config.yaml
```

编辑 `config.yaml`：

```yaml
wallet:
  chain: bsc # bsc | solana
  private_key: "YOUR_PRIVATE_KEY_HERE"

symbol: BTC-USD

# 挂单参数（bps = 0.01%，即 10 bps = 0.1%）
order_distance_bps: 20       # 挂单距离 mark_price 的 bps
cancel_distance_bps: 10      # 价格靠近到这个距离时撤单（避免成交）
rebalance_distance_bps: 30   # 价格远离超过这个距离时撤单（重新挂更优价格）
order_size_btc: 0.01         # 单笔挂单大小

# 仓位控制
max_position_btc: 0.1        # 最大持仓（绝对值），超过停止做市
stop_loss_usd: 50.0          # 紧急止损（美元），亏损超过此值全平并停止

# 高级风控与平仓逻辑
max_skew_bps: 0              # 库存倾斜参数（0表示不倾斜，建议保持0）
taker_fee_rate: 0.0004       # 交易所 Taker 费率 (0.04%)
min_profit_bps: 2            # Maker Exit 追求的最小利润点 (bps)
min_profit_usd: 0.1          # 激进止盈触发的最小美元利润（需覆盖手续费）
fill_cooldown_sec: 10        # 成交后的冷却观察期（秒）
volatility_pause_sec: 30     # 波动率熔断后的暂停时间（秒）

# 波动率控制
volatility_window_sec: 5     # 观察窗口秒数
volatility_threshold_bps: 5  # 窗口内波动小于此值才允许挂单
```

## 运行

启动做市机器人：

```bash
python main.py
```

指定配置文件：

```bash
python main.py --config my_config.yaml
```

## 日志文件

程序运行时会生成以下日志文件（已在 `.gitignore` 中排除）：

| 文件                   | 说明                                           |
| ---------------------- | ---------------------------------------------- |
| `latency_<config>.log` | API 调用延迟记录，格式：`时间戳,接口,延迟毫秒` |
| `reduce_<config>.log`  | 减仓/平仓记录                                  |
| `status.log`           | 监控脚本的账户状态快照                         |

## 风险提示

1.  **私钥安全**：`config.yaml` 包含钱包私钥，请勿提交到公开仓库
2.  **做市风险**：本策略本质是赚取积分而非交易价差。在极端单边行情中，即使有风控，仍可能产生亏损。
3.  **作者不对使用本策略造成的任何损失负责**。建议先以极小资金（如 0.001 BTC）进行测试。

## 许可证

MIT License

使用本项目时请标明作者 Twitter: [@frozenraspberry](https://x.com/frozenraspberry)

---

免责声明：本软件仅供学习和研究使用。使用本软件进行交易的所有风险由使用者自行承担。作者不对任何交易损失负责。
