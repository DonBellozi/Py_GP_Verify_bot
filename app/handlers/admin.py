import json
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError
from aiogram.types import CallbackQuery, Message

from app.config import settings
from app.db import (
    clear_membership_cache,
    create_pending_request,
    get_bot_admin,
    get_pending_request,
    get_setting,
    list_bot_admins,
    list_source_chats,
    list_target_chats,
    remove_bot_admin,
    remove_chat_from_processing,
    set_setting,
    update_pending_request_status,
    update_bot_admin_profile,
    upsert_bot_admin,
    upsert_source_chat,
    upsert_target_chat,
    write_audit,
)
from app.keyboards import (
    BTN_ADMIN_ADD,
    BTN_ADMIN_LIST,
    BTN_ADMIN_REMOVE,
    BTN_ADMINS,
    BTN_BACK,
    BTN_CLEAR_CACHE,
    BTN_COMMANDS,
    BTN_DIAG,
    BTN_MODE,
    BTN_MY_PROFILE,
    BTN_SETTINGS,
    BTN_SOURCES,
    BTN_TARGETS,
    admin_menu_keyboard,
    admins_menu_keyboard,
)
from app.services.owner_notify import (
    notify_owner_chat_added,
    notify_owner_pending_chat_request,
)
from app.services.permissions import require_admin
from app.services.safe_send import safe_answer

logger = logging.getLogger(__name__)

router = Router()


class AdminStates(StatesGroup):
    waiting_add_admin_id = State()
    waiting_remove_admin_id = State()


def _chat_title(message: Message) -> str:
    return message.chat.title or getattr(message.chat, "full_name", None) or str(message.chat.id)


def _command_arg(message: Message, command: str) -> str:
    text = message.text or ""
    return text.replace(command, "", 1).strip()


def _mode_title(mode: str | None) -> str:
    return mode or "soft"

def _format_username(username: str | None) -> str:
    return f"@{username}" if username else "username не указан"


def _format_full_name(full_name: str | None) -> str:
    return full_name or "имя не указано"


def _format_admin_line(
    *,
    user_id: int,
    username: str | None,
    full_name: str | None,
) -> str:
    return f"{user_id} ({_format_username(username)}) {_format_full_name(full_name)}"


def _parse_user_id(raw: str | None) -> int | None:
    if not raw:
        return None

    raw = raw.strip()

    if not raw.isdigit():
        return None

    return int(raw)


def _user_identity_text(user: object) -> str:
    username = getattr(user, "username", None)
    full_name = getattr(user, "full_name", None)

    if not full_name:
        first_name = getattr(user, "first_name", None)
        last_name = getattr(user, "last_name", None)
        full_name = " ".join(part for part in [first_name, last_name] if part) or None

    return _format_admin_line(
        user_id=int(getattr(user, "id")),
        username=username,
        full_name=full_name,
    )


async def _resolve_user_identity(bot: Bot, user_id: int) -> tuple[str | None, str | None]:
    try:
        chat = await bot.get_chat(user_id, request_timeout=30)
    except (TelegramBadRequest, TelegramForbiddenError):
        return None, None
    except TelegramNetworkError as exc:
        logger.warning("Telegram network error while resolving user identity: user_id=%s error=%s", user_id, exc)
        return None, None

    username = getattr(chat, "username", None)
    full_name = getattr(chat, "full_name", None)

    if not full_name:
        first_name = getattr(chat, "first_name", None)
        last_name = getattr(chat, "last_name", None)
        full_name = " ".join(part for part in [first_name, last_name] if part) or None

    return username, full_name


async def _refresh_current_admin_profile(message: Message) -> None:
    if not message.from_user:
        return

    if message.from_user.id == settings.owner_id:
        return

    admin = await get_bot_admin(message.from_user.id)

    if admin and admin.get("enabled"):
        await update_bot_admin_profile(
            user_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        )


async def _show_main_menu(message: Message) -> None:
    if not message.from_user:
        return

    is_owner = message.from_user.id == settings.owner_id

    await safe_answer(
        message,
        "Меню управления GP Verify:",
        reply_markup=admin_menu_keyboard(is_owner=is_owner),
    )


async def _show_admins_menu(message: Message) -> None:
    if not message.from_user or message.from_user.id != settings.owner_id:
        await safe_answer(message, "Управление администраторами доступно только владельцу бота.")
        return

    await safe_answer(
        message,
        "👥 Управление администраторами",
        reply_markup=admins_menu_keyboard(),
    )


async def _show_my_id(message: Message) -> None:
    if not message.from_user:
        return

    username = f"@{message.from_user.username}" if message.from_user.username else "не задан"
    full_name = message.from_user.full_name or "не указано"

    await safe_answer(
        message,
        "Ваш Telegram ID: "
        f"{message.from_user.id}\n\n"
        f"Username: {username}\n"
        f"Имя: {full_name}",
    )


async def _show_my_profile(message: Message) -> None:
    if not message.from_user:
        return

    if message.from_user.id == settings.owner_id:
        role = "👑 Владелец"
    elif await require_admin(message.from_user):
        role = "🛡 Администратор"
    else:
        role = "👤 Пользователь"

    username = f"@{message.from_user.username}" if message.from_user.username else "не задан"
    full_name = message.from_user.full_name or "не указано"

    await safe_answer(
        message,
        "👤 Мой профиль\n\n"
        f"Telegram ID: {message.from_user.id}\n"
        f"Username: {username}\n"
        f"Имя: {full_name}\n"
        f"Роль: {role}",
    )


async def _show_bot_admins(message: Message) -> None:
    if not message.from_user or message.from_user.id != settings.owner_id:
        await safe_answer(message, "Список администраторов доступен только владельцу бота.")
        return

    admins = await list_bot_admins(enabled_only=True)

    lines = [
        "👑 Владелец\n",
        _format_admin_line(
            user_id=settings.owner_id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        ),
        "",
        "👥 Администраторы\n",
    ]

    if not admins:
        lines.append("Администраторы не добавлены.")
    else:
        for admin in admins:
            lines.append(
                _format_admin_line(
                    user_id=int(admin["user_id"]),
                    username=admin.get("username"),
                    full_name=admin.get("full_name"),
                )
            )

        lines.append("")
        lines.append(f"Всего: {len(admins)}")

    await safe_answer(message, "\n".join(lines))


async def _add_admin_by_id(
    *,
    message: Message,
    bot: Bot,
    user_id: int,
    source: str,
) -> None:
    assert message.from_user is not None

    if message.from_user.id != settings.owner_id:
        await safe_answer(message, "Добавление администраторов доступно только владельцу бота.")
        return

    if user_id == settings.owner_id:
        await safe_answer(message, "Владелец уже имеет все права администратора.")
        return

    existing = await get_bot_admin(user_id)
    username, full_name = await _resolve_user_identity(bot, user_id)

    if existing and existing.get("enabled"):
        if username or full_name:
            await update_bot_admin_profile(
                user_id=user_id,
                username=username,
                full_name=full_name,
            )

        await safe_answer(
            message,
            "⚠️ Пользователь уже является администратором.\n\n"
            + _format_admin_line(
                user_id=user_id,
                username=username or existing.get("username"),
                full_name=full_name or existing.get("full_name"),
            ),
        )
        return

    await upsert_bot_admin(
        user_id=user_id,
        username=username,
        full_name=full_name,
        actor_user_id=message.from_user.id,
    )

    await write_audit(
        actor_user_id=message.from_user.id,
        actor_username=message.from_user.username,
        actor_full_name=message.from_user.full_name,
        action="bot_admin_added",
        entity_type="bot_admin",
        entity_id=str(user_id),
        details={
            "source": source,
            "username": username,
            "full_name": full_name,
        },
    )

    await safe_answer(
        message,
        "✅ Администратор добавлен.\n\n"
        + _format_admin_line(
            user_id=user_id,
            username=username,
            full_name=full_name,
        ),
    )


