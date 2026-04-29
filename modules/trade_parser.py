import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from modules.notification_monitor import RawNotification

logger = logging.getLogger(__name__)


@dataclass
class ParsedTrade:
    trade_id: str
    trader_id: str
    asset: str | None = None
    direction: str | None = None        # "long" | "short"
    entry_price: float | None = None
    take_profit: float | None = None
    stop_loss: float | None = None
    leverage: float | None = None
    bank_percent: float | None = None
    raw_text: str = ""
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def is_actionable(self) -> bool:
        """Minimum viable trade: we know who opened it and in which direction."""
        return bool(self.trader_id and self.direction)


class TradeParser:
    def __init__(self, authorized_traders: list[str]):
        # Normalized lowercase for comparison
        self._authorized = {t.strip().lower() for t in authorized_traders if t.strip()}

    def parse(self, notification: RawNotification) -> ParsedTrade | None:
        text = notification.raw_text
        trader_id = self._extract_trader(text)

        if not trader_id:
            logger.debug("Could not identify trader in notification, skipping")
            return None

        if self._authorized and trader_id.lower() not in self._authorized:
            logger.info("Unauthorized trader '%s', skipping", trader_id)
            return None

        trade = ParsedTrade(
            trade_id=_generate_trade_id(trader_id, text),
            trader_id=trader_id,
            raw_text=text,
        )

        trade.direction = _extract_direction(text)
        trade.asset = _extract_asset(text)
        trade.entry_price = _extract_price(text, pattern=r"(?:entry|price)[:\s]+([0-9]+(?:[.,][0-9]+)?)")
        trade.take_profit = _extract_price(text, pattern=r"(?:tp|take\s*profit)[:\s]+([0-9]+(?:[.,][0-9]+)?)")
        trade.stop_loss = _extract_price(text, pattern=r"(?:sl|stop\s*loss)[:\s]+([0-9]+(?:[.,][0-9]+)?)")
        trade.leverage = _extract_number(text, pattern=r"([0-9]+(?:\.[0-9]+)?)\s*[xX]")
        trade.bank_percent = _extract_number(text, pattern=r"([0-9]+(?:\.[0-9]+)?)\s*%")

        logger.info(
            "Parsed trade %s | trader=%s asset=%s direction=%s",
            trade.trade_id, trade.trader_id, trade.asset, trade.direction,
        )
        return trade

    def _extract_trader(self, text: str) -> str | None:
        # TODO: update this pattern once the actual Involio notification format is known
        # Common patterns: "@username opened a position" or "TraderName: BUY BTC"
        match = re.search(r"@([\w\d_]+)", text)
        if match:
            return match.group(1)
        # Fallback: first capitalised word before "opened|bought|sold|long|short"
        match = re.search(r"([A-Z][\w\d]+)\s+(?:opened|bought|sold|went\s+long|went\s+short)", text)
        if match:
            return match.group(1)
        return None


# ---------------------------------------------------------------------------
# Helpers — all pure functions, easy to unit-test
# ---------------------------------------------------------------------------

def _extract_direction(text: str) -> str | None:
    t = text.lower()
    if re.search(r"\blong\b|\bbuy\b|\bbought\b", t):
        return "long"
    if re.search(r"\bshort\b|\bsell\b|\bsold\b", t):
        return "short"
    return None


def _extract_asset(text: str) -> str | None:
    # Matches common crypto pairs: BTC, ETH/USDT, BTC-PERP, etc.
    match = re.search(r"\b([A-Z]{2,6}(?:[/-][A-Z]{2,6})?(?:-PERP)?)\b", text)
    return match.group(1) if match else None


def _extract_price(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return _to_float(match.group(1))
    return None


def _extract_number(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return _to_float(match.group(1))
    return None


def _to_float(value: str) -> float | None:
    try:
        return float(value.replace(",", "."))
    except (ValueError, AttributeError):
        return None


def _generate_trade_id(trader_id: str, raw_text: str) -> str:
    # Round timestamp to the minute to survive slight re-reads of the same notification
    minute_bucket = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")
    raw = f"{trader_id.lower()}|{raw_text[:200]}|{minute_bucket}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]
