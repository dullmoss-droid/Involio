import logging
from dataclasses import dataclass

from config import Config

logger = logging.getLogger(__name__)


@dataclass
class PositionParams:
    quantity: float      # in base asset units
    leverage: int
    sl_price: float
    tp_price: float
    notional_usdt: float # total position value


class RiskManager:
    """
    Calculates position size, stop loss, and take profit based on:
    - Account balance and RISK_PER_TRADE %
    - ATR-derived volatility
    - Configured leverage limits
    """

    def calculate(
        self,
        entry_price: float,
        direction: str,         # LONG | SHORT
        sl_pct: float,          # stop loss distance in %
        tp_pct: float,          # take profit distance in %
        account_balance: float,
        atr_pct: float = 1.0,   # ATR as % of price (from technical analysis)
    ) -> PositionParams:
        """
        Compute position parameters for a new trade.

        sl_pct and tp_pct come from the AI recommendation but are floor-bounded
        by a minimum (1× ATR%) to avoid stops that are too tight.
        """
        # Ensure SL is at least 1× ATR from entry to avoid premature stops
        effective_sl_pct = max(sl_pct, atr_pct * 1.0)
        effective_tp_pct = max(tp_pct, effective_sl_pct * 2)  # minimum 1:2 R:R

        # Risk in USDT = balance × risk_per_trade%
        risk_usdt = account_balance * (Config.RISK_PER_TRADE / 100)

        # Position size: risk_usdt / (entry_price × sl_pct%)
        # With leverage: quantity = risk_usdt / (entry_price × sl_pct% / leverage)
        leverage = self._select_leverage(effective_sl_pct)
        sl_distance = entry_price * (effective_sl_pct / 100)
        quantity = (risk_usdt * leverage) / (entry_price * (effective_sl_pct / 100))
        notional = quantity * entry_price

        # SL/TP prices
        if direction == "LONG":
            sl_price = entry_price - sl_distance
            tp_price = entry_price + entry_price * (effective_tp_pct / 100)
        else:  # SHORT
            sl_price = entry_price + sl_distance
            tp_price = entry_price - entry_price * (effective_tp_pct / 100)

        logger.info(
            "Risk calc: entry=%.4f dir=%s SL=%.4f (%.1f%%) TP=%.4f (%.1f%%) "
            "qty=%.6f lev=%dx notional=%.2f USDT risk=%.2f USDT",
            entry_price, direction, sl_price, effective_sl_pct, tp_price, effective_tp_pct,
            quantity, leverage, notional, risk_usdt,
        )

        return PositionParams(
            quantity=round(quantity, 6),
            leverage=leverage,
            sl_price=round(sl_price, 6),
            tp_price=round(tp_price, 6),
            notional_usdt=round(notional, 2),
        )

    def _select_leverage(self, sl_pct: float) -> int:
        """
        Choose leverage inversely proportional to stop loss distance.
        Wider stops → lower leverage to keep risk constant.
        """
        if sl_pct <= 1.0:
            lev = 10
        elif sl_pct <= 2.0:
            lev = 7
        elif sl_pct <= 3.0:
            lev = 5
        elif sl_pct <= 5.0:
            lev = 3
        else:
            lev = 2

        return min(lev, Config.MAX_LEVERAGE)
