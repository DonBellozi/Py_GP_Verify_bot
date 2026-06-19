import json

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.config import settings
from app.db import (
    clear_membership_cache,
    create_pending_request,
    get_pending_request,
    get_setting,
    list_source_chats,
    list_target_chats,
    remove_chat_from_processing,
    set_setting,
    update_pending_request_status,
    upsert_source_chat,
    upsert_target_chat,
    write_audit,
)
from app.keyboards import (
    BTN_CLEAR_CACHE,
    BTN_COMMANDS,
    BTN_DIAG,
    BTN_MODE,
    BTN_SETTINGS,
    BTN_SOURCES,
    BTN_TARGETS,
    admin_menu_keyboard,
)
from app.services.owner_notify import (
    notify_owner_chat_added,
    notify_owner_pending_chat_request,
)
from app.services.permissions import require_admin
from app.services.safe_send import safe_answer

router = Router()


def _chat_title(message: Message) -> str:
    return message.chat.title or getattr(message.chat, "full_name", None) or str(message.chat.id)


def _command_arg(message: Message, command: str) -> str:
    text = message.text or ""
    return text.replace(command, "", 1).strip()


def _mode_title(mode: str | None) -> str:
    return mode or "soft"


async def _register_source_now(message: Message, bot: Bot, title: str, mode: str) -> None:
    assert message.from_user is not None

    await upsert_source_chat(
        chat_id=message.chat.id,
        title=title,
        actor_user_id=message.from_user.id,
        actor_username=message.from_user.username,
        actor_full_name=message.from_user.full_name,
    )

    await clear_membership_cache()

    await write_audit(
        actor_user_id=message.from_user.id,
        actor_username=message.from_user.username,
        actor_full_name=message.from_user.full_name,
        action="source_chat_registered",
        entity_type="source_chat",
        entity_id=str(message.chat.id),
        details={"title": title, "cache_cleared": True, "mode": mode},
    )

    if message.from_user.id != settings.owner_id:
        await notify_owner_chat_added(
            bot=bot,
            actor=message.from_user,
            chat=message.chat,
            role="source",
            mode=mode,
        )

    await safe_answer(message, 
        "✅ Закрытая группа добавлена в обработку.\n\n"
        f"Название: {title}\n"
        f"Chat ID: {message.chat.id}\n\n"
        "Кеш проверки пользователей очищен."
    )


async def _register_target_now(message: Message, bot: Bot, title: str, reaction: str, mode: str) -> None:
    assert message.from_user is not None

    await upsert_target_chat(
        chat_id=message.chat.id,
        title=title,
        reaction=reaction,
        actor_user_id=message.from_user.id,
        actor_username=message.from_user.username,
        actor_full_name=message.from_user.full_name,
    )

    await clear_membership_cache()

    await write_audit(
        actor_user_id=message.from_user.id,
        actor_username=message.from_user.username,
        actor_full_name=message.from_user.full_name,
        action="target_chat_registered",
        entity_type="target_chat",
        entity_id=str(message.chat.id),
        details={"title": title, "reaction": reaction, "cache_cleared": True, "mode": mode},
    )

    if message.from_user.id != settings.owner_id:
        await notify_owner_chat_added(
            bot=bot,
            actor=message.from_user,
            chat=message.chat,
            role="target",
            reaction=reaction,
            mode=mode,
        )

    await safe_answer(message, 
        "✅ Целевой чат добавлен в обработку.\n\n"
        f"Название: {title}\n"
        f"Chat ID: {message.chat.id}\n"
        f"Реакция: {reaction}\n\n"
        "Кеш проверки пользователей очищен."
    )


@router.message(Command("start"))
async def start(message: Message) -> None:
    if not message.from_user:
        return

    if not await require_admin(message.from_user):
        await safe_answer(message, 
            "Доступ к управлению ботом запрещен.\n\n"
            f"Ваш Telegram user_id: {message.from_user.id}"
        )
        return

    is_owner = message.from_user.id == settings.owner_id

    await safe_answer(message, 
        "Меню управления GP Verify:",
        reply_markup=admin_menu_keyboard(is_owner=is_owner),
    )


@router.message(Command("menu"))
async def menu(message: Message) -> None:
    if not message.from_user:
        return

    if not await require_admin(message.from_user):
        await safe_answer(message, 
            "Доступ к управлению ботом запрещен.\n\n"
            f"Ваш Telegram user_id: {message.from_user.id}"
        )
        return

    is_owner = message.from_user.id == settings.owner_id

    await safe_answer(message, 
        "Меню управления GP Verify:",
        reply_markup=admin_menu_keyboard(is_owner=is_owner),
    )


@router.message(Command("mode"))
async def show_mode(message: Message) -> None:
    if not message.from_user or message.from_user.id != settings.owner_id:
        return

    mode = await get_setting("admin_approval_mode", "soft")

    await safe_answer(message, 
        f"⚙️ Текущий режим управления: {mode}\n\n"
        "Доступные режимы:\n\n"
        "soft – мягкий режим.\n"
        "Администратор может сразу добавить чат в обработку, "
        "а владелец получает уведомление о действии.\n\n"
        "strict – строгий режим.\n"
        "Действия администратора требуют подтверждения владельца. "
        "Администратор создает заявку, владелец подтверждает или отклоняет ее.\n\n"
        "Команды переключения:\n"
        "/mode_soft – включить мягкий режим\n"
        "/mode_strict – включить строгий режим"
    )


@router.message(Command("mode_soft"))
async def set_mode_soft(message: Message) -> None:
    if not message.from_user or message.from_user.id != settings.owner_id:
        return

    await set_setting("admin_approval_mode", "soft")

    await write_audit(
        actor_user_id=message.from_user.id,
        actor_username=message.from_user.username,
        actor_full_name=message.from_user.full_name,
        action="admin_approval_mode_changed",
        entity_type="settings",
        entity_id="admin_approval_mode",
        details={"mode": "soft"},
    )

    await safe_answer(message, "✅ Включен мягкий режим управления.")


@router.message(Command("mode_strict"))
async def set_mode_strict(message: Message) -> None:
    if not message.from_user or message.from_user.id != settings.owner_id:
        return

    await set_setting("admin_approval_mode", "strict")

    await write_audit(
        actor_user_id=message.from_user.id,
        actor_username=message.from_user.username,
        actor_full_name=message.from_user.full_name,
        action="admin_approval_mode_changed",
        entity_type="settings",
        entity_id="admin_approval_mode",
        details={"mode": "strict"},
    )

    await safe_answer(message, 
        "✅ Включен строгий режим управления.\n\n"
        "Теперь добавление чатов администраторами будет требовать подтверждения владельца."
    )


@router.message(Command("register_source"))
async def register_source(message: Message, bot: Bot) -> None:
    if not message.from_user or not await require_admin(message.from_user):
        return

    if message.chat.type == "private":
        await safe_answer(message, "Эту команду нужно выполнить в закрытой группе дома.")
        return

    title = _command_arg(message, "/register_source") or _chat_title(message)
    mode = _mode_title(await get_setting("admin_approval_mode", "soft"))

    if mode == "strict" and message.from_user.id != settings.owner_id:
        request_id = await create_pending_request(
            request_type="add_source_chat",
            requested_by_user_id=message.from_user.id,
            requested_by_username=message.from_user.username,
            requested_by_full_name=message.from_user.full_name,
            chat_id=message.chat.id,
            chat_title=title,
            chat_role="source",
            payload={"title": title},
        )

        await write_audit(
            actor_user_id=message.from_user.id,
            actor_username=message.from_user.username,
            actor_full_name=message.from_user.full_name,
            action="source_chat_add_requested",
            entity_type="source_chat",
            entity_id=str(message.chat.id),
            details={"request_id": request_id, "title": title},
        )

        await notify_owner_pending_chat_request(
            bot=bot,
            request_id=request_id,
            actor=message.from_user,
            chat=message.chat,
            role="source",
        )

        await safe_answer(message, 
            "🕓 Заявка на добавление закрытой группы отправлена владельцу."
        )
        return

    await _register_source_now(message, bot, title, mode)


@router.message(Command("register_target"))
async def register_target(message: Message, bot: Bot) -> None:
    if not message.from_user or not await require_admin(message.from_user):
        return

    if message.chat.type == "private":
        await safe_answer(message, "Эту команду нужно выполнить в целевом чате.")
        return

    title = _command_arg(message, "/register_target") or _chat_title(message)
    mode = _mode_title(await get_setting("admin_approval_mode", "soft"))
    reaction = await get_setting("default_reaction", settings.default_reaction)
    reaction = reaction or settings.default_reaction

    if mode == "strict" and message.from_user.id != settings.owner_id:
        request_id = await create_pending_request(
            request_type="add_target_chat",
            requested_by_user_id=message.from_user.id,
            requested_by_username=message.from_user.username,
            requested_by_full_name=message.from_user.full_name,
            chat_id=message.chat.id,
            chat_title=title,
            chat_role="target",
            payload={"title": title, "reaction": reaction},
        )

        await write_audit(
            actor_user_id=message.from_user.id,
            actor_username=message.from_user.username,
            actor_full_name=message.from_user.full_name,
            action="target_chat_add_requested",
            entity_type="target_chat",
            entity_id=str(message.chat.id),
            details={"request_id": request_id, "title": title, "reaction": reaction},
        )

        await notify_owner_pending_chat_request(
            bot=bot,
            request_id=request_id,
            actor=message.from_user,
            chat=message.chat,
            role="target",
            reaction=reaction,
        )

        await safe_answer(message, 
            "🕓 Заявка на добавление целевого чата отправлена владельцу."
        )
        return

    await _register_target_now(message, bot, title, reaction, mode)


@router.callback_query(lambda callback: callback.data and callback.data.startswith("approve_req:"))
async def approve_request(callback: CallbackQuery) -> None:
    if not callback.from_user or callback.from_user.id != settings.owner_id:
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    request_id = int(callback.data.split(":", 1)[1])
    request = await get_pending_request(request_id)

    if not request:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return

    if request["status"] != "pending":
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return

    payload = json.loads(request["payload_json"] or "{}")

    if request["request_type"] == "add_source_chat":
        await upsert_source_chat(
            chat_id=int(request["chat_id"]),
            title=payload.get("title") or request["chat_title"],
            actor_user_id=int(request["requested_by_user_id"]),
            actor_username=request["requested_by_username"],
            actor_full_name=request["requested_by_full_name"],
        )

        action = "source_chat_request_approved"
        entity_type = "source_chat"

    elif request["request_type"] == "add_target_chat":
        reaction = payload.get("reaction") or settings.default_reaction

        await upsert_target_chat(
            chat_id=int(request["chat_id"]),
            title=payload.get("title") or request["chat_title"],
            reaction=reaction,
            actor_user_id=int(request["requested_by_user_id"]),
            actor_username=request["requested_by_username"],
            actor_full_name=request["requested_by_full_name"],
        )

        action = "target_chat_request_approved"
        entity_type = "target_chat"

    else:
        await callback.answer("Неизвестный тип заявки.", show_alert=True)
        return

    await clear_membership_cache()

    await update_pending_request_status(
        request_id=request_id,
        status="approved",
        resolved_by_user_id=callback.from_user.id,
    )

    await write_audit(
        actor_user_id=callback.from_user.id,
        actor_username=callback.from_user.username,
        actor_full_name=callback.from_user.full_name,
        action=action,
        entity_type=entity_type,
        entity_id=str(request["chat_id"]),
        details={
            "request_id": request_id,
            "requested_by_user_id": request["requested_by_user_id"],
            "cache_cleared": True,
        },
    )

    if callback.message:
        await callback.message.edit_text(
            "✅ Заявка одобрена.\n\n"
            f"Чат: {request['chat_title']}\n"
            f"Chat ID: {request['chat_id']}\n"
            "Кеш проверки пользователей очищен."
        )

    await callback.answer("Заявка одобрена.")


@router.callback_query(lambda callback: callback.data and callback.data.startswith("reject_req:"))
async def reject_request(callback: CallbackQuery) -> None:
    if not callback.from_user or callback.from_user.id != settings.owner_id:
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    request_id = int(callback.data.split(":", 1)[1])
    request = await get_pending_request(request_id)

    if not request:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return

    if request["status"] != "pending":
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return

    await update_pending_request_status(
        request_id=request_id,
        status="rejected",
        resolved_by_user_id=callback.from_user.id,
    )

    await write_audit(
        actor_user_id=callback.from_user.id,
        actor_username=callback.from_user.username,
        actor_full_name=callback.from_user.full_name,
        action="pending_request_rejected",
        entity_type=request["chat_role"],
        entity_id=str(request["chat_id"]),
        details={
            "request_id": request_id,
            "request_type": request["request_type"],
            "requested_by_user_id": request["requested_by_user_id"],
        },
    )

    if callback.message:
        await callback.message.edit_text(
            "❌ Заявка отклонена.\n\n"
            f"Чат: {request['chat_title']}\n"
            f"Chat ID: {request['chat_id']}"
        )

    await callback.answer("Заявка отклонена.")


@router.message(Command("sources"))
async def show_sources(message: Message) -> None:
    if not message.from_user or message.from_user.id != settings.owner_id:
        return

    chats = await list_source_chats()

    if not chats:
        await safe_answer(message, "Закрытые группы домов не добавлены.")
        return

    lines = ["🏠 Закрытые группы домов:\n"]

    for chat in chats:
        status = "✅" if chat["enabled"] else "⛔"
        lines.append(
            f"{status} ID базы: {chat['id']}\n"
            f"Название: {chat['title']}\n"
            f"Chat ID: {chat['chat_id']}\n"
            f"Исключить: /remove_source_{chat['id']}\n"
        )

    await safe_answer(message, "\n".join(lines))


@router.message(Command("targets"))
async def show_targets(message: Message) -> None:
    if not message.from_user or message.from_user.id != settings.owner_id:
        return

    chats = await list_target_chats()

    if not chats:
        await safe_answer(message, "Целевые чаты не добавлены.")
        return

    lines = ["💬 Целевые чаты:\n"]

    for chat in chats:
        status = "✅" if chat["enabled"] else "⛔"
        lines.append(
            f"{status} ID базы: {chat['id']}\n"
            f"Название: {chat['title']}\n"
            f"Chat ID: {chat['chat_id']}\n"
            f"Реакция: {chat['reaction']}\n"
            f"Исключить: /remove_target_{chat['id']}\n"
        )

    await safe_answer(message, "\n".join(lines))


@router.message(lambda message: message.text and message.text.startswith("/remove_source_"))
async def remove_source(message: Message) -> None:
    if not message.from_user or message.from_user.id != settings.owner_id:
        return

    raw_id = message.text.replace("/remove_source_", "", 1).strip()

    if not raw_id.isdigit():
        await safe_answer(message, "Некорректный ID.")
        return

    chat_db_id = int(raw_id)

    chat = await remove_chat_from_processing(
        table="source_chats",
        chat_db_id=chat_db_id,
        actor_user_id=message.from_user.id,
        reason="removed_by_owner",
    )

    if not chat:
        await safe_answer(message, "Чат не найден.")
        return

    await write_audit(
        actor_user_id=message.from_user.id,
        actor_username=message.from_user.username,
        actor_full_name=message.from_user.full_name,
        action="source_chat_removed_from_processing",
        entity_type="source_chat",
        entity_id=str(chat_db_id),
        details={
            "chat_id": chat["chat_id"],
            "title": chat["title"],
            "cache_cleared": True,
        },
    )

    await safe_answer(message, 
        "⛔ Закрытая группа исключена из обработки.\n\n"
        f"Название: {chat['title']}\n"
        f"Chat ID: {chat['chat_id']}\n"
        "Кеш проверки пользователей очищен."
    )


@router.message(lambda message: message.text and message.text.startswith("/remove_target_"))
async def remove_target(message: Message) -> None:
    if not message.from_user or message.from_user.id != settings.owner_id:
        return

    raw_id = message.text.replace("/remove_target_", "", 1).strip()

    if not raw_id.isdigit():
        await safe_answer(message, "Некорректный ID.")
        return

    chat_db_id = int(raw_id)

    chat = await remove_chat_from_processing(
        table="target_chats",
        chat_db_id=chat_db_id,
        actor_user_id=message.from_user.id,
        reason="removed_by_owner",
    )

    if not chat:
        await safe_answer(message, "Чат не найден.")
        return

    await write_audit(
        actor_user_id=message.from_user.id,
        actor_username=message.from_user.username,
        actor_full_name=message.from_user.full_name,
        action="target_chat_removed_from_processing",
        entity_type="target_chat",
        entity_id=str(chat_db_id),
        details={
            "chat_id": chat["chat_id"],
            "title": chat["title"],
            "cache_cleared": True,
        },
    )

    await safe_answer(message, 
        "⛔ Целевой чат исключен из обработки.\n\n"
        f"Название: {chat['title']}\n"
        f"Chat ID: {chat['chat_id']}\n"
        "Кеш проверки пользователей очищен."
    )

@router.message(F.text == BTN_SOURCES)
async def menu_sources(message: Message) -> None:
    await show_sources(message)


@router.message(F.text == BTN_TARGETS)
async def menu_targets(message: Message) -> None:
    await show_targets(message)


@router.message(F.text == BTN_MODE)
async def menu_mode(message: Message) -> None:
    await show_mode(message)


@router.message(F.text == BTN_CLEAR_CACHE)
async def menu_clear_cache(message: Message) -> None:
    if not message.from_user or message.from_user.id != settings.owner_id:
        await safe_answer(message, "Очистка кеша доступна только владельцу бота.")
        return

    await clear_membership_cache()

    await write_audit(
        actor_user_id=message.from_user.id,
        actor_username=message.from_user.username,
        actor_full_name=message.from_user.full_name,
        action="membership_cache_cleared",
        entity_type="cache",
        entity_id="membership_cache",
        details={"source": "owner_menu"},
    )

    await safe_answer(message, "✅ Кеш проверки пользователей очищен.")


@router.message(F.text == BTN_SETTINGS)
async def menu_settings(message: Message) -> None:
    if not message.from_user or message.from_user.id != settings.owner_id:
        await safe_answer(message, "Настройки доступны только владельцу бота.")
        return

    mode = await get_setting("admin_approval_mode", "soft")
    reaction = await get_setting("default_reaction", settings.default_reaction)

    await safe_answer(message, 
        "⚙️ Текущие настройки GP Verify:\n\n"
        f"Режим управления: {mode}\n"
        f"Реакция: {reaction}\n"
        f"Кеш проверки: {settings.cache_ttl_minutes} минут\n\n"
        "Переключение режима:\n"
        "/mode_soft – мягкий режим\n"
        "/mode_strict – строгий режим\n\n"
        "Списки чатов:\n"
        "/sources – ЗГ домов\n"
        "/targets – целевые чаты"
    )


@router.message(F.text == BTN_DIAG)
async def menu_diag(message: Message) -> None:
    if not message.from_user or not await require_admin(message.from_user):
        return

    mode = await get_setting("admin_approval_mode", "soft")
    reaction = await get_setting("default_reaction", settings.default_reaction)

    await safe_answer(message, 
        "🧪 Базовая диагностика:\n\n"
        f"Бот запущен: да\n"
        f"Ваш user_id: {message.from_user.id}\n"
        f"Роль: {'owner' if message.from_user.id == settings.owner_id else 'admin'}\n"
        f"Режим управления: {mode}\n"
        f"Реакция: {reaction}\n\n"
        "Для проверки подключенных чатов используйте:\n"
        "/sources\n"
        "/targets"
    )


@router.message(F.text == BTN_COMMANDS)
async def menu_commands(message: Message) -> None:
    if not message.from_user or not await require_admin(message.from_user):
        return

    is_owner = message.from_user.id == settings.owner_id

    text = (
        "📋 Команды GP Verify:\n\n"
        "Общие команды:\n"
        "/start – открыть меню\n"
        "/menu – открыть меню\n"
        "/register_source Название – добавить текущий чат как ЗГ дома\n"
        "/register_target Название – добавить текущий чат как целевой\n"
        "/sources – список ЗГ домов\n"
        "/targets – список целевых чатов\n"
    )

    if is_owner:
        text += (
            "\nКоманды владельца:\n"
            "/mode – показать режим управления\n"
            "/mode_soft – включить мягкий режим\n"
            "/mode_strict – включить строгий режим\n"
            "/remove_source_ID – исключить ЗГ из обработки\n"
            "/remove_target_ID – исключить целевой чат из обработки\n"
        )

    await safe_answer(message, text)