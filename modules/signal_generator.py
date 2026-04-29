import logging
import time
from dataclasses import dataclass
from typing import Optional

from config import Config
from modules.ai_decision_engine import AIDecisionEngine, TradingDecision
from modules.market_data import MarketData
from modules.state_store import SignalRecord, save_signal, get_open_paper_trades_for_symbol
from modules.technical_analysis import TechnicalAnalyzer

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    symbol: str
    decision: str          # LONG, SHORT
    confidence: int
    entry_price: float
    sl_pct: float
    tp_pct: float
    reasoning: str
    key_factors: list[str]
    risk_factors: list[str]
    signal_id: int         # database ID
    indicators: dict[str, dict]


class SignalGenerator:
    """
    Orchestrates: MarketData → TechnicalAnalyzer → AIDecisionEngine → validated Signal.
    Applies cooldown periods and open-position guards before emitting a signal.
    """

    def __init__(
        self,
        market_data: MarketData,
        analyzer: TechnicalAnalyzer,
        ai_engine: AIDecisionEngine,
    ) -> None:
        self._market = market_data
        self._analyzer = analyzer
        self._ai = ai_engine
        # symbol → timestamp of last acted-upon signal
        self._last_signal_ts: dict[str, float] = {}
        self._cooldown_seconds = 3600  # 1 hour between signals per symbol

    def generate(self, symbol: str) -> Optional[Signal]:
        """
        Run a full analysis cycle for one symbol.
        Returns a Signal if conditions are met, or None (HOLD / filtered).
        """
        logger.info("── Analyzing %s ──────────────────────────────────", symbol)

        # ── Fetch data ────────────────────────────────────────────────────────
        try:
            ohlcv_by_tf = self._market.fetch_all_timeframes(symbol)
            current_price = self._market.get_current_price(symbol)
        except Exception as e:
            logger.error("Market data error for %s: %s", symbol, e)
            return None

        # ── Compute indicators per timeframe ──────────────────────────────────
        indicators: dict[str, dict] = {}
        for tf, df in ohlcv_by_tf.items():
            try:
                indicators[tf] = self._analyzer.compute(df)
            except Exception as e:
                logger.error("TA computation error for %s %s: %s", symbol, tf, e)
                return None

        # ── AI decision ───────────────────────────────────────────────────────
        try:
            ai_result: TradingDecision = self._ai.decide(symbol, current_price, indicators)
        except Exception as e:
            logger.error("AI decision error for %s: %s", symbol, e)
            return None

        # ── Always persist the signal (even HOLDs) for auditing ──────────────
        primary_tf = Config.TIMEFRAMES[1] if len(Config.TIMEFRAMES) > 1 else Config.TIMEFRAMES[0]
        ind_15m = indicators.get("15m", indicators.get(Config.TIMEFRAMES[0], {}))
        ind_1h = indicators.get("1h", indicators.get(primary_tf, {}))
        ind_4h = indicators.get("4h", indicators.get(Config.TIMEFRAMES[-1], {}))

        record = SignalRecord(
            symbol=symbol,
            decision=ai_result.decision,
            confidence=ai_result.confidence,
            reasoning=ai_result.reasoning,
            key_factors=ai_result.key_factors,
            risk_factors=ai_result.risk_factors,
            entry_price=current_price,
            suggested_sl_pct=ai_result.suggested_sl_pct,
            suggested_tp_pct=ai_result.suggested_tp_pct,
            indicators_15m=ind_15m,
            indicators_1h=ind_1h,
            indicators_4h=ind_4h,
        )
        signal_id = save_signal(record)

        # ── Filter: HOLD decisions ────────────────────────────────────────────
        if ai_result.decision == "HOLD":
            logger.info("%s → HOLD (confidence=%d%%)", symbol, ai_result.confidence)
            return None

        # ── Filter: confidence threshold ──────────────────────────────────────
        if ai_result.confidence < Config.MIN_CONFIDENCE:
            logger.info(
                "%s → %s below min confidence (%d%% < %d%%) — skipped",
                symbol, ai_result.decision, ai_result.confidence, Config.MIN_CONFIDENCE,
            )
            return None

        # ── Filter: cooldown between signals ──────────────────────────────────
        last_ts = self._last_signal_ts.get(symbol, 0)
        if time.time() - last_ts < self._cooldown_seconds:
            remaining = int(self._cooldown_seconds - (time.time() - last_ts))
            logger.info("%s → %s skipped (cooldown: %ds remaining)", symbol, ai_result.decision, remaining)
            return None

        # ── Filter: already has an open position in this symbol ───────────────
        open_trades = get_open_paper_trades_for_symbol(symbol)
        if open_trades:
            logger.info("%s → %s skipped (already has %d open position(s))", symbol, ai_result.decision, len(open_trades))
            return None

        # ── Emit signal ───────────────────────────────────────────────────────
        self._last_signal_ts[symbol] = time.time()

        signal = Signal(
            symbol=symbol,
            decision=ai_result.decision,
            confidence=ai_result.confidence,
            entry_price=current_price,
            sl_pct=ai_result.suggested_sl_pct,
            tp_pct=ai_result.suggested_tp_pct,
            reasoning=ai_result.reasoning,
            key_factors=ai_result.key_factors,
            risk_factors=ai_result.risk_factors,
            signal_id=signal_id,
            indicators=indicators,
        )

        logger.info(
            "✓ SIGNAL: %s %s @ %.4f | confidence=%d%% | SL=%.1f%% TP=%.1f%%",
            symbol, signal.decision, current_price, signal.confidence, signal.sl_pct, signal.tp_pct,
        )

        return signal
