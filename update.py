"""Обновление бота из git-репозитория.

Кнопки и команды доступны только админам (ADMIN_IDS), проверка по числовому id.
- «Проверить обновление» — git fetch + сравнение с origin, ничего не меняет.
- «Обновить и перезапустить» — при отсутствии локальных правок делает git pull
  (--ff-only), при изменении requirements.txt ставит зависимости, затем
  перезапускается (systemd с Restart=always поднимет процесс заново).

Git работает в каталоге этого файла (там же лежит бот) от имени пользователя
сервиса — root не нужен, т.к. каталог принадлежит ему.
"""
import asyncio
import logging
import os
import signal
import sys

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config import Config

log = logging.getLogger(__name__)
router = Router()

REPO_DIR = os.path.dirname(os.path.abspath(__file__))


def _is_admin(uid: int | None, config: Config) -> bool:
    return uid is not None and uid in config.admin_ids


async def _run(args: list[str]) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=REPO_DIR,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    return proc.returncode, out.decode(errors="replace").strip()


async def _branch() -> str:
    rc, out = await _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return out if rc == 0 and out else "main"


async def _check_into(message: Message) -> None:
    msg = await message.answer("🔄 Проверяю обновления…")
    rc, out = await _run(["git", "fetch", "--quiet"])
    if rc != 0:
        await msg.edit_text(f"⚠️ git fetch не удался:\n<code>{out[:600]}</code>")
        return
    branch = await _branch()
    rc, count = await _run(["git", "rev-list", "--count", f"HEAD..origin/{branch}"])
    if rc != 0:
        await msg.edit_text(f"⚠️ Не удалось сравнить версии:\n<code>{count[:600]}</code>")
        return
    n = count.strip() or "0"
    if n == "0":
        await msg.edit_text("✅ Обновлений нет — установлена последняя версия.")
        return
    rc, changes = await _run(
        ["git", "log", "--oneline", "--no-decorate", f"HEAD..origin/{branch}"]
    )
    body = changes[:1500] if rc == 0 else ""
    await msg.edit_text(
        f"⬇️ Доступно обновление: <b>{n}</b> коммит(ов).\n\n"
        f"Изменения:\n<code>{body}</code>\n\n"
        "Нажмите «⬇️ Обновить и перезапустить» в меню (/menu)."
    )


async def _update_into(message: Message) -> bool:
    """Возвращает True, если нужно перезапуститься после ответа."""
    msg = await message.answer("⬇️ Обновляю…")

    rc, dirty = await _run(["git", "status", "--porcelain"])
    if rc == 0 and dirty.strip():
        await msg.edit_text(
            "⚠️ На сервере есть локальные изменения — обновление отменено, "
            "чтобы их не потерять:\n"
            f"<code>{dirty[:800]}</code>\n\n"
            "Закоммитьте или откатите их (git checkout .) и повторите."
        )
        return False

    rc, old = await _run(["git", "rev-parse", "HEAD"])
    branch = await _branch()
    rc, out = await _run(["git", "pull", "--ff-only", "origin", branch])
    if rc != 0:
        await msg.edit_text(f"⚠️ git pull не удался:\n<code>{out[:800]}</code>")
        return False

    rc, new = await _run(["git", "rev-parse", "HEAD"])
    if old.strip() == new.strip():
        await msg.edit_text("✅ Уже последняя версия — обновлять нечего.")
        return False

    note = ""
    rc, changed = await _run(["git", "diff", "--name-only", old.strip(), new.strip()])
    if rc == 0 and "requirements.txt" in changed:
        rc, pout = await _run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        note = (
            "\nЗависимости обновлены."
            if rc == 0
            else f"\n⚠️ Ошибка установки зависимостей:\n<code>{pout[:500]}</code>"
        )

    await msg.edit_text(f"✅ Обновлено до последней версии.{note}\n♻️ Перезапускаю бота…")
    return True


# ---------- Кнопки меню ----------


@router.callback_query(F.data == "menu:update_check")
async def cb_check(cb: CallbackQuery, config: Config) -> None:
    if not _is_admin(cb.from_user.id if cb.from_user else None, config):
        await cb.answer("Недоступно", show_alert=True)
        return
    await cb.answer()
    await _check_into(cb.message)


@router.callback_query(F.data == "menu:update_pull")
async def cb_pull(cb: CallbackQuery, config: Config) -> None:
    if not _is_admin(cb.from_user.id if cb.from_user else None, config):
        await cb.answer("Недоступно", show_alert=True)
        return
    await cb.answer()
    if await _update_into(cb.message):
        await asyncio.sleep(1.0)
        os.kill(os.getpid(), signal.SIGTERM)


# ---------- Команды (дублируют кнопки) ----------


@router.message(Command("update_check"))
async def cmd_check(message: Message, config: Config) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None, config):
        return
    await _check_into(message)


@router.message(Command("update"))
async def cmd_update(message: Message, config: Config) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None, config):
        return
    if await _update_into(message):
        await asyncio.sleep(1.0)
        os.kill(os.getpid(), signal.SIGTERM)