async def _remove_admin_by_id(
    *,
    message: Message,
    user_id: int,
    source: str,
) -> None:
    assert message.from_user is not None

    if message.from_user.id != settings.owner_id:
        await safe_answer(message, "Удаление администраторов доступно только владельцу бота.")
        return

    if user_id == settings.owner_id:
        await safe_answer(message, "Нельзя удалить владельца из администраторов.")
        return

    admin = await remove_bot_admin(
        user_id=user_id,
        actor_user_id=message.from_user.id,
    )

    if not admin:
        await safe_answer(message, "Администратор не найден или уже отключен.")
        return

    await write_audit(
        actor_user_id=message.from_user.id,
        actor_username=message.from_user.username,
        actor_full_name=message.from_user.full_name,
        action="bot_admin_removed",
        entity_type="bot_admin",
        entity_id=str(user_id),
        details={
            "source": source,
            "username": admin.get("username"),
            "full_name": admin.get("full_name"),
        },
    )

    await safe_answer(
        message,
        "✅ Администратор удален.\n\n"
        + _format_admin_line(
            user_id=user_id,
            username=admin.get("username"),
            full_name=admin.get("full_name"),
        ),
    )


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

    await _refresh_current_admin_profile(message)

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

    await _refresh_current_admin_profile(message)

    is_owner = message.from_user.id == settings.owner_id

    await safe_answer(message, 
        "Меню управления GP Verify:",
        reply_markup=admin_menu_keyboard(is_owner=is_owner),
    )



@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await _show_my_id(message)


@router.message(Command("whoami"))
async def cmd_whoami(message: Message) -> None:
    await _show_my_profile(message)


@router.message(Command("admins"))
async def cmd_admins(message: Message) -> None:
    await _show_bot_admins(message)


@router.message(Command("add_admin"))
async def add_admin_command(message: Message, bot: Bot) -> None:
    if not message.from_user or message.from_user.id != settings.owner_id:
        await safe_answer(message, "Добавление администраторов доступно только владельцу бота.")
        return

    raw_user_id = _command_arg(message, "/add_admin")
    user_id = _parse_user_id(raw_user_id)

    if user_id is None:
        await safe_answer(
            message,
            "Некорректный Telegram ID.\n\n"
            "Пример:\n"
            "/add_admin 123456789",
        )
        return

    await _add_admin_by_id(
        message=message,
        bot=bot,
        user_id=user_id,
        source="command",
    )


@router.message(Command("remove_admin"))
async def remove_admin_command(message: Message) -> None:
    if not message.from_user or message.from_user.id != settings.owner_id:
        await safe_answer(message, "Удаление администраторов доступно только владельцу бота.")
        return

    raw_user_id = _command_arg(message, "/remove_admin")
    user_id = _parse_user_id(raw_user_id)

    if user_id is None:
        await safe_answer(
            message,
            "Некорректный Telegram ID.\n\n"
            "Пример:\n"
            "/remove_admin 123456789",
        )
        return

    await _remove_admin_by_id(
        message=message,
        user_id=user_id,
        source="command",
    )


@router.message(Command("cancel"))
async def cancel_state(message: Message, state: FSMContext) -> None:
    await state.clear()

    if message.from_user and message.from_user.id == settings.owner_id:
        await safe_answer(
            message,
            "Действие отменено.",
            reply_markup=admins_menu_keyboard(),
        )
    else:
        await safe_answer(message, "Действие отменено.")


