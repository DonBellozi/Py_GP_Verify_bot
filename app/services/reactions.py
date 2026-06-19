from aiogram import Bot
from aiogram.types import ReactionTypeEmoji


async def set_verify_reaction(
    *,
    bot: Bot,
    chat_id: int,
    message_id: int,
    reaction: str,
) -> None:
    await bot.set_message_reaction(
        chat_id=chat_id,
        message_id=message_id,
        reaction=[ReactionTypeEmoji(emoji=reaction)],
        is_big=False,
    )
