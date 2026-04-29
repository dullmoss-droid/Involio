import json
import logging
from dataclasses import dataclass
from typing import Optional

import anthropic

from config import Config

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"

# ── System prompt (cached) ────────────────────────────────────────────────────
# This is the "knowledge base" sent with every request. Prompt caching makes
# repeated calls ~90% cheaper after the first one.
SYSTEM_PROMPT = """You are an expert cryptocurrency trading analyst with deep knowledge of technical analysis, market structure, and risk management. Your role is to analyze market data and recommend whether to open a LONG position, SHORT position, or stay neutral (HOLD) on a given cryptocurrency pair.

## Your Analytical Framework

### Trend Analysis (most important)
- **EMA structure**: Price above EMA200 = long-term bullish bias. EMA9 > EMA21 = short-term bullish momentum.
- **MACD**: Histogram crossing from negative to positive = bullish momentum shift. Divergence signals reversals.
- **ADX**: Values below 20 = weak trend (avoid directional trades). Above 40 = strong trend (trade with it).

### Momentum Signals
- **RSI(14)**:
  - < 30: Oversold → potential LONG opportunity
  - > 70: Overbought → potential SHORT opportunity
  - 30-45: Bearish zone, 55-70: Bullish zone
- **Stochastic RSI**: Confirms RSI signals. K crossing above D at low levels = bullish.
- **MACD histogram**: Rising histogram = strengthening momentum in that direction.

### Volatility Context
- **ATR%**: If ATR% > 3%, market is very volatile — require higher confidence. If < 0.5%, market is quiet — signals less reliable.
- **Bollinger Bands**: Price near lower band + oversold RSI = potential LONG. Price near upper band + overbought RSI = potential SHORT. Band squeeze (low BB width) = imminent breakout.

### Volume Confirmation
- **HIGH volume** (ratio > 1.5): Confirms the move — adds conviction to signals.
- **LOW volume** (ratio < 0.7): Warns of false breakout — reduce confidence.
- Always require volume confirmation for entries against the trend.

### Multi-Timeframe Analysis
You receive data for three timeframes:
1. **4h**: Macro trend — only trade in this direction unless the setup is exceptional.
2. **1h**: Primary trend — the main signal source.
3. **15m**: Entry timing — fine-tune the entry point.

Best setups: All three timeframes aligned in the same direction.
Good setups: 4h + 1h aligned, 15m showing entry signal.
Avoid: Trading against the 4h trend unless very strong reversal signals.

### Position Sizing Context
- Recommend **sl_pct** (stop loss %): Typically 1.5x–2x ATR% from entry.
- Recommend **tp_pct** (take profit %): Minimum 2:1 risk/reward (so tp_pct = 2 × sl_pct).

## Output Format
You must respond ONLY with valid JSON matching this exact structure:
```json
{
  "decision": "LONG | SHORT | HOLD",
  "confidence": <integer 0-100>,
  "reasoning": "<concise explanation of why you chose this direction, referencing specific indicator values>",
  "key_factors": ["<factor 1>", "<factor 2>", "<factor 3>"],
  "risk_factors": ["<risk 1>", "<risk 2>"],
  "suggested_sl_pct": <float>,
  "suggested_tp_pct": <float>
}
```

### Confidence Guidelines
- **80-100**: Near-perfect multi-timeframe alignment, strong volume, clear trend.
- **65-79**: Good setup but 1-2 conflicting signals or weak volume.
- **50-64**: Mixed signals, proceed only if risk is minimal.
- **< 50**: Always output HOLD — the setup is too uncertain.

Be conservative. It is always better to HOLD and miss a trade than to enter a poor setup."""


@dataclass
class TradingDecision:
    decision: str          # LONG, SHORT, HOLD
    confidence: int        # 0-100
    reasoning: str
    key_factors: list[str]
    risk_factors: list[str]
    suggested_sl_pct: float
    suggested_tp_pct: float


class AIDecisionEngine:
    """
    Uses the Claude API to analyze multi-timeframe technical indicators
    and produce a structured LONG/SHORT/HOLD decision with reasoning.
    """

    def __init__(self) -> None:
        if not Config.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is required for the AI decision engine.")
        self._client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

    def decide(
        self,
        symbol: str,
        current_price: float,
        indicators: dict[str, dict],  # keyed by timeframe: "15m", "1h", "4h"
    ) -> TradingDecision:
        """
        Send market data to Claude and parse its structured trading decision.
        """
        user_message = self._build_user_message(symbol, current_price, indicators)

        try:
            response = self._client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},  # prompt caching
                    }
                ],
                messages=[{"role": "user", "content": user_message}],
            )
        except anthropic.APIError as e:
            logger.error("Claude API error for %s: %s", symbol, e)
            raise

        raw_text = response.content[0].text.strip()
        logger.debug("Claude raw response for %s:\n%s", symbol, raw_text)

        decision = self._parse_response(raw_text, symbol)

        logger.info(
            "AI decision for %s: %s (confidence=%d%%) | %s",
            symbol,
            decision.decision,
            decision.confidence,
            decision.reasoning[:120],
        )

        return decision

    def _build_user_message(
        self,
        symbol: str,
        current_price: float,
        indicators: dict[str, dict],
    ) -> str:
        timeframes_data = {}
        for tf, ind in indicators.items():
            # Include only numeric/string values (exclude None) for cleaner context
            timeframes_data[tf] = {k: v for k, v in ind.items() if v is not None}

        payload = {
            "symbol": symbol,
            "current_price": current_price,
            "analysis_timeframes": timeframes_data,
        }

        return (
            f"Analyze the following market data for {symbol} and provide your trading decision.\n\n"
            f"```json\n{json.dumps(payload, indent=2)}\n```\n\n"
            "Respond ONLY with the JSON decision object."
        )

    def _parse_response(self, raw_text: str, symbol: str) -> TradingDecision:
        """Extract and validate the JSON decision from Claude's response."""
        # Strip markdown code blocks if present
        if "```" in raw_text:
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]

        try:
            data = json.loads(raw_text.strip())
        except json.JSONDecodeError as e:
            logger.error("Failed to parse Claude JSON for %s: %s\nRaw: %s", symbol, e, raw_text)
            return self._fallback_hold("JSON parse error")

        decision = str(data.get("decision", "HOLD")).upper()
        if decision not in ("LONG", "SHORT", "HOLD"):
            logger.warning("Unexpected decision value '%s' for %s — defaulting to HOLD", decision, symbol)
            decision = "HOLD"

        confidence = int(data.get("confidence", 0))
        confidence = max(0, min(100, confidence))

        # Safety guard: low confidence always becomes HOLD
        if confidence < 50 and decision != "HOLD":
            logger.warning("Confidence %d < 50 for %s — overriding to HOLD", confidence, symbol)
            decision = "HOLD"

        return TradingDecision(
            decision=decision,
            confidence=confidence,
            reasoning=str(data.get("reasoning", "")),
            key_factors=list(data.get("key_factors", [])),
            risk_factors=list(data.get("risk_factors", [])),
            suggested_sl_pct=float(data.get("suggested_sl_pct", 1.5)),
            suggested_tp_pct=float(data.get("suggested_tp_pct", 3.0)),
        )

    @staticmethod
    def _fallback_hold(reason: str) -> TradingDecision:
        return TradingDecision(
            decision="HOLD",
            confidence=0,
            reasoning=f"Fallback HOLD due to: {reason}",
            key_factors=[],
            risk_factors=[reason],
            suggested_sl_pct=1.5,
            suggested_tp_pct=3.0,
        )
