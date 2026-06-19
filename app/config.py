import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str
    owner_id: int
    db_path: str
    cache_ttl_minutes: int
    default_reaction: str
    admin_approval_mode: str


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default

    try:
        return int(value)
    except ValueError:
        return default


settings = Settings(
    bot_token=os.getenv("BOT_TOKEN", ""),
    owner_id=_int_env("OWNER_ID", 0),
    db_path=os.getenv("DB_PATH", "./data/bot.sqlite3"),
    cache_ttl_minutes=_int_env("CACHE_TTL_MINUTES", 30),
    default_reaction=os.getenv("DEFAULT_REACTION", "👌"),
    # Режим управления администраторами:
    # soft   - админы выполняют действия сразу, owner получает уведомления
    # strict - действия админов требуют подтверждения owner
    admin_approval_mode=os.getenv("ADMIN_APPROVAL_MODE", "soft"),
)
