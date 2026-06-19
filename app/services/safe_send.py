import logging

from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter
from aiogram.types import Message

logger = logging.getLogger(__name__)


async def safe_answer(message: Message, text: str, **kwargs) -> None:
    """
    Safely send a reply to a Telegram message.

    Telegram API/network timeouts should not crash the update handler
    and should not produce a huge traceback for normal temporary network issues.
    """
    try:
        await message.answer(text, **kwargs)
    except TelegramRetryAfter as exc:
        logger.warning("Telegram flood limit. Retry after %s seconds", exc.retry_after)
    except TelegramNetworkError as exc:
        logger.warning("Telegram network error while sending answer: %s", exc)
