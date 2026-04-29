import logging
from dataclasses import dataclass

import ccxt

from config import Config
from modules.risk_manager import PositionParams, RiskManager
from modules.signal_generator import Signal
from modules.state_store import mark_signal_acted

logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    order_id: str
    symbol: str
    direction: str
    entry_price: float
    quantity: float
    leverage: int
    sl_price: float
    tp_price: float
    raw: dict


class ExchangeExecutor:
    """
    Executes real trades on Binance USDM Futures.
    Only active when TRADING_MODE=live.
    """

    def __init__(self) -> None:
        if Config.TRADING_MODE != "live":
            raise RuntimeError("ExchangeExecutor instantiated in non-live mode. Use PaperTrader instead.")

        self._exchange = ccxt.binance({
            "apiKey": Config.BINANCE_API_KEY,
            "secret": Config.BINANCE_API_SECRET,
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })

        if Config.BINANCE_TESTNET:
            self._exchange.set_sandbox_mode(True)

        self._risk_manager = RiskManager()

    def get_account_balance(self) -> float:
        """Return available USDT balance in futures wallet."""
        balance = self._exchange.fetch_balance()
        return float(balance["USDT"]["free"])

    def open_position(self, signal: Signal) -> OrderResult:
        """Open a leveraged long or short position with bracket (SL + TP) orders."""
        balance = self.get_account_balance()

        primary_tf = "1h" if "1h" in signal.indicators else list(signal.indicators.keys())[0]
        atr_pct = signal.indicators[primary_tf].get("atr_pct", 1.0) or 1.0

        params: PositionParams = self._risk_manager.calculate(
            entry_price=signal.entry_price,
            direction=signal.decision,
            sl_pct=signal.sl_pct,
            tp_pct=signal.tp_pct,
            account_balance=balance,
            atr_pct=atr_pct,
        )

        # Set leverage
        self._exchange.set_leverage(params.leverage, signal.symbol)

        side = "buy" if signal.decision == "LONG" else "sell"
        opposite_side = "sell" if signal.decision == "LONG" else "buy"

        # Market entry order
        entry_order = self._exchange.create_order(
            symbol=signal.symbol,
            type="market",
            side=side,
            amount=params.quantity,
        )
        entry_price = float(entry_order.get("average") or entry_order.get("price") or signal.entry_price)

        # Stop loss order
        sl_order = self._exchange.create_order(
            symbol=signal.symbol,
            type="stop_market",
            side=opposite_side,
            amount=params.quantity,
            params={"stopPrice": params.sl_price, "reduceOnly": True},
        )

        # Take profit order
        tp_order = self._exchange.create_order(
            symbol=signal.symbol,
            type="take_profit_market",
            side=opposite_side,
            amount=params.quantity,
            params={"stopPrice": params.tp_price, "reduceOnly": True},
        )

        mark_signal_acted(signal.signal_id)

        result = OrderResult(
            order_id=str(entry_order["id"]),
            symbol=signal.symbol,
            direction=signal.decision,
            entry_price=entry_price,
            quantity=params.quantity,
            leverage=params.leverage,
            sl_price=params.sl_price,
            tp_price=params.tp_price,
            raw={"entry": entry_order, "sl": sl_order, "tp": tp_order},
        )

        logger.info(
            "Live order placed: %s %s @ %.4f | qty=%.6f lev=%dx | SL=%.4f TP=%.4f",
            signal.symbol, signal.decision, entry_price,
            params.quantity, params.leverage, params.sl_price, params.tp_price,
        )

        return result

    def close_position(self, symbol: str, quantity: float, direction: str) -> dict:
        """Manually close an open position at market price."""
        side = "sell" if direction == "LONG" else "buy"
        order = self._exchange.create_order(
            symbol=symbol,
            type="market",
            side=side,
            amount=quantity,
            params={"reduceOnly": True},
        )
        logger.info("Closed live position: %s %s qty=%.6f", symbol, direction, quantity)
        return order
