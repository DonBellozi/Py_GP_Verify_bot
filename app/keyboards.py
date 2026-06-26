from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_SOURCES = "🏠 ЗГ домов"
BTN_TARGETS = "💬 Целевые чаты"
BTN_ADMINS = "👥 Администраторы"
BTN_DIAG = "🧪 Диагностика"
BTN_CLEAR_CACHE = "🧹 Очистить кеш"
BTN_COMMANDS = "📋 Команды"
BTN_MODE = "🔐 Режим доступа"
BTN_SETTINGS = "⚙️ Настройки"

BTN_ADMIN_ADD = "➕ Добавить администратора"
BTN_ADMIN_REMOVE = "➖ Удалить администратора"
BTN_ADMIN_LIST = "📋 Список администраторов"
BTN_MY_PROFILE = "👤 Мой профиль"
BTN_BACK = "🔙 Назад"


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
                KeyboardButton(text=BTN_ADMINS),
                KeyboardButton(text=BTN_CLEAR_CACHE),
            ],
        )

    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )


def admins_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=BTN_ADMIN_ADD),
                KeyboardButton(text=BTN_ADMIN_REMOVE),
            ],
            [
                KeyboardButton(text=BTN_ADMIN_LIST),
                KeyboardButton(text=BTN_MY_PROFILE),
            ],
            [
                KeyboardButton(text=BTN_BACK),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Управление администраторами",
    )
