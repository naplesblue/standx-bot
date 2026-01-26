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
    order_distance_bps: float
    cancel_distance_bps: float
    rebalance_distance_bps: float
    order_size_btc: float
    max_position_btc: float
    volatility_window_sec: int
    volatility_threshold_bps: float
    order_distance_tight_min_bps: float = 0.0
    order_distance_tight_max_bps: float = 0.0
    order_distance_far_min_bps: float = 0.0
    order_distance_far_max_bps: float = 0.0
    cancel_distance_min_bps: float = 0.0
    cancel_distance_max_bps: float = 0.0
    max_skew_bps: float = 0
    stop_loss_usd: float = 0.0
    taker_fee_rate: float = 0.0004
    min_profit_bps: float = 2
    fill_cooldown_sec: int = 10
    maker_min_rest_sec: float = 3.0
    recovery_window_sec: int = 300
    recovery_volatility_bps: float = 25
    stop_loss_cooldown_sec: int = 600
    recovery_check_interval_sec: int = 300
    binance_symbol: str = None
    binance_staleness_sec: float = 5.0
    dex_staleness_sec: float = 5.0
    spread_threshold_bps: float = 20
    spread_warn_bps: float = 12
    spread_recovery_bps: float = 10
    spread_recovery_sec: int = 10
    
    # Advanced Risk Control
    amplitude_window_sec: int = 10
    amplitude_ratio_threshold: float = 0.5  # As ratio of order_distance
    amplitude_warn_ratio_threshold: float = 0.3
    velocity_check_window_sec: float = 1.0
    velocity_tick_threshold: int = 3
    velocity_warn_tick_threshold: int = 2
    volume_window_sec: int = 60
    volume_min_samples: int = 10
    volume_warn_ratio: float = 2.5
    volume_guard_ratio: float = 4.0
    risk_guard_cooldown_sec: int = 15
    risk_recovery_stable_sec: int = 15
    caution_other_side_enabled: bool = True
    telegram_bot_token: str = None
    telegram_chat_id: str = None
    
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
            order_distance_tight_min_bps=data.get("order_distance_tight_min_bps", data["order_distance_bps"]),
            order_distance_tight_max_bps=data.get("order_distance_tight_max_bps", data["order_distance_bps"]),
            order_distance_far_min_bps=data.get(
                "order_distance_far_min_bps",
                data.get("rebalance_distance_bps", data["order_distance_bps"]),
            ),
            order_distance_far_max_bps=data.get(
                "order_distance_far_max_bps",
                data.get("rebalance_distance_bps", data["order_distance_bps"]),
            ),
            cancel_distance_min_bps=data.get("cancel_distance_min_bps", data["cancel_distance_bps"]),
            cancel_distance_max_bps=data.get("cancel_distance_max_bps", data["cancel_distance_bps"]),
            max_skew_bps=data.get("max_skew_bps", 0),
            stop_loss_usd=data.get("stop_loss_usd", 0.0),
            taker_fee_rate=data.get("taker_fee_rate", 0.0004),
            min_profit_bps=data.get("min_profit_bps", 2),
            fill_cooldown_sec=data.get("fill_cooldown_sec", 10),
            maker_min_rest_sec=data.get("maker_min_rest_sec", 3.0),
            recovery_window_sec=data.get("recovery_window_sec", 300),
            recovery_volatility_bps=data.get("recovery_volatility_bps", 25),
            stop_loss_cooldown_sec=data.get("stop_loss_cooldown_sec", 600),
            recovery_check_interval_sec=data.get("recovery_check_interval_sec", 300),
            binance_symbol=data.get("binance_symbol"),
            binance_staleness_sec=data.get("binance_staleness_sec", 5.0),
            dex_staleness_sec=data.get("dex_staleness_sec", 5.0),
            spread_threshold_bps=data.get("spread_threshold_bps", 20),
            spread_warn_bps=data.get(
                "spread_warn_bps",
                max(0.0, data.get("spread_threshold_bps", 20) * 0.7),
            ),
            spread_recovery_bps=data.get("spread_recovery_bps", 10),
            spread_recovery_sec=data.get("spread_recovery_sec", 10),
            amplitude_window_sec=data.get("amplitude_window_sec", 10),
            amplitude_ratio_threshold=data.get("amplitude_ratio_threshold", 0.5),
            amplitude_warn_ratio_threshold=data.get(
                "amplitude_warn_ratio_threshold",
                data.get("amplitude_ratio_threshold", 0.5) * 0.6,
            ),
            velocity_check_window_sec=data.get("velocity_check_window_sec", 1.0),
            velocity_tick_threshold=data.get("velocity_tick_threshold", 3),
            velocity_warn_tick_threshold=data.get(
                "velocity_warn_tick_threshold",
                max(1, data.get("velocity_tick_threshold", 3) - 1),
            ),
            volume_window_sec=data.get("volume_window_sec", 60),
            volume_min_samples=data.get("volume_min_samples", 10),
            volume_warn_ratio=data.get("volume_warn_ratio", 2.5),
            volume_guard_ratio=data.get("volume_guard_ratio", 4.0),
            risk_guard_cooldown_sec=data.get("risk_guard_cooldown_sec", 15),
            risk_recovery_stable_sec=data.get(
                "risk_recovery_stable_sec",
                data.get("spread_recovery_sec", 15),
            ),
            caution_other_side_enabled=data.get("caution_other_side_enabled", True),
            telegram_bot_token=data.get("telegram_bot_token"),
            telegram_chat_id=data.get("telegram_chat_id"),
        )


def load_config(path: str = "config.yaml") -> Config:
    """Load configuration from YAML file."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    return Config.from_dict(data)
