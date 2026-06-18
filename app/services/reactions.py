import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import ReactionTypeEmoji

logger = logging.getLogger(__name__)


async def set_check_reaction(bot: Bot, chat_id: int, message_id: int, emoji: str) -> bool:
    try:
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
            is_big=False,
        )
        return True

    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        logger.warning("Cannot set reaction in chat %s message %s: %s", chat_id, message_id, exc)
        return False

    except Exception as exc:
        logger.exception("Unexpected reaction error in chat %s message %s: %s", chat_id, message_id, exc)
        return False