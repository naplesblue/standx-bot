"""Configuration loader for StandX Maker Bot."""
import yaml
from pathlib import Path
from dataclasses import dataclass


@dataclass
class WalletConfig:
    chain: str
    private_key: str


@dataclass
class Config:
    wallet: WalletConfig
    symbol: str
    order_distance_bps: int
    cancel_distance_bps: int
    rebalance_distance_bps: int
    order_size_btc: float
    max_position_btc: float
    volatility_window_sec: int
    volatility_threshold_bps: int
    max_skew_bps: int = 0
    stop_loss_usd: float = 0.0
    taker_fee_rate: float = 0.0004
    min_profit_bps: int = 2
    fill_cooldown_sec: int = 10
    volatility_pause_sec: int = 30
    recovery_window_sec: int = 300
    recovery_volatility_bps: int = 25
    stop_loss_cooldown_sec: int = 600
    recovery_check_interval_sec: int = 300
    binance_symbol: str = None
    binance_staleness_sec: float = 5.0
    
    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        return cls(
            wallet=WalletConfig(**data["wallet"]),
            symbol=data["symbol"],
            order_distance_bps=data["order_distance_bps"],
            cancel_distance_bps=data["cancel_distance_bps"],
            rebalance_distance_bps=data.get("rebalance_distance_bps", 20),
            order_size_btc=data["order_size_btc"],
            max_position_btc=data["max_position_btc"],
            volatility_window_sec=data["volatility_window_sec"],
            volatility_threshold_bps=data["volatility_threshold_bps"],
            max_skew_bps=data.get("max_skew_bps", 0),
            stop_loss_usd=data.get("stop_loss_usd", 0.0),
            taker_fee_rate=data.get("taker_fee_rate", 0.0004),
            min_profit_bps=data.get("min_profit_bps", 2),
            fill_cooldown_sec=data.get("fill_cooldown_sec", 10),
            volatility_pause_sec=data.get("volatility_pause_sec", 30),
            recovery_window_sec=data.get("recovery_window_sec", 300),
            recovery_volatility_bps=data.get("recovery_volatility_bps", 25),
            stop_loss_cooldown_sec=data.get("stop_loss_cooldown_sec", 600),
            recovery_check_interval_sec=data.get("recovery_check_interval_sec", 300),
            binance_symbol=data.get("binance_symbol"),
            binance_staleness_sec=data.get("binance_staleness_sec", 5.0),
        )


def load_config(path: str = "config.yaml") -> Config:
    """Load configuration from YAML file."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    return Config.from_dict(data)
