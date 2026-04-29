import logging
from typing import Optional

import requests

from config import Config
from modules.paper_trader import ClosedTrade
from modules.signal_generator import Signal

logger = logging.getLogger(__name__)


def _send_telegram(message: str) -> None:
    if not Config.TELEGRAM_BOT_TOKEN or not Config.TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": Config.TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
        if not resp.ok:
            logger.warning("Telegram send failed: %s", resp.text)
    except Exception as e:
        logger.warning("Telegram error: %s", e)


def _send_discord(message: str) -> None:
    if not Config.DISCORD_WEBHOOK_URL:
        return
    try:
        resp = requests.post(Config.DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10)
        if not resp.ok:
            logger.warning("Discord send failed: %s", resp.text)
    except Exception as e:
        logger.warning("Discord error: %s", e)


def send(message: str) -> None:
    """Send to all configured alert channels."""
    logger.info("[ALERT] %s", message[:200])
    _send_telegram(message)
    _send_discord(message)


class AlertingModule:
    """Formats and dispatches alerts for key bot events."""

    def signal_alert(self, signal: Signal) -> None:
        direction_emoji = "🟢" if signal.decision == "LONG" else "🔴"
        factors = "\n".join(f"  • {f}" for f in signal.key_factors)
        risks = "\n".join(f"  ⚠ {r}" for r in signal.risk_factors)

        message = (
            f"{direction_emoji} <b>NEW SIGNAL: {signal.decision}</b>\n"
            f"<b>Pair:</b> {signal.symbol}\n"
            f"<b>Entry:</b> {signal.entry_price:.4f} USDT\n"
            f"<b>Confidence:</b> {signal.confidence}%\n"
            f"<b>SL:</b> {signal.sl_pct:.1f}%  |  <b>TP:</b> {signal.tp_pct:.1f}%\n\n"
            f"<b>Reasoning:</b>\n{signal.reasoning}\n\n"
            f"<b>Key factors:</b>\n{factors}\n"
        )
        if risks:
            message += f"\n<b>Risks:</b>\n{risks}\n"

        send(message)

    def trade_opened_alert(self, signal: Signal, trade_id: int) -> None:
        direction_emoji = "🟢" if signal.decision == "LONG" else "🔴"
        send(
            f"{direction_emoji} Trade opened [id={trade_id}]\n"
            f"{signal.symbol} {signal.decision} @ {signal.entry_price:.4f}\n"
            f"SL: {signal.sl_pct:.1f}% | TP: {signal.tp_pct:.1f}%"
        )

    def trade_closed_alert(self, trade: ClosedTrade) -> None:
        if trade.status == "CLOSED_TP":
            emoji = "✅"
            label = "TAKE PROFIT HIT"
        else:
            emoji = "❌"
            label = "STOP LOSS HIT"

        pnl_sign = "+" if trade.pnl_usdt >= 0 else ""
        send(
            f"{emoji} {label}\n"
            f"{trade.symbol} {trade.direction}\n"
            f"Entry: {trade.entry_price:.4f} → Exit: {trade.exit_price:.4f}\n"
            f"PnL: {pnl_sign}{trade.pnl_usdt:.2f} USDT ({pnl_sign}{trade.pnl_pct:.2f}%)"
        )

    def portfolio_summary_alert(self, summary: dict, portfolio: dict) -> None:
        pnl_sign = "+" if portfolio["total_pnl_usdt"] >= 0 else ""
        send(
            f"📊 <b>Portfolio Summary</b>\n"
            f"Balance: {portfolio['balance']:.2f} USDT\n"
            f"Total PnL: {pnl_sign}{portfolio['total_pnl_usdt']:.2f} USDT "
            f"({pnl_sign}{portfolio['total_pnl_pct']:.2f}%)\n"
            f"Open positions: {portfolio['open_positions']}\n"
            f"Total trades: {summary.get('total_trades', 0)} | "
            f"Win rate: {summary.get('win_rate', 0):.1f}%"
        )

    def error_alert(self, module: str, message: str) -> None:
        send(f"🚨 <b>ERROR [{module}]</b>\n{message}")

    def bot_started_alert(self, config_summary: str) -> None:
        send(f"🤖 <b>Trading Bot Started</b>\n{config_summary}")

    def bot_stopped_alert(self, reason: str) -> None:
        send(f"🛑 <b>Trading Bot Stopped</b>\nReason: {reason}")
