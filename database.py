"""Слой работы с базой данных (SQLite через aiosqlite).

Хранит сами напоминания и индивидуальные настройки повторов для каждого
пользователя. База данных — единственный источник правды: при перезапуске
бот восстанавливает все активные напоминания именно отсюда.
"""
import aiosqlite


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id         INTEGER NOT NULL,
                text            TEXT    NOT NULL,
                next_fire_at    TEXT    NOT NULL,   -- ISO 8601 с таймзоной
                repeat_total    INTEGER NOT NULL,   -- сколько ДОПОЛНИТЕЛЬНЫХ повторов
                repeats_done    INTEGER NOT NULL DEFAULT 0,
                interval_minutes INTEGER NOT NULL,
                status          TEXT    NOT NULL DEFAULT 'active', -- active|done|cancelled
                created_at      TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_settings (
                chat_id          INTEGER PRIMARY KEY,
                repeat_count     INTEGER NOT NULL,
                interval_minutes INTEGER NOT NULL
            );
            """
        )
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    # ---------- Напоминания ----------

    async def create_reminder(
        self,
        chat_id: int,
        text: str,
        fire_at_iso: str,
        repeat_total: int,
        interval_minutes: int,
        created_at_iso: str,
    ) -> int:
        cur = await self.conn.execute(
            """INSERT INTO reminders
               (chat_id, text, next_fire_at, repeat_total, repeats_done,
                interval_minutes, status, created_at)
               VALUES (?, ?, ?, ?, 0, ?, 'active', ?)""",
            (chat_id, text, fire_at_iso, repeat_total, interval_minutes, created_at_iso),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def get_reminder(self, reminder_id: int) -> dict | None:
        cur = await self.conn.execute(
            "SELECT * FROM reminders WHERE id = ?", (reminder_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def record_fire(
        self, reminder_id: int, repeats_done: int, next_fire_at: str, status: str
    ) -> None:
        await self.conn.execute(
            "UPDATE reminders SET repeats_done = ?, next_fire_at = ?, status = ? WHERE id = ?",
            (repeats_done, next_fire_at, status, reminder_id),
        )
        await self.conn.commit()

    async def set_status(self, reminder_id: int, status: str) -> None:
        await self.conn.execute(
            "UPDATE reminders SET status = ? WHERE id = ?", (status, reminder_id)
        )
        await self.conn.commit()

    async def active_for_chat(self, chat_id: int) -> list[dict]:
        cur = await self.conn.execute(
            "SELECT * FROM reminders WHERE chat_id = ? AND status = 'active' ORDER BY next_fire_at",
            (chat_id,),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def all_active(self) -> list[dict]:
        cur = await self.conn.execute("SELECT * FROM reminders WHERE status = 'active'")
        return [dict(r) for r in await cur.fetchall()]

    # ---------- Настройки пользователя ----------

    async def get_settings(self, chat_id: int) -> dict | None:
        cur = await self.conn.execute(
            "SELECT * FROM user_settings WHERE chat_id = ?", (chat_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def set_settings(
        self, chat_id: int, repeat_count: int, interval_minutes: int
    ) -> None:
        await self.conn.execute(
            """INSERT INTO user_settings (chat_id, repeat_count, interval_minutes)
               VALUES (?, ?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET
                 repeat_count = excluded.repeat_count,
                 interval_minutes = excluded.interval_minutes""",
            (chat_id, repeat_count, interval_minutes),
        )
        await self.conn.commit()
