import json
from unittest.mock import MagicMock, patch

import pytest

from modules.ai_decision_engine import AIDecisionEngine, TradingDecision


MOCK_LONG_RESPONSE = json.dumps({
    "decision": "LONG",
    "confidence": 82,
    "reasoning": "RSI oversold at 28, MACD bullish crossover, price above EMA200. Strong setup.",
    "key_factors": ["RSI oversold", "MACD bullish crossover", "Above EMA200"],
    "risk_factors": ["Low ADX (weak trend)"],
    "suggested_sl_pct": 1.8,
    "suggested_tp_pct": 3.6,
})

MOCK_SHORT_RESPONSE = json.dumps({
    "decision": "SHORT",
    "confidence": 75,
    "reasoning": "RSI overbought at 78, price at upper Bollinger Band, MACD bearish divergence.",
    "key_factors": ["RSI overbought", "Upper BB touch", "MACD bearish"],
    "risk_factors": ["Strong uptrend on 4h"],
    "suggested_sl_pct": 2.0,
    "suggested_tp_pct": 4.0,
})

MOCK_HOLD_RESPONSE = json.dumps({
    "decision": "HOLD",
    "confidence": 45,
    "reasoning": "Mixed signals. No clear directional bias.",
    "key_factors": ["Mixed timeframes"],
    "risk_factors": ["Low ADX", "No volume confirmation"],
    "suggested_sl_pct": 1.5,
    "suggested_tp_pct": 3.0,
})

SAMPLE_INDICATORS = {
    "15m": {"rsi_14": 35, "macd_crossover": "BULLISH", "trend": "BULLISH", "atr_pct": 0.8},
    "1h": {"rsi_14": 42, "macd_crossover": "BULLISH_CROSS", "above_ema200": True, "trend": "BULLISH"},
    "4h": {"rsi_14": 50, "trend": "SIDEWAYS", "adx": 25},
}


def _make_mock_response(text: str):
    mock_content = MagicMock()
    mock_content.text = text
    mock_response = MagicMock()
    mock_response.content = [mock_content]
    return mock_response


@pytest.fixture
def engine():
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-key"}):
        from config import Config
        Config.ANTHROPIC_API_KEY = "sk-test-key"
        return AIDecisionEngine()


def test_decide_returns_long(engine):
    with patch.object(engine._client.messages, "create", return_value=_make_mock_response(MOCK_LONG_RESPONSE)):
        result = engine.decide("BTC/USDT", 42000.0, SAMPLE_INDICATORS)

    assert isinstance(result, TradingDecision)
    assert result.decision == "LONG"
    assert result.confidence == 82
    assert len(result.key_factors) == 3
    assert result.suggested_sl_pct == 1.8
    assert result.suggested_tp_pct == 3.6


def test_decide_returns_short(engine):
    with patch.object(engine._client.messages, "create", return_value=_make_mock_response(MOCK_SHORT_RESPONSE)):
        result = engine.decide("ETH/USDT", 3200.0, SAMPLE_INDICATORS)

    assert result.decision == "SHORT"
    assert result.confidence == 75


def test_decide_returns_hold(engine):
    with patch.object(engine._client.messages, "create", return_value=_make_mock_response(MOCK_HOLD_RESPONSE)):
        result = engine.decide("SOL/USDT", 150.0, SAMPLE_INDICATORS)

    assert result.decision == "HOLD"
    assert result.confidence == 45


def test_low_confidence_overridden_to_hold(engine):
    """Confidence < 50 on a LONG/SHORT must be overridden to HOLD."""
    low_conf = json.dumps({
        "decision": "LONG",
        "confidence": 35,
        "reasoning": "Weak setup",
        "key_factors": [],
        "risk_factors": [],
        "suggested_sl_pct": 1.5,
        "suggested_tp_pct": 3.0,
    })
    with patch.object(engine._client.messages, "create", return_value=_make_mock_response(low_conf)):
        result = engine.decide("BNB/USDT", 500.0, SAMPLE_INDICATORS)

    assert result.decision == "HOLD"


def test_malformed_json_returns_hold(engine):
    """If Claude returns invalid JSON, fall back to HOLD without crashing."""
    with patch.object(engine._client.messages, "create", return_value=_make_mock_response("not valid json !!!")):
        result = engine.decide("BTC/USDT", 42000.0, SAMPLE_INDICATORS)

    assert result.decision == "HOLD"
    assert result.confidence == 0


def test_unknown_decision_defaults_to_hold(engine):
    unknown = json.dumps({
        "decision": "MAYBE",
        "confidence": 80,
        "reasoning": "Unknown",
        "key_factors": [],
        "risk_factors": [],
        "suggested_sl_pct": 1.5,
        "suggested_tp_pct": 3.0,
    })
    with patch.object(engine._client.messages, "create", return_value=_make_mock_response(unknown)):
        result = engine.decide("BTC/USDT", 42000.0, SAMPLE_INDICATORS)

    assert result.decision == "HOLD"


def test_markdown_code_block_stripped(engine):
    """Claude sometimes wraps JSON in ```json ``` — must parse correctly."""
    wrapped = f"```json\n{MOCK_LONG_RESPONSE}\n```"
    with patch.object(engine._client.messages, "create", return_value=_make_mock_response(wrapped)):
        result = engine.decide("BTC/USDT", 42000.0, SAMPLE_INDICATORS)

    assert result.decision == "LONG"
