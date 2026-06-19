import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

from app.config import settings
from app.db import init_db
from app.handlers import admin, messages


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

    session = AiohttpSession(timeout=60)
    bot = Bot(token=settings.bot_token, session=session)

    dp = Dispatcher()

    dp.include_router(admin.router)
    dp.include_router(messages.router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
        polling_timeout=60,
    )


if __name__ == "__main__":
    asyncio.run(main())
