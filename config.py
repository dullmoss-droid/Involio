import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Required environment variable '{key}' is not set. Check your .env file.")
    return value


def _list(key: str, default: str) -> list[str]:
    return [s.strip() for s in os.getenv(key, default).split(",") if s.strip()]


class Config:
    # Binance
    BINANCE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
    BINANCE_API_SECRET: str = os.getenv("BINANCE_API_SECRET", "")
    BINANCE_TESTNET: bool = os.getenv("BINANCE_TESTNET", "true").lower() == "true"

    # Claude AI
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

    # Trading mode
    TRADING_MODE: str = os.getenv("TRADING_MODE", "paper")  # paper | live

    # Symbols & timeframes
    SYMBOLS: list[str] = _list("SYMBOLS", "BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT")
    TIMEFRAMES: list[str] = _list("TIMEFRAMES", "15m,1h,4h")

    # Bot parameters
    ANALYSIS_INTERVAL: int = int(os.getenv("ANALYSIS_INTERVAL", "300"))
    MIN_CONFIDENCE: int = int(os.getenv("MIN_CONFIDENCE", "70"))

    # Paper trading
    PAPER_BALANCE: float = float(os.getenv("PAPER_BALANCE", "10000"))

    # Risk management
    RISK_PER_TRADE: float = float(os.getenv("RISK_PER_TRADE", "1.0"))
    MAX_LEVERAGE: int = int(os.getenv("MAX_LEVERAGE", "10"))
    MAX_OPEN_POSITIONS: int = int(os.getenv("MAX_OPEN_POSITIONS", "5"))

    # Alerts
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")

    @classmethod
    def validate(cls) -> None:
        if not cls.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is required. Set it in your .env file.")
        if cls.TRADING_MODE == "live" and (not cls.BINANCE_API_KEY or not cls.BINANCE_API_SECRET):
            raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET are required for live trading.")
        if cls.TRADING_MODE not in ("paper", "live"):
            raise ValueError(f"TRADING_MODE must be 'paper' or 'live', got: '{cls.TRADING_MODE}'")
        if not cls.SYMBOLS:
            raise ValueError("SYMBOLS must contain at least one trading pair.")

    @classmethod
    def summary(cls) -> str:
        return (
            f"Mode: {cls.TRADING_MODE.upper()} | "
            f"Symbols: {', '.join(cls.SYMBOLS)} | "
            f"Timeframes: {', '.join(cls.TIMEFRAMES)} | "
            f"Interval: {cls.ANALYSIS_INTERVAL}s | "
            f"Min confidence: {cls.MIN_CONFIDENCE}% | "
            f"Risk/trade: {cls.RISK_PER_TRADE}%"
        )
