from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from app.config import settings
from app.db import (
    get_active_source_chat_ids,
    get_cached_membership,
    set_cached_membership,
    write_event,
)

VERIFIED_STATUSES = {"creator", "administrator", "member"}


async def is_user_verified(bot: Bot, user_id: int) -> bool:
    cached = await get_cached_membership(user_id)

    if cached is not None:
        return cached

    source_chat_ids = await get_active_source_chat_ids()

    if not source_chat_ids:
        await set_cached_membership(
            user_id=user_id,
            is_verified=False,
            ttl_minutes=settings.cache_ttl_minutes,
        )
        return False

    is_verified = False

    for source_chat_id in source_chat_ids:
        try:
            member = await bot.get_chat_member(
                chat_id=source_chat_id,
                user_id=user_id,
            )

            if member.status in VERIFIED_STATUSES:
                is_verified = True
                break

        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            await write_event(
                target_chat_id=source_chat_id,
                message_id=None,
                user_id=user_id,
                is_verified=None,
                action="get_chat_member_failed",
                error=str(exc),
            )
            continue

    await set_cached_membership(
        user_id=user_id,
        is_verified=is_verified,
        ttl_minutes=settings.cache_ttl_minutes,
    )

    return is_verified
