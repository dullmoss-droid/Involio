import asyncio
import logging
import signal
import sys

from config import Config
from modules.trading_bot import TradingBot


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("trading_bot.log"),
        ],
    )
    # Quiet noisy third-party loggers
    logging.getLogger("ccxt").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def main() -> None:
    setup_logging()
    logger = logging.getLogger("main")

    logger.info("═══════════════════════════════════════════════════════════")
    logger.info("  Crypto Trading Bot  |  Powered by Claude AI")
    logger.info("═══════════════════════════════════════════════════════════")

    try:
        Config.validate()
    except ValueError as e:
        logger.critical("Configuration error: %s", e)
        logger.critical("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)

    logger.info("Config: %s", Config.summary())

    bot = TradingBot()

    # Graceful shutdown on SIGINT / SIGTERM
    loop = asyncio.get_running_loop()

    def _shutdown(sig_name: str) -> None:
        logger.info("Received %s — shutting down gracefully...", sig_name)
        bot.stop()
        for task in asyncio.all_tasks(loop):
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: _shutdown(s.name))

    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
