"""Админские команды: перезапуск бота.

Безопасность:
- Команда доступна ТОЛЬКО пользователям из ADMIN_IDS (проверка по числовому
  user_id, а не по нику — ник можно сменить).
- Перезапуск не требует прав: процесс завершается, а systemd (Restart=always)
  поднимает бота заново.
"""
import asyncio
import logging
import os
import signal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config import Config

log = logging.getLogger(__name__)
router = Router()


def _is_admin(message: Message, config: Config) -> bool:
    return message.from_user is not None and message.from_user.id in config.admin_ids


@router.message(Command("restart"))
async def cmd_restart(message: Message, config: Config) -> None:
    if not _is_admin(message, config):
        return
    await message.answer("♻️ Перезапускаю бота…")
    log.info("Перезапуск бота по команде пользователя %s", message.from_user.id)
    # Корректно завершаем процесс — systemd (Restart=always) поднимет заново.
    # Небольшая пауза, чтобы сообщение успело уйти.
    await asyncio.sleep(0.5)
    os.kill(os.getpid(), signal.SIGTERM)


@router.callback_query(F.data == "menu:restart")
async def menu_restart(cb: CallbackQuery, config: Config) -> None:
    # Проверяем по тому, КТО нажал (cb.from_user), а не по чату.
    if cb.from_user is None or cb.from_user.id not in config.admin_ids:
        await cb.answer("Недоступно", show_alert=True)
        return
    await cb.message.answer("♻️ Перезапускаю бота…")
    await cb.answer()
    log.info("Перезапуск бота из меню пользователем %s", cb.from_user.id)
    await asyncio.sleep(0.5)
    os.kill(os.getpid(), signal.SIGTERM)
