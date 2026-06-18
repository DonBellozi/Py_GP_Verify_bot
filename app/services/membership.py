import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from db import (
    get_active_source_chats,
    get_membership_cache,
    set_membership_cache,
)

logger = logging.getLogger(__name__)

GOOD_STATUSES = {"creator", "administrator", "member"}


async def is_member_any_source(bot: Bot, user_id: int, use_cache: bool = True) -> bool:
    if use_cache:
        cached = await get_membership_cache(user_id)
        if cached is not None:
            return cached

    sources = await get_active_source_chats()

    if not sources:
        await set_membership_cache(user_id, False)
        return False

    found = False

    for source in sources:
        chat_id = source["chat_id"]

        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            status = str(member.status)

            if status in GOOD_STATUSES:
                found = True
                break

        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            logger.warning("Cannot check user %s in source chat %s: %s", user_id, chat_id, exc)
            continue
        except Exception as exc:
            logger.exception("Unexpected error while checking user %s in source chat %s: %s", user_id, chat_id, exc)
            continue

    await set_membership_cache(user_id, found)
    return found