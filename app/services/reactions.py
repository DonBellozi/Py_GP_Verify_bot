import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError
from aiogram.types import ReactionTypeEmoji

logger = logging.getLogger(__name__)


async def set_verify_reaction(
    *,
    bot: Bot,
    chat_id: int,
    message_id: int,
    reaction: str,
) -> None:
    try:
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=reaction)],
            is_big=False,
            request_timeout=30,
        )

    except TelegramNetworkError as exc:
        logger.warning(
            "Telegram network error while setting reaction: chat_id=%s message_id=%s error=%s",
            chat_id,
            message_id,
            exc,
        )

    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        logger.warning(
            "Telegram refused reaction: chat_id=%s message_id=%s error=%s",
            chat_id,
            message_id,
            exc,
        )
