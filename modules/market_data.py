import logging
import time
from functools import lru_cache
from typing import Optional

import ccxt
import pandas as pd

from config import Config

logger = logging.getLogger(__name__)

# Binance OHLCV column names
OHLCV_COLS = ["timestamp", "open", "high", "low", "close", "volume"]


def _build_exchange() -> ccxt.Exchange:
    params: dict = {
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
    }
    if Config.BINANCE_API_KEY:
        params["apiKey"] = Config.BINANCE_API_KEY
        params["secret"] = Config.BINANCE_API_SECRET

    exchange = ccxt.binance(params)

    if Config.BINANCE_TESTNET:
        exchange.set_sandbox_mode(True)

    return exchange


class MarketData:
    """Fetches OHLCV candlestick data and live prices from Binance via ccxt."""

    def __init__(self) -> None:
        self._exchange = _build_exchange()
        self._price_cache: dict[str, tuple[float, float]] = {}  # symbol → (price, ts)
        self._price_ttl = 5.0  # seconds

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        """Return OHLCV DataFrame for the given symbol and timeframe."""
        try:
            raw = self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        except ccxt.NetworkError as e:
            logger.warning("Network error fetching %s %s: %s — retrying once", symbol, timeframe, e)
            time.sleep(2)
            raw = self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

        df = pd.DataFrame(raw, columns=OHLCV_COLS)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.set_index("timestamp").astype(float)
        return df

    def fetch_all_timeframes(self, symbol: str) -> dict[str, pd.DataFrame]:
        """Return OHLCV DataFrames for all configured timeframes."""
        result: dict[str, pd.DataFrame] = {}
        for tf in Config.TIMEFRAMES:
            result[tf] = self.fetch_ohlcv(symbol, tf)
            logger.debug("Fetched %d candles for %s %s", len(result[tf]), symbol, tf)
        return result

    def get_current_price(self, symbol: str) -> float:
        """Return the latest mark price, with a short TTL cache."""
        now = time.time()
        cached_price, cached_ts = self._price_cache.get(symbol, (0.0, 0.0))
        if cached_price and (now - cached_ts) < self._price_ttl:
            return cached_price

        try:
            ticker = self._exchange.fetch_ticker(symbol)
            price = float(ticker["last"])
        except Exception as e:
            logger.error("Failed to fetch price for %s: %s", symbol, e)
            # Fall back to last candle close if available
            if cached_price:
                return cached_price
            raise

        self._price_cache[symbol] = (price, now)
        return price

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        """Batch fetch prices for multiple symbols."""
        return {sym: self.get_current_price(sym) for sym in symbols}