@router.message(AdminStates.waiting_add_admin_id)
async def process_add_admin_id(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.from_user or message.from_user.id != settings.owner_id:
        await state.clear()
        return

    if message.text == BTN_BACK:
        await state.clear()
        await _show_admins_menu(message)
        return

    user_id = _parse_user_id(message.text)

    if user_id is None:
        await safe_answer(
            message,
            "Некорректный Telegram ID.\n\n"
            "Введите только цифры, например:\n"
            "123456789\n\n"
            "Для отмены: /cancel",
        )
        return

    await state.clear()

    await _add_admin_by_id(
        message=message,
        bot=bot,
        user_id=user_id,
        source="menu",
    )


@router.message(AdminStates.waiting_remove_admin_id)
async def process_remove_admin_id(message: Message, state: FSMContext) -> None:
    if not message.from_user or message.from_user.id != settings.owner_id:
        await state.clear()
        return

    if message.text == BTN_BACK:
        await state.clear()
        await _show_admins_menu(message)
        return

    user_id = _parse_user_id(message.text)

    if user_id is None:
        await safe_answer(
            message,
            "Некорректный Telegram ID.\n\n"
            "Введите только цифры, например:\n"
            "123456789\n\n"
            "Для отмены: /cancel",
        )
        return

    await state.clear()

    await _remove_admin_by_id(
        message=message,
        user_id=user_id,
        source="menu",
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



@router.message(F.text == BTN_ADMINS)
async def menu_admins(message: Message) -> None:
    await _show_admins_menu(message)


@router.message(F.text == BTN_ADMIN_ADD)
async def menu_add_admin(message: Message, state: FSMContext) -> None:
    if not message.from_user or message.from_user.id != settings.owner_id:
        await safe_answer(message, "Добавление администраторов доступно только владельцу бота.")
        return

    await state.set_state(AdminStates.waiting_add_admin_id)

    await safe_answer(
        message,
        "Введите Telegram ID пользователя.\n\n"
        "Пример:\n"
        "123456789\n\n"
        "Для отмены: /cancel",
        reply_markup=admins_menu_keyboard(),
    )


@router.message(F.text == BTN_ADMIN_REMOVE)
async def menu_remove_admin(message: Message, state: FSMContext) -> None:
    if not message.from_user or message.from_user.id != settings.owner_id:
        await safe_answer(message, "Удаление администраторов доступно только владельцу бота.")
        return

    admins = await list_bot_admins(enabled_only=True)

    if not admins:
        await safe_answer(message, "Администраторы не добавлены.")
        return

    lines = [
        "Введите Telegram ID администратора для удаления.\n",
        "Текущие администраторы:\n",
    ]

    for admin in admins:
        lines.append(
            _format_admin_line(
                user_id=int(admin["user_id"]),
                username=admin.get("username"),
                full_name=admin.get("full_name"),
            )
        )

    lines.extend(
        [
            "",
            "Для отмены: /cancel",
        ]
    )

    await state.set_state(AdminStates.waiting_remove_admin_id)

    await safe_answer(
        message,
        "\n".join(lines),
        reply_markup=admins_menu_keyboard(),
    )


@router.message(F.text == BTN_ADMIN_LIST)
async def menu_admin_list(message: Message) -> None:
    await _show_bot_admins(message)


@router.message(F.text == BTN_MY_PROFILE)
async def menu_my_profile(message: Message) -> None:
    await _show_my_profile(message)


@router.message(F.text == BTN_BACK)
async def menu_back(message: Message) -> None:
    if not message.from_user or not await require_admin(message.from_user):
        return

    await _show_main_menu(message)


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
        "/id – показать ваш Telegram ID\n"
        "/whoami – показать профиль и роль\n"
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
            "/admins – список администраторов\n"
            "/add_admin 123456789 – добавить администратора\n"
            "/remove_admin 123456789 – удалить администратора\n"
            "/remove_source_ID – исключить ЗГ из обработки\n"
            "/remove_target_ID – исключить целевой чат из обработки\n"
        )

    await safe_answer(message, text)