import pytest

from modules.paper_trader import PaperTrader
from modules.signal_generator import Signal
from modules.state_store import initialize_db


SAMPLE_INDICATORS = {
    "1h": {"atr_pct": 1.0, "rsi_14": 40, "trend": "BULLISH"},
}


def _make_signal(symbol="BTC/USDT", decision="LONG", confidence=80, entry=42000.0, signal_id=1) -> Signal:
    return Signal(
        symbol=symbol,
        decision=decision,
        confidence=confidence,
        entry_price=entry,
        sl_pct=1.5,
        tp_pct=3.0,
        reasoning="Test signal",
        key_factors=["RSI oversold"],
        risk_factors=[],
        signal_id=signal_id,
        indicators=SAMPLE_INDICATORS,
    )


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Use a fresh in-memory-like SQLite for each test."""
    import modules.state_store as ss
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setattr(ss, "DB_PATH", db_path)
    initialize_db()


@pytest.fixture
def trader():
    from config import Config
    Config.PAPER_BALANCE = 10000.0
    Config.RISK_PER_TRADE = 1.0
    Config.MAX_LEVERAGE = 10
    Config.MAX_OPEN_POSITIONS = 5
    return PaperTrader()


def test_initial_balance(trader):
    assert trader.balance == 10000.0


def test_open_long_position(trader):
    signal = _make_signal(decision="LONG", signal_id=1)
    trade_id = trader.open_position(signal)
    assert trade_id > 0
    assert trader.balance < 10000.0  # fee deducted


def test_open_short_position(trader):
    signal = _make_signal(decision="SHORT", signal_id=2)
    trade_id = trader.open_position(signal)
    assert trade_id > 0


def test_tp_hit_long(trader):
    """Simulate a LONG position hitting take profit."""
    signal = _make_signal(decision="LONG", entry=42000.0, signal_id=3)
    trader.open_position(signal)

    # Price rises above TP
    tp_price = 42000.0 * (1 + 3.0 / 100) + 100
    closed = trader.check_exits({"BTC/USDT": tp_price})

    assert len(closed) == 1
    assert closed[0].status == "CLOSED_TP"
    assert closed[0].pnl_usdt > 0


def test_sl_hit_long(trader):
    """Simulate a LONG position hitting stop loss."""
    signal = _make_signal(decision="LONG", entry=42000.0, signal_id=4)
    trader.open_position(signal)

    sl_price = 42000.0 * (1 - 1.5 / 100) - 100
    closed = trader.check_exits({"BTC/USDT": sl_price})

    assert len(closed) == 1
    assert closed[0].status == "CLOSED_SL"
    assert closed[0].pnl_usdt < 0


def test_tp_hit_short(trader):
    """Simulate a SHORT position hitting take profit (price drops)."""
    signal = _make_signal(decision="SHORT", entry=42000.0, signal_id=5)
    trader.open_position(signal)

    tp_price = 42000.0 * (1 - 3.0 / 100) - 100
    closed = trader.check_exits({"BTC/USDT": tp_price})

    assert len(closed) == 1
    assert closed[0].status == "CLOSED_TP"
    assert closed[0].pnl_usdt > 0


def test_no_close_when_price_unchanged(trader):
    signal = _make_signal(signal_id=6)
    trader.open_position(signal)

    # Price at entry — should not close
    closed = trader.check_exits({"BTC/USDT": 42000.0})
    assert len(closed) == 0


def test_max_positions_respected(trader):
    from config import Config
    Config.MAX_OPEN_POSITIONS = 2

    s1 = _make_signal(symbol="BTC/USDT", signal_id=10, entry=42000.0)
    s2 = _make_signal(symbol="ETH/USDT", signal_id=11, entry=3200.0)
    s3 = _make_signal(symbol="SOL/USDT", signal_id=12, entry=150.0)

    trader.open_position(s1)
    trader.open_position(s2)
    result = trader.open_position(s3)  # should be blocked

    assert result == -1


def test_get_summary_structure(trader):
    summary = trader.get_summary()
    assert "balance" in summary
    assert "total_pnl_usdt" in summary
    assert "total_pnl_pct" in summary
    assert "open_positions" in summary
