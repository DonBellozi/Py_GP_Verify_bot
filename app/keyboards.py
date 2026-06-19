from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_SOURCES = "🏠 ЗГ домов"
BTN_TARGETS = "💬 Целевые чаты"
BTN_DIAG = "🧪 Диагностика"
BTN_CLEAR_CACHE = "🧹 Очистить кеш"
BTN_COMMANDS = "📋 Команды"
BTN_MODE = "🔐 Режим доступа"
BTN_SETTINGS = "⚙️ Настройки"


def admin_menu_keyboard(*, is_owner: bool) -> ReplyKeyboardMarkup:
    buttons = [
        [
            KeyboardButton(text=BTN_SOURCES),
            KeyboardButton(text=BTN_TARGETS),
        ],
        [
            KeyboardButton(text=BTN_DIAG),
            KeyboardButton(text=BTN_COMMANDS),
        ],
    ]

    if is_owner:
        buttons.insert(
            1,
            [
                KeyboardButton(text=BTN_MODE),
                KeyboardButton(text=BTN_SETTINGS),
            ],
        )

        buttons.insert(
            2,
            [
                KeyboardButton(text=BTN_CLEAR_CACHE),
            ],
        )

    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )