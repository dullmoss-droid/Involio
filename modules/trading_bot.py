import asyncio
import logging
import time
from typing import Optional

from config import Config
from modules.ai_decision_engine import AIDecisionEngine
from modules.alerting_module import AlertingModule
from modules.market_data import MarketData
from modules.paper_trader import PaperTrader
from modules.signal_generator import Signal, SignalGenerator
from modules.state_store import get_paper_portfolio_summary, initialize_db, log_event
from modules.technical_analysis import TechnicalAnalyzer

logger = logging.getLogger(__name__)

POSITION_CHECK_INTERVAL = 30   # seconds between SL/TP checks
SUMMARY_INTERVAL = 3600        # send portfolio summary every hour


class TradingBot:
    """
    Main async orchestrator.

    Loop A (analysis): every ANALYSIS_INTERVAL seconds, analyze each symbol
                        and emit signals → open positions if actionable.
    Loop B (monitor):  every POSITION_CHECK_INTERVAL seconds, check SL/TP
                        on all open paper positions.
    Loop C (summary):  every SUMMARY_INTERVAL seconds, send portfolio summary.
    """

    def __init__(self) -> None:
        self._market = MarketData()
        self._analyzer = TechnicalAnalyzer()
        self._ai = AIDecisionEngine()
        self._signal_gen = SignalGenerator(self._market, self._analyzer, self._ai)
        self._paper_trader = PaperTrader() if Config.TRADING_MODE == "paper" else None
        self._alerting = AlertingModule()
        self._running = False

    async def run(self) -> None:
        logger.info("Initializing database...")
        initialize_db()

        logger.info("Trading bot starting | %s", Config.summary())
        self._alerting.bot_started_alert(Config.summary())
        self._running = True

        try:
            await asyncio.gather(
                self._analysis_loop(),
                self._monitor_loop(),
                self._summary_loop(),
            )
        except asyncio.CancelledError:
            logger.info("Bot shutdown requested.")
        except Exception as e:
            logger.critical("Fatal error in bot: %s", e, exc_info=True)
            self._alerting.error_alert("TradingBot", str(e))
            raise
        finally:
            self._running = False
            self._alerting.bot_stopped_alert("Process exited")

    async def _analysis_loop(self) -> None:
        """Periodically analyze all configured symbols."""
        while self._running:
            start = time.monotonic()
            logger.info("═══ Analysis cycle start ═══════════════════════════════")

            for symbol in Config.SYMBOLS:
                try:
                    await self._analyze_symbol(symbol)
                except Exception as e:
                    logger.error("Error analyzing %s: %s", symbol, e, exc_info=True)
                    log_event("ERROR", "analysis_loop", f"{symbol}: {e}")
                    self._alerting.error_alert("analysis_loop", f"{symbol}: {e}")

                # Small pause between symbols to respect rate limits
                await asyncio.sleep(2)

            elapsed = time.monotonic() - start
            wait = max(0, Config.ANALYSIS_INTERVAL - elapsed)
            logger.info("Analysis cycle done in %.1fs. Next in %.0fs.", elapsed, wait)
            await asyncio.sleep(wait)

    async def _analyze_symbol(self, symbol: str) -> None:
        """Run one full analysis cycle for a single symbol."""
        loop = asyncio.get_event_loop()

        # Run blocking I/O in thread pool to keep event loop free
        signal: Optional[Signal] = await loop.run_in_executor(
            None, self._signal_gen.generate, symbol
        )

        if signal is None:
            return

        # Alert on new signal
        self._alerting.signal_alert(signal)

        # Execute trade
        if Config.TRADING_MODE == "paper" and self._paper_trader:
            trade_id = await loop.run_in_executor(
                None, self._paper_trader.open_position, signal
            )
            if trade_id > 0:
                self._alerting.trade_opened_alert(signal, trade_id)

        elif Config.TRADING_MODE == "live":
            try:
                from modules.exchange_executor import ExchangeExecutor
                executor = ExchangeExecutor()
                result = await loop.run_in_executor(
                    None, executor.open_position, signal
                )
                logger.info("Live trade placed: order_id=%s", result.order_id)
                self._alerting.trade_opened_alert(signal, int(result.order_id) if result.order_id.isdigit() else 0)
            except Exception as e:
                logger.error("Live execution failed for %s: %s", symbol, e)
                self._alerting.error_alert("exchange_executor", f"{symbol}: {e}")

    async def _monitor_loop(self) -> None:
        """Check open paper positions for SL/TP hits."""
        if Config.TRADING_MODE != "paper" or not self._paper_trader:
            return

        while self._running:
            await asyncio.sleep(POSITION_CHECK_INTERVAL)
            try:
                current_prices = await asyncio.get_event_loop().run_in_executor(
                    None, self._market.get_prices, Config.SYMBOLS
                )
                closed_trades = await asyncio.get_event_loop().run_in_executor(
                    None, self._paper_trader.check_exits, current_prices
                )
                for trade in closed_trades:
                    self._alerting.trade_closed_alert(trade)
            except Exception as e:
                logger.error("Monitor loop error: %s", e)

    async def _summary_loop(self) -> None:
        """Send periodic portfolio summary."""
        await asyncio.sleep(SUMMARY_INTERVAL)  # wait before first summary
        while self._running:
            try:
                portfolio = self._paper_trader.get_summary() if self._paper_trader else {}
                db_summary = get_paper_portfolio_summary()
                self._alerting.portfolio_summary_alert(db_summary, portfolio)
                logger.info(
                    "Portfolio: balance=%.2f USDT | PnL=%.2f USDT (%.2f%%) | open=%d | win_rate=%.1f%%",
                    portfolio.get("balance", 0),
                    portfolio.get("total_pnl_usdt", 0),
                    portfolio.get("total_pnl_pct", 0),
                    portfolio.get("open_positions", 0),
                    db_summary.get("win_rate", 0),
                )
            except Exception as e:
                logger.error("Summary loop error: %s", e)
            await asyncio.sleep(SUMMARY_INTERVAL)

    def stop(self) -> None:
        self._running = False
