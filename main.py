import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from modules import state_store
from modules.alerting_module import AlertingModule
from modules.notification_monitor import NotificationMonitor, RawNotification
from modules.session_manager import SessionManager
from modules.trade_parser import TradeParser

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler("logs/involio.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("main")

# ---------------------------------------------------------------------------
# Config from .env
# ---------------------------------------------------------------------------
EMAIL = os.environ["INVOLIO_EMAIL"]
PASSWORD = os.environ["INVOLIO_PASSWORD"]
ALERT_TO = os.environ.get("ALERT_EMAIL_TO", EMAIL)
ALERT_FROM = os.environ.get("ALERT_EMAIL_FROM", EMAIL)
ALERT_PASSWORD = os.environ.get("ALERT_EMAIL_PASSWORD", "")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", 20))
AUTHORIZED_TRADERS = [
    t.strip() for t in os.environ.get("AUTHORIZED_TRADERS", "").split(",") if t.strip()
]

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
state_store.init_db()
alerter = AlertingModule(from_addr=ALERT_FROM, to_addr=ALERT_TO, password=ALERT_PASSWORD)
parser = TradeParser(authorized_traders=AUTHORIZED_TRADERS)
session = SessionManager(email=EMAIL, password=PASSWORD)

PAUSED = False


def handle_notification(notification: RawNotification) -> None:
    global PAUSED
    if PAUSED:
        return

    trade = parser.parse(notification)
    if trade is None:
        return

    if state_store.is_trade_copied(trade.trade_id):
        logger.info("Duplicate trade %s — skipping", trade.trade_id)
        return

    if not trade.is_actionable():
        reason = f"Not actionable: direction={trade.direction}"
        logger.warning("Trade %s not actionable: %s", trade.trade_id, reason)
        alerter.trade_not_copied(trade.trade_id, reason)
        state_store.log_event("trade_not_copied", f"{trade.trade_id} | {reason}")
        return

    logger.info(
        "Trade detected | id=%s trader=%s asset=%s direction=%s",
        trade.trade_id, trade.trader_id, trade.asset, trade.direction,
    )

    # Phase 3 will plug in ExecutionEngine here.
    # For Phase 1, log and persist the detection only.
    state_store.save_copied_trade(
        trade_id=trade.trade_id,
        trader_id=trade.trader_id,
        parsed_fields={
            "asset": trade.asset,
            "direction": trade.direction,
            "entry_price": trade.entry_price,
            "take_profit": trade.take_profit,
            "stop_loss": trade.stop_loss,
            "leverage": trade.leverage,
            "bank_percent": trade.bank_percent,
        },
        action_taken="detected_phase1",
        result="pending_execution",
    )
    logger.info("Trade %s saved to state store (execution not yet wired)", trade.trade_id)


def run() -> None:
    global PAUSED

    max_restarts = 10
    restart_count = 0

    while restart_count < max_restarts:
        try:
            logger.info("Starting session (attempt %d)", restart_count + 1)
            page = session.start()

            monitor = NotificationMonitor(page=page, poll_interval=POLL_INTERVAL)
            monitor.on_new_notification(handle_notification)
            monitor.start()

        except RuntimeError as exc:
            if "Login failed" in str(exc):
                logger.critical("Login failed — pausing system")
                alerter.login_failed(str(exc))
                PAUSED = True
                break
            logger.error("Runtime error: %s", exc)

        except KeyboardInterrupt:
            logger.info("Interrupted by user, shutting down")
            break

        except Exception as exc:
            restart_count += 1
            delay = min(2 ** restart_count, 60)
            logger.error("Unexpected error: %s — restarting in %ds", exc, delay)
            alerter.browser_closed()
            state_store.log_event("crash_restart", str(exc))
            session.close()
            time.sleep(delay)
            continue

        finally:
            session.save_session()
            session.close()

    if restart_count >= max_restarts:
        logger.critical("Max restarts reached — giving up")
        alerter.system_paused("Max restarts reached")


if __name__ == "__main__":
    run()
