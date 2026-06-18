import os


class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
    OWNER_ID: int = int(os.getenv("OWNER_ID", "0"))

    DB_PATH: str = os.getenv("DB_PATH", "/data/bot.sqlite3")
    LOG_PATH: str = os.getenv("LOG_PATH", "/logs/bot.log")

    DEFAULT_REACTION: str = os.getenv("DEFAULT_REACTION", "✅")
    CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "900"))

    ADMIN_IDS_RAW: str = os.getenv("ADMIN_IDS", "").strip()

    @property
    def admin_ids(self) -> set[int]:
        result = {self.OWNER_ID}

        if self.ADMIN_IDS_RAW:
            for item in self.ADMIN_IDS_RAW.split(","):
                item = item.strip()
                if item.isdigit():
                    result.add(int(item))

        return result


config = Config()


def validate_config() -> None:
    if not config.BOT_TOKEN or config.BOT_TOKEN == "PASTE_BOT_TOKEN_HERE":
        raise RuntimeError("BOT_TOKEN is not set")

    if not config.OWNER_ID:
        raise RuntimeError("OWNER_ID is not set")