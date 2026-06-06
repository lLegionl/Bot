"""Точка входа: запуск бота."""
import asyncio
import logging
import socket

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiohttp.resolver import ThreadedResolver

from config import load_config
from database import Database
from handlers import router
from admin import router as admin_router
from chat import router as chat_router
from scheduler import ReminderScheduler


def build_session(proxy_url: str | None) -> AiohttpSession:
    """Создаёт сессию подключения к Telegram.

    Если PROXY_URL задан — идём через прокси.
    Если нет — прямое подключение, принудительно по IPv4 (как `curl -4`),
    чтобы не зависать на нерабочем IPv6.
    """
    if proxy_url:
        return AiohttpSession(proxy=proxy_url)

    session = AiohttpSession()
    session._connector_init["family"] = socket.AF_INET
    session._connector_init["resolver"] = ThreadedResolver()
    return session


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = load_config()

    bot = Bot(
        token=config.bot_token,
        session=build_session(config.proxy_url),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    if config.proxy_url:
        logging.getLogger(__name__).info("Используется прокси для подключения к Telegram.")
    else:
        logging.getLogger(__name__).info("Прямое подключение (IPv4).")

    db = Database(config.db_path)
    await db.init()

    scheduler = ReminderScheduler(bot, db, config.timezone)
    scheduler.start()
    await scheduler.reschedule_all()

    dp = Dispatcher()
    dp.include_router(admin_router)   # админские команды — первыми
    dp.include_router(chat_router)    # режим чата — до разбора напоминаний
    dp.include_router(router)

    logging.getLogger(__name__).info("Бот запущен. Админов: %d", len(config.admin_ids))
    try:
        await dp.start_polling(bot, db=db, scheduler=scheduler, config=config)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
