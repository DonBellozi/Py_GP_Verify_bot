import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)

from app.config import settings
from app.db import (
    get_active_source_chat_ids,
    get_cached_membership,
    set_cached_membership,
    write_event,
)

logger = logging.getLogger(__name__)

VERIFIED_STATUSES = {"creator", "administrator", "member"}

MEMBERSHIP_REQUEST_TIMEOUT_SECONDS = 30
MEMBERSHIP_RETRY_DELAY_SECONDS = 5
MEMBERSHIP_MAX_ATTEMPTS = 2


async def _get_chat_member_with_retry(bot: Bot, source_chat_id: int, user_id: int):
    for attempt in range(1, MEMBERSHIP_MAX_ATTEMPTS + 1):
        try:
            return await bot.get_chat_member(
                chat_id=source_chat_id,
                user_id=user_id,
                request_timeout=MEMBERSHIP_REQUEST_TIMEOUT_SECONDS,
            )

        except TelegramRetryAfter as exc:
            if attempt >= MEMBERSHIP_MAX_ATTEMPTS:
                raise

            delay = max(MEMBERSHIP_RETRY_DELAY_SECONDS, int(exc.retry_after))
            logger.warning(
                "Telegram retry-after while checking membership. "
                "Retry in %s seconds: source_chat_id=%s user_id=%s attempt=%s/%s",
                delay,
                source_chat_id,
                user_id,
                attempt,
                MEMBERSHIP_MAX_ATTEMPTS,
            )
            await asyncio.sleep(delay)

        except TelegramNetworkError as exc:
            if attempt >= MEMBERSHIP_MAX_ATTEMPTS:
                raise

            logger.warning(
                "Telegram network error while checking membership. "
                "Retry in %s seconds: source_chat_id=%s user_id=%s attempt=%s/%s error=%s",
                MEMBERSHIP_RETRY_DELAY_SECONDS,
                source_chat_id,
                user_id,
                attempt,
                MEMBERSHIP_MAX_ATTEMPTS,
                exc,
            )
            await asyncio.sleep(MEMBERSHIP_RETRY_DELAY_SECONDS)

    raise RuntimeError("Unexpected membership retry loop exit")


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
    network_error = False

    for source_chat_id in source_chat_ids:
        try:
            member = await _get_chat_member_with_retry(
                bot=bot,
                source_chat_id=source_chat_id,
                user_id=user_id,
            )

            if member.status in VERIFIED_STATUSES:
                is_verified = True
                break

        except (TelegramNetworkError, TelegramRetryAfter) as exc:
            network_error = True
            logger.warning(
                "Telegram network error while checking membership after retry: "
                "source_chat_id=%s user_id=%s error=%s",
                source_chat_id,
                user_id,
                exc,
            )
            await write_event(
                target_chat_id=source_chat_id,
                message_id=None,
                user_id=user_id,
                is_verified=None,
                action="get_chat_member_network_error_after_retry",
                error=str(exc),
            )
            continue

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

    # Не кешируем отрицательный результат, если был сетевой сбой Telegram.
    # Иначе можно случайно запомнить "не подтвержден" из-за временной проблемы сети.
    if is_verified or not network_error:
        await set_cached_membership(
            user_id=user_id,
            is_verified=is_verified,
            ttl_minutes=settings.cache_ttl_minutes,
        )

    return is_verified
