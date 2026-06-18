import asyncio
import logging
import os
import socket
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import BotCommand

from config import config, validate_config
from db import init_db
from handlers import admin, messages


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(config.LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def make_session() -> AiohttpSession:
    timeout = int(os.getenv("TELEGRAM_REQUEST_TIMEOUT", "180"))
    force_ipv6 = os.getenv("FORCE_IPV6", "0").strip() == "1"

    session = AiohttpSession(timeout=timeout)

    if force_ipv6:
        # aiogram использует aiohttp. Принудительно задаем IPv6 для TCPConnector.
        session._connector_init["family"] = socket.AF_INET6
        logging.info("Telegram session: FORCE_IPV6 enabled")

    logging.info("Telegram request timeout: %s seconds", timeout)
    return session


async def set_commands(bot: Bot) -> None:
    commands = [
        BotCommand(command="start", description="Запуск бота"),
        BotCommand(command="menu", description="Меню управления"),
        BotCommand(command="id", description="Показать user_id и chat_id"),
        BotCommand(command="test_me", description="Проверить себя"),
        BotCommand(command="register_source", description="Добавить ЗГ дома"),
        BotCommand(command="register_target", description="Добавить целевой чат"),
        BotCommand(command="list_sources", description="Список ЗГ домов"),
        BotCommand(command="list_targets", description="Список целевых чатов"),
        BotCommand(command="diag", description="Диагностика"),
    ]

    await bot.set_my_commands(commands, request_timeout=180)


async def main() -> None:
    validate_config()
    setup_logging()

    logging.info("Starting GP Verify bot")

    await init_db()

    session = make_session()
    bot = Bot(token=config.BOT_TOKEN, session=session)

    dp = Dispatcher()
    dp.include_router(admin.router)
    dp.include_router(messages.router)

    try:
        await set_commands(bot)
        logging.info("Bot commands updated")
    except Exception as exc:
        logging.warning("Cannot update bot commands, continue without command menu: %s", exc)

    try:
        me = await bot.get_me(request_timeout=180)
        logging.info("Bot started as @%s, id=%s", me.username, me.id)

        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            polling_timeout=60,
        )
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())