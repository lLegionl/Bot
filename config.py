"""Загрузка конфигурации из переменных окружения (.env)."""
import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    bot_token: str
    timezone: ZoneInfo
    db_path: str
    default_repeat_count: int
    default_interval_minutes: int
    proxy_url: str | None
    admin_ids: set[int]
    deepseek_api_key: str | None
    deepseek_model: str
    openrouter_api_key: str | None
    openrouter_model: str


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "BOT_TOKEN не задан. Создайте файл .env и впишите туда токен от @BotFather."
        )
    tz_name = os.getenv("TIMEZONE", "Europe/Moscow")
    admin_ids = {
        int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x
    }
    return Config(
        bot_token=token,
        timezone=ZoneInfo(tz_name),
        db_path=os.getenv("DB_PATH", "reminders.db"),
        default_repeat_count=int(os.getenv("DEFAULT_REPEAT_COUNT", "3")),
        default_interval_minutes=int(os.getenv("DEFAULT_INTERVAL_MINUTES", "5")),
        proxy_url=os.getenv("PROXY_URL") or None,
        admin_ids=admin_ids,
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY") or None,
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY") or None,
        openrouter_model=os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-r1:free"),
    )
