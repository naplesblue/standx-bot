# StandX Maker Bot

双边挂单做市机器人，通过价格监控和自动撤单避免成交。

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

- `wallet.private_key`: 你的 BSC 钱包私钥

## 运行

```bash
python main.py
```

使用自定义配置文件：

```bash
python main.py --config my_config.yaml
```

## 参数说明

| 参数                       | 说明                       |
| -------------------------- | -------------------------- |
| `order_distance_bps`       | 挂单距离 last_price 的 bps |
| `cancel_distance_bps`      | 价格靠近到这个距离时撤单   |
| `order_size_btc`           | 单笔挂单大小               |
| `max_position_btc`         | 最大持仓，超过停止做市     |
| `volatility_threshold_bps` | 波动率阈值，超过暂停挂单   |
