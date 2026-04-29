import logging
from dataclasses import dataclass

from config import Config
from modules.risk_manager import PositionParams, RiskManager
from modules.signal_generator import Signal
from modules.state_store import (
    PaperTradeRecord,
    close_paper_trade,
    get_open_paper_trades,
    mark_signal_acted,
    open_paper_trade,
)

logger = logging.getLogger(__name__)

# Simulate realistic trading costs
SLIPPAGE_PCT = 0.05   # 0.05% slippage on entry
TAKER_FEE_PCT = 0.04  # 0.04% taker fee per side


@dataclass
class ClosedTrade:
    trade_id: int
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    pnl_usdt: float
    pnl_pct: float
    status: str  # CLOSED_TP, CLOSED_SL


class PaperTrader:
    """
    Simulates trade execution against real market prices.
    Tracks virtual P&L without touching real money.
    """

    def __init__(self) -> None:
        self._risk_manager = RiskManager()
        self._balance = Config.PAPER_BALANCE
        self._initial_balance = Config.PAPER_BALANCE

    @property
    def balance(self) -> float:
        return self._balance

    def open_position(self, signal: Signal) -> int:
        """Open a simulated position. Returns the paper trade database ID."""
        if self._count_open_positions() >= Config.MAX_OPEN_POSITIONS:
            logger.warning("Max open positions (%d) reached — skipping %s", Config.MAX_OPEN_POSITIONS, signal.symbol)
            return -1

        # Get ATR% for position sizing
        primary_tf = "1h" if "1h" in signal.indicators else list(signal.indicators.keys())[0]
        atr_pct = signal.indicators[primary_tf].get("atr_pct", 1.0) or 1.0

        params: PositionParams = self._risk_manager.calculate(
            entry_price=signal.entry_price,
            direction=signal.decision,
            sl_pct=signal.sl_pct,
            tp_pct=signal.tp_pct,
            account_balance=self._balance,
            atr_pct=atr_pct,
        )

        # Apply simulated slippage to entry
        if signal.decision == "LONG":
            actual_entry = signal.entry_price * (1 + SLIPPAGE_PCT / 100)
        else:
            actual_entry = signal.entry_price * (1 - SLIPPAGE_PCT / 100)

        record = PaperTradeRecord(
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            direction=signal.decision,
            entry_price=actual_entry,
            quantity=params.quantity,
            leverage=params.leverage,
            sl_price=params.sl_price,
            tp_price=params.tp_price,
        )

        trade_id = open_paper_trade(record)
        mark_signal_acted(signal.signal_id)

        # Deduct opening fee from virtual balance
        fee = params.notional_usdt * (TAKER_FEE_PCT / 100)
        self._balance -= fee

        logger.info(
            "Paper trade opened: id=%d %s %s @ %.4f | qty=%.6f lev=%dx | "
            "SL=%.4f TP=%.4f | fee=%.4f USDT | balance=%.2f USDT",
            trade_id, signal.symbol, signal.decision, actual_entry,
            params.quantity, params.leverage, params.sl_price, params.tp_price,
            fee, self._balance,
        )

        return trade_id

    def check_exits(self, current_prices: dict[str, float]) -> list[ClosedTrade]:
        """Check all open paper trades against current prices and close those that hit SL/TP."""
        open_trades = get_open_paper_trades()
        closed: list[ClosedTrade] = []

        for trade in open_trades:
            symbol = trade["symbol"]
            price = current_prices.get(symbol)
            if price is None:
                continue

            direction = trade["direction"]
            sl_price = trade["sl_price"]
            tp_price = trade["tp_price"]
            entry_price = trade["entry_price"]
            quantity = trade["quantity"]
            leverage = trade["leverage"]

            status = None
            exit_price = None

            if direction == "LONG":
                if price <= sl_price:
                    status = "CLOSED_SL"
                    exit_price = sl_price
                elif price >= tp_price:
                    status = "CLOSED_TP"
                    exit_price = tp_price
            else:  # SHORT
                if price >= sl_price:
                    status = "CLOSED_SL"
                    exit_price = sl_price
                elif price <= tp_price:
                    status = "CLOSED_TP"
                    exit_price = tp_price

            if status and exit_price:
                pnl_usdt, pnl_pct = self._compute_pnl(
                    direction, entry_price, exit_price, quantity, leverage
                )
                self._balance += pnl_usdt

                # Deduct closing fee
                fee = quantity * exit_price * (TAKER_FEE_PCT / 100)
                self._balance -= fee
                pnl_usdt -= fee

                close_paper_trade(trade["id"], exit_price, status, pnl_usdt, pnl_pct)

                closed.append(ClosedTrade(
                    trade_id=trade["id"],
                    symbol=symbol,
                    direction=direction,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl_usdt=pnl_usdt,
                    pnl_pct=pnl_pct,
                    status=status,
                ))

                logger.info(
                    "Paper trade closed: id=%d %s %s | %s @ %.4f | PnL=%.2f USDT (%.2f%%) | balance=%.2f USDT",
                    trade["id"], symbol, direction, status, exit_price, pnl_usdt, pnl_pct, self._balance,
                )

        return closed

    def _compute_pnl(
        self,
        direction: str,
        entry_price: float,
        exit_price: float,
        quantity: float,
        leverage: int,
    ) -> tuple[float, float]:
        if direction == "LONG":
            pnl_pct = (exit_price - entry_price) / entry_price * 100 * leverage
            pnl_usdt = (exit_price - entry_price) * quantity * leverage
        else:
            pnl_pct = (entry_price - exit_price) / entry_price * 100 * leverage
            pnl_usdt = (entry_price - exit_price) * quantity * leverage

        return round(pnl_usdt, 4), round(pnl_pct, 3)

    def _count_open_positions(self) -> int:
        return len(get_open_paper_trades())

    def get_summary(self) -> dict:
        return {
            "balance": round(self._balance, 2),
            "initial_balance": self._initial_balance,
            "total_pnl_usdt": round(self._balance - self._initial_balance, 2),
            "total_pnl_pct": round((self._balance / self._initial_balance - 1) * 100, 2),
            "open_positions": self._count_open_positions(),
        }
