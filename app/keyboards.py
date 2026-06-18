from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🏠 ЗГ домов", callback_data="menu:sources"),
                InlineKeyboardButton(text="💬 Целевые чаты", callback_data="menu:targets"),
            ],
            [
                InlineKeyboardButton(text="🧪 Диагностика", callback_data="menu:diag"),
                InlineKeyboardButton(text="🧹 Очистить кеш", callback_data="menu:clear_cache"),
            ],
            [
                InlineKeyboardButton(text="📋 Команды", callback_data="menu:commands"),
            ],
        ]
    )


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="menu:main")]
        ]
    )