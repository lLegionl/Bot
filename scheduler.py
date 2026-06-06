"""Планировщик: отправляет напоминания и управляет повторами.

Логика повторов:
- В назначенное время приходит первое уведомление с кнопкой «Стоп».
- Если пользователь не нажал «Стоп», через `interval_minutes` приходит
  повтор. Так до `repeat_total` повторов, после чего напоминание считается
  выполненным автоматически.
- Нажатие «Стоп» немедленно прекращает все будущие повторы.

Источник правды — база данных. APScheduler хранит задания в памяти, поэтому
при старте бот заново планирует все активные напоминания (`reschedule_all`).
"""
import html
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import Database

log = logging.getLogger(__name__)


def _stop_keyboard(reminder_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Стоп / Выполнено", callback_data=f"stop:{reminder_id}")]
        ]
    )


class ReminderScheduler:
    def __init__(self, bot: Bot, db: Database, tz: ZoneInfo):
        self.bot = bot
        self.db = db
        self.tz = tz
        self.scheduler = AsyncIOScheduler(timezone=tz)

    def start(self) -> None:
        self.scheduler.start()

    def _job_id(self, reminder_id: int) -> str:
        return f"rem_{reminder_id}"

    def _add_job(self, reminder_id: int, run_date: datetime) -> None:
        self.scheduler.add_job(
            self._fire,
            trigger="date",
            run_date=run_date,
            args=[reminder_id],
            id=self._job_id(reminder_id),
            replace_existing=True,
            misfire_grace_time=3600,  # стерпеть опоздание до часа
        )

    def _remove_job(self, reminder_id: int) -> None:
        try:
            self.scheduler.remove_job(self._job_id(reminder_id))
        except JobLookupError:
            pass

    def schedule_new(self, reminder_id: int, fire_at: datetime) -> None:
        self._add_job(reminder_id, fire_at)

    async def cancel(self, reminder_id: int) -> None:
        await self.db.set_status(reminder_id, "cancelled")
        self._remove_job(reminder_id)

    async def stop(self, reminder_id: int) -> None:
        await self.db.set_status(reminder_id, "done")
        self._remove_job(reminder_id)

    async def reschedule_all(self) -> None:
        """Восстановить расписание после перезапуска бота."""
        now = datetime.now(self.tz)
        rows = await self.db.all_active()
        for rem in rows:
            run_at = datetime.fromisoformat(rem["next_fire_at"])
            if run_at < now:
                # Напоминание было пропущено во время простоя — напомним скоро.
                run_at = now + timedelta(seconds=10)
            self._add_job(rem["id"], run_at)
        if rows:
            log.info("Восстановлено активных напоминаний: %d", len(rows))

    async def _fire(self, reminder_id: int) -> None:
        rem = await self.db.get_reminder(reminder_id)
        if not rem or rem["status"] != "active":
            return

        safe_text = html.escape(rem["text"])
        try:
            await self.bot.send_message(
                rem["chat_id"],
                f"🔔 <b>Напоминание:</b> {safe_text}",
                reply_markup=_stop_keyboard(reminder_id),
            )
        except Exception:
            log.exception("Не удалось отправить напоминание %d", reminder_id)

        repeats_done = rem["repeats_done"] + 1
        if repeats_done <= rem["repeat_total"]:
            next_at = datetime.now(self.tz) + timedelta(minutes=rem["interval_minutes"])
            await self.db.record_fire(
                reminder_id, repeats_done, next_at.isoformat(), "active"
            )
            self._add_job(reminder_id, next_at)
        else:
            # Повторы закончились — закрываем напоминание.
            await self.db.record_fire(
                reminder_id, repeats_done, rem["next_fire_at"], "done"
            )
