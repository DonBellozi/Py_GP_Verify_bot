import logging

from aiogram import Bot, Router
from aiogram.types import Message

from db import get_target_chat, log_event
from services.membership import is_member_any_source
from services.reactions import set_check_reaction

router = Router()
logger = logging.getLogger(__name__)


@router.message()
async def handle_target_chat_message(message: Message, bot: Bot) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        return

    if message.text and message.text.startswith("/"):
        return

    if not message.from_user:
        return

    if message.from_user.is_bot:
        return

    target = await get_target_chat(message.chat.id)

    if not target or target["enabled"] != 1:
        return

    user_id = message.from_user.id

    found = await is_member_any_source(bot, user_id)

    if not found:
        await log_event(
            result="not_found",
            target_chat_id=message.chat.id,
            message_id=message.message_id,
            user_id=user_id,
            details="User not found in active source chats",
        )
        return

    ok = await set_check_reaction(
        bot=bot,
        chat_id=message.chat.id,
        message_id=message.message_id,
        emoji=target["reaction"],
    )

    await log_event(
        result="reaction_set" if ok else "reaction_failed",
        target_chat_id=message.chat.id,
        message_id=message.message_id,
        user_id=user_id,
        details=f"reaction={target['reaction']}",
    )