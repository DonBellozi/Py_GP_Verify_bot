from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config import config
from db import (
    add_admin,
    clear_cache,
    is_admin,
    list_source_chats,
    list_target_chats,
    log_audit,
    remove_admin,
    set_source_enabled,
    set_target_enabled,
    upsert_source_chat,
    upsert_target_chat,
)
from keyboards import admin_menu_keyboard, back_keyboard
from services.membership import is_member_any_source

router = Router()


def display_name(message: Message) -> str:
    user = message.from_user
    if not user:
        return "unknown"

    if user.username:
        return f"@{user.username}"

    return " ".join(x for x in [user.first_name, user.last_name] if x) or str(user.id)


async def require_admin_message(message: Message) -> bool:
    if not message.from_user:
        return False

    ok = await is_admin(message.from_user.id)

    if not ok:
        if message.chat.type == "private":
            await message.answer(
                "Доступ запрещен.\n\n"
                f"Ваш Telegram user_id: `{message.from_user.id}`",
            )
        return False

    return True


async def require_admin_callback(callback: CallbackQuery) -> bool:
    if not callback.from_user:
        return False

    ok = await is_admin(callback.from_user.id)

    if not ok:
        await callback.answer("Доступ запрещен", show_alert=True)
        return False

    return True


def parse_arg_text(message: Message) -> str:
    text = message.text or ""
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else 0

    if await is_admin(user_id):
        await message.answer(
            "GP Verify запущен.\n\n"
            "Вы администратор бота.\n"
            "Откройте меню управления:",
            reply_markup=admin_menu_keyboard(),
        )
    else:
        await message.answer(
            "GP Verify работает.\n\n"
            "Управление ботом доступно только владельцу и назначенным администраторам.\n\n"
            f"Ваш Telegram user_id: `{user_id}`",
        )


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else 0

    await message.answer(
        "Идентификаторы:\n\n"
        f"Ваш user_id: `{user_id}`\n"
        f"chat_id этого чата: `{message.chat.id}`\n"
        f"тип чата: `{message.chat.type}`",
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    if not await require_admin_message(message):
        return

    if message.chat.type != "private":
        await message.answer("Меню управления открывается в личном чате с ботом.")
        return

    await message.answer("Меню управления GP Verify:", reply_markup=admin_menu_keyboard())


@router.message(Command("register_source"))
async def cmd_register_source(message: Message, bot: Bot) -> None:
    if not await require_admin_message(message):
        return

    if message.chat.type not in {"group", "supergroup"}:
        await message.answer("Эту команду нужно выполнить внутри закрытой группы дома.")
        return

    title = parse_arg_text(message) or message.chat.title or str(message.chat.id)

    me = await bot.get_me()
    bot_member = await bot.get_chat_member(chat_id=message.chat.id, user_id=me.id)

    if str(bot_member.status) not in {"administrator", "creator"}:
        await message.answer("Бот должен быть администратором в этой ЗГ, иначе проверка участников может работать нестабильно.")
        return

    await upsert_source_chat(message.chat.id, title)
    await log_audit(message.from_user.id, display_name(message), "register_source", f"{title} / {message.chat.id}")

    await message.answer(
        "ЗГ дома добавлена как источник проверки.\n\n"
        f"Название: {title}\n"
        f"chat_id: `{message.chat.id}`",
    )


@router.message(Command("register_target"))
async def cmd_register_target(message: Message, bot: Bot) -> None:
    if not await require_admin_message(message):
        return

    if message.chat.type not in {"group", "supergroup"}:
        await message.answer("Эту команду нужно выполнить внутри чата, где бот должен ставить галочку.")
        return

    title = parse_arg_text(message) or message.chat.title or str(message.chat.id)

    me = await bot.get_me()
    bot_member = await bot.get_chat_member(chat_id=message.chat.id, user_id=me.id)

    if str(bot_member.status) not in {"administrator", "creator"}:
        await message.answer("Бот должен быть администратором в этом чате, чтобы стабильно видеть сообщения и ставить реакции.")
        return

    await upsert_target_chat(message.chat.id, title, config.DEFAULT_REACTION)
    await log_audit(message.from_user.id, display_name(message), "register_target", f"{title} / {message.chat.id}")

    await message.answer(
        "Целевой чат добавлен.\n\n"
        f"Название: {title}\n"
        f"chat_id: `{message.chat.id}`\n"
        f"Реакция: {config.DEFAULT_REACTION}",
    )


@router.message(Command("list_sources"))
async def cmd_list_sources(message: Message) -> None:
    if not await require_admin_message(message):
        return

    rows = await list_source_chats()

    if not rows:
        await message.answer("ЗГ домов пока не добавлены.")
        return

    lines = ["ЗГ домов:"]
    for row in rows:
        mark = "✅" if row["enabled"] else "⛔"
        lines.append(f'{mark} #{row["id"]} {row["title"]} `{row["chat_id"]}`')

    await message.answer("\n".join(lines))


@router.message(Command("list_targets"))
async def cmd_list_targets(message: Message) -> None:
    if not await require_admin_message(message):
        return

    rows = await list_target_chats()

    if not rows:
        await message.answer("Целевые чаты пока не добавлены.")
        return

    lines = ["Целевые чаты:"]
    for row in rows:
        mark = "✅" if row["enabled"] else "⛔"
        lines.append(f'{mark} #{row["id"]} {row["title"]} `{row["chat_id"]}` reaction={row["reaction"]}')

    await message.answer("\n".join(lines))


@router.message(Command("enable_source"))
async def cmd_enable_source(message: Message) -> None:
    if not await require_admin_message(message):
        return

    arg = parse_arg_text(message)

    if not arg.isdigit():
        await message.answer("Формат: /enable_source ID")
        return

    ok = await set_source_enabled(int(arg), True)
    await message.answer("ЗГ включена." if ok else "ЗГ с таким ID не найдена.")


@router.message(Command("disable_source"))
async def cmd_disable_source(message: Message) -> None:
    if not await require_admin_message(message):
        return

    arg = parse_arg_text(message)

    if not arg.isdigit():
        await message.answer("Формат: /disable_source ID")
        return

    ok = await set_source_enabled(int(arg), False)
    await message.answer("ЗГ отключена." if ok else "ЗГ с таким ID не найдена.")


@router.message(Command("enable_target"))
async def cmd_enable_target(message: Message) -> None:
    if not await require_admin_message(message):
        return

    arg = parse_arg_text(message)

    if not arg.isdigit():
        await message.answer("Формат: /enable_target ID")
        return

    ok = await set_target_enabled(int(arg), True)
    await message.answer("Целевой чат включен." if ok else "Целевой чат с таким ID не найден.")


@router.message(Command("disable_target"))
async def cmd_disable_target(message: Message) -> None:
    if not await require_admin_message(message):
        return

    arg = parse_arg_text(message)

    if not arg.isdigit():
        await message.answer("Формат: /disable_target ID")
        return

    ok = await set_target_enabled(int(arg), False)
    await message.answer("Целевой чат отключен." if ok else "Целевой чат с таким ID не найден.")


@router.message(Command("add_admin"))
async def cmd_add_admin(message: Message) -> None:
    if not message.from_user or message.from_user.id != config.OWNER_ID:
        await message.answer("Добавлять администраторов может только владелец бота.")
        return

    arg = parse_arg_text(message)

    if not arg.isdigit():
        await message.answer("Формат: /add_admin USER_ID")
        return

    await add_admin(int(arg))
    await log_audit(message.from_user.id, display_name(message), "add_admin", arg)
    await message.answer(f"Администратор добавлен: `{arg}`")


@router.message(Command("remove_admin"))
async def cmd_remove_admin(message: Message) -> None:
    if not message.from_user or message.from_user.id != config.OWNER_ID:
        await message.answer("Удалять администраторов может только владелец бота.")
        return

    arg = parse_arg_text(message)

    if not arg.isdigit():
        await message.answer("Формат: /remove_admin USER_ID")
        return

    if int(arg) == config.OWNER_ID:
        await message.answer("Владельца нельзя удалить из администраторов.")
        return

    await remove_admin(int(arg))
    await log_audit(message.from_user.id, display_name(message), "remove_admin", arg)
    await message.answer(f"Администратор отключен: `{arg}`")


@router.message(Command("test_me"))
async def cmd_test_me(message: Message, bot: Bot) -> None:
    if not message.from_user:
        return

    found = await is_member_any_source(bot, message.from_user.id, use_cache=False)

    if found:
        await message.answer("Вы найдены в одной из подключенных ЗГ домов. Ваши сообщения будут отмечаться ✅.")
    else:
        await message.answer("Вы не найдены в подключенных ЗГ домов.")


@router.message(Command("clear_cache"))
async def cmd_clear_cache(message: Message) -> None:
    if not await require_admin_message(message):
        return

    await clear_cache()
    await log_audit(message.from_user.id, display_name(message), "clear_cache", "")
    await message.answer("Кеш проверок очищен.")


@router.message(Command("diag"))
async def cmd_diag(message: Message, bot: Bot) -> None:
    if not await require_admin_message(message):
        return

    me = await bot.get_me()
    sources = await list_source_chats()
    targets = await list_target_chats()

    await message.answer(
        "Диагностика GP Verify:\n\n"
        f"Бот: @{me.username}\n"
        f"bot_id: `{me.id}`\n"
        f"Текущий chat_id: `{message.chat.id}`\n"
        f"Тип чата: `{message.chat.type}`\n"
        f"ЗГ домов: {len(sources)}\n"
        f"Целевые чаты: {len(targets)}\n"
        f"Реакция по умолчанию: {config.DEFAULT_REACTION}\n"
        f"Кеш, секунд: {config.CACHE_TTL_SECONDS}",
    )


@router.callback_query(F.data == "menu:main")
async def cb_menu_main(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return

    await callback.message.edit_text("Меню управления GP Verify:", reply_markup=admin_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == "menu:sources")
async def cb_menu_sources(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return

    rows = await list_source_chats()

    if not rows:
        text = "ЗГ домов пока не добавлены.\n\nДобавление выполняется командой в нужной закрытой группе:\n/register_source Дом 1"
    else:
        lines = ["ЗГ домов:"]
        for row in rows:
            mark = "✅" if row["enabled"] else "⛔"
            lines.append(f'{mark} #{row["id"]} {row["title"]}')
        text = "\n".join(lines)

    await callback.message.edit_text(text, reply_markup=back_keyboard())
    await callback.answer()


@router.callback_query(F.data == "menu:targets")
async def cb_menu_targets(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return

    rows = await list_target_chats()

    if not rows:
        text = "Целевые чаты пока не добавлены.\n\nДобавление выполняется командой в нужном чате:\n/register_target Общий чат"
    else:
        lines = ["Целевые чаты:"]
        for row in rows:
            mark = "✅" if row["enabled"] else "⛔"
            lines.append(f'{mark} #{row["id"]} {row["title"]} {row["reaction"]}')
        text = "\n".join(lines)

    await callback.message.edit_text(text, reply_markup=back_keyboard())
    await callback.answer()


@router.callback_query(F.data == "menu:commands")
async def cb_menu_commands(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return

    text = (
        "Основные команды:\n\n"
        "/menu – меню управления\n"
        "/id – показать user_id и chat_id\n"
        "/register_source Дом 1 – добавить текущую ЗГ дома\n"
        "/register_target Общий чат – добавить целевой чат\n"
        "/list_sources – список ЗГ\n"
        "/list_targets – список целевых чатов\n"
        "/enable_source ID – включить ЗГ\n"
        "/disable_source ID – отключить ЗГ\n"
        "/enable_target ID – включить целевой чат\n"
        "/disable_target ID – отключить целевой чат\n"
        "/test_me – проверить себя\n"
        "/diag – диагностика\n"
        "/clear_cache – очистить кеш\n\n"
        "Только владелец:\n"
        "/add_admin USER_ID\n"
        "/remove_admin USER_ID"
    )

    await callback.message.edit_text(text, reply_markup=back_keyboard())
    await callback.answer()


@router.callback_query(F.data == "menu:diag")
async def cb_menu_diag(callback: CallbackQuery, bot: Bot) -> None:
    if not await require_admin_callback(callback):
        return

    me = await bot.get_me()
    sources = await list_source_chats()
    targets = await list_target_chats()

    text = (
        "Диагностика GP Verify:\n\n"
        f"Бот: @{me.username}\n"
        f"bot_id: {me.id}\n"
        f"ЗГ домов: {len(sources)}\n"
        f"Целевые чаты: {len(targets)}\n"
        f"Реакция: {config.DEFAULT_REACTION}\n"
        f"Кеш: {config.CACHE_TTL_SECONDS} сек."
    )

    await callback.message.edit_text(text, reply_markup=back_keyboard())
    await callback.answer()


@router.callback_query(F.data == "menu:clear_cache")
async def cb_menu_clear_cache(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return

    await clear_cache()
    await log_audit(callback.from_user.id, callback.from_user.full_name, "clear_cache", "from menu")

    await callback.message.edit_text("Кеш проверок очищен.", reply_markup=back_keyboard())
    await callback.answer("Готово")