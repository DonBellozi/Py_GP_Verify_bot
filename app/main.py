import asyncio
import logging
import socket

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError

from app.config import settings
from app.db import init_db
from app.handlers import admin, messages


logger = logging.getLogger(__name__)


async def wait_for_ipv6_dns(host: str = "api.telegram.org", port: int = 443) -> None:
    loop = asyncio.get_running_loop()

    while True:
        try:
            await loop.run_in_executor(
                None,
                lambda: socket.getaddrinfo(
                    host,
                    port,
                    socket.AF_INET6,
                    socket.SOCK_STREAM,
                ),
            )
            logger.info("IPv6 DNS resolved for %s", host)
            return

        except socket.gaierror as exc:
            logger.warning(
                "IPv6 DNS is not ready for %s: %s. Retry in 10 seconds.",
                host,
                exc,
            )
            await asyncio.sleep(10)


async def delete_webhook_with_retry(bot: Bot) -> None:
    while True:
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("Webhook deleted successfully")
            return

        except TelegramNetworkError as exc:
            logger.warning(
                "Telegram API is not available yet: %s. Retry in 15 seconds.",
                exc,
            )
            await asyncio.sleep(15)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is empty. Check .env file.")

    if settings.owner_id == 0:
        raise RuntimeError("OWNER_ID is empty or invalid. Check .env file.")

    await init_db()

    session = AiohttpSession(timeout=90)
    bot = Bot(token=settings.bot_token, session=session)

    dp = Dispatcher()
    dp.include_router(admin.router)
    dp.include_router(messages.router)

    try:
        await wait_for_ipv6_dns()
        await delete_webhook_with_retry(bot)

        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            polling_timeout=60,
        )

    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())