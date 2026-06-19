from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message

from app.config import settings
from app.db import get_target_reaction, is_active_target_chat, write_event
from app.services.membership import is_user_verified
from app.services.reactions import set_verify_reaction

router = Router()


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_group_message(message: Message, bot: Bot) -> None:
    if not message.from_user:
        return

    if message.from_user.is_bot:
        return

    # Не ставим реакции на команды управления ботом.
    if message.text and message.text.startswith("/"):
        return

    if not await is_active_target_chat(message.chat.id):
        return

    verified = await is_user_verified(bot, message.from_user.id)

    if not verified:
        await write_event(
            target_chat_id=message.chat.id,
            message_id=message.message_id,
            user_id=message.from_user.id,
            is_verified=False,
            action="skipped_not_verified",
        )
        return

    reaction = await get_target_reaction(message.chat.id)
    reaction = reaction or settings.default_reaction

    try:
        await set_verify_reaction(
            bot=bot,
            chat_id=message.chat.id,
            message_id=message.message_id,
            reaction=reaction,
        )

        await write_event(
            target_chat_id=message.chat.id,
            message_id=message.message_id,
            user_id=message.from_user.id,
            is_verified=True,
            action="reaction_set",
        )

    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        await write_event(
            target_chat_id=message.chat.id,
            message_id=message.message_id,
            user_id=message.from_user.id,
            is_verified=True,
            action="reaction_failed",
            error=str(exc),
        )
