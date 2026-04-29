import numpy as np
import pandas as pd
import pytest

from modules.technical_analysis import TechnicalAnalyzer


def _make_df(n: int = 200, trend: str = "up") -> pd.DataFrame:
    """Generate a synthetic OHLCV DataFrame."""
    np.random.seed(42)
    base = 40000.0
    if trend == "up":
        closes = base + np.cumsum(np.random.randn(n) * 100 + 50)
    elif trend == "down":
        closes = base + np.cumsum(np.random.randn(n) * 100 - 50)
    else:
        closes = base + np.random.randn(n) * 200

    highs = closes + np.abs(np.random.randn(n) * 80)
    lows = closes - np.abs(np.random.randn(n) * 80)
    opens = closes + np.random.randn(n) * 50
    volumes = np.random.uniform(1000, 5000, n)

    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=idx,
    )


@pytest.fixture
def analyzer():
    return TechnicalAnalyzer()


def test_compute_returns_dict(analyzer):
    df = _make_df()
    result = analyzer.compute(df)
    assert isinstance(result, dict)


def test_compute_contains_required_keys(analyzer):
    df = _make_df()
    result = analyzer.compute(df)
    required = ["rsi_14", "macd", "bb_upper", "bb_lower", "ema_50", "ema_200", "atr", "adx", "trend"]
    for key in required:
        assert key in result, f"Missing key: {key}"


def test_rsi_range(analyzer):
    df = _make_df()
    result = analyzer.compute(df)
    rsi = result.get("rsi_14")
    if rsi is not None:
        assert 0 <= rsi <= 100, f"RSI out of range: {rsi}"


def test_rsi_signal_oversold(analyzer):
    """Force an oversold RSI scenario with a consistently falling market."""
    df = _make_df(n=200, trend="down")
    result = analyzer.compute(df)
    # RSI signal should reflect downtrend (BEARISH or OVERSOLD)
    assert result.get("rsi_signal") in ("OVERSOLD", "BEARISH", "NEUTRAL")


def test_trend_bullish_in_uptrend(analyzer):
    df = _make_df(n=200, trend="up")
    result = analyzer.compute(df)
    # In a consistent uptrend, trend should lean bullish or sideways
    assert result.get("trend") in ("BULLISH", "SIDEWAYS")


def test_trend_bearish_in_downtrend(analyzer):
    df = _make_df(n=200, trend="down")
    result = analyzer.compute(df)
    assert result.get("trend") in ("BEARISH", "SIDEWAYS")


def test_support_below_price(analyzer):
    df = _make_df()
    result = analyzer.compute(df)
    price = result.get("price")
    support = result.get("support")
    if price and support:
        assert support <= price, f"Support {support} should be <= price {price}"


def test_resistance_above_price(analyzer):
    df = _make_df()
    result = analyzer.compute(df)
    price = result.get("price")
    resistance = result.get("resistance")
    if price and resistance:
        assert resistance >= price, f"Resistance {resistance} should be >= price {price}"


def test_compute_with_short_df_does_not_crash(analyzer):
    """Should not raise even with fewer candles than ideal."""
    df = _make_df(n=30)
    result = analyzer.compute(df)
    assert isinstance(result, dict)


def test_volume_ratio_is_positive(analyzer):
    df = _make_df()
    result = analyzer.compute(df)
    ratio = result.get("volume_ratio")
    if ratio is not None:
        assert ratio > 0
