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
    order_size_btc: float
    max_position_btc: float
    volatility_window_sec: int
    volatility_threshold_bps: int
    loop_interval_sec: float
    
    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        return cls(
            wallet=WalletConfig(**data["wallet"]),
            symbol=data["symbol"],
            order_distance_bps=data["order_distance_bps"],
            cancel_distance_bps=data["cancel_distance_bps"],
            order_size_btc=data["order_size_btc"],
            max_position_btc=data["max_position_btc"],
            volatility_window_sec=data["volatility_window_sec"],
            volatility_threshold_bps=data["volatility_threshold_bps"],
            loop_interval_sec=data.get("loop_interval_sec", 1.0),
        )


def load_config(path: str = "config.yaml") -> Config:
    """Load configuration from YAML file."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    return Config.from_dict(data)
