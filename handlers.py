"""Обработчики команд и нажатий кнопок."""
import html
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from config import Config
from database import Database
from parsing import parse_reminder
from scheduler import ReminderScheduler

router = Router()

# Границы значений настроек.
REPEAT_MIN, REPEAT_MAX = 0, 20
INTERVAL_MIN, INTERVAL_MAX = 1, 1440

# Подписи кнопок главного меню (reply-клавиатура снизу).
BTN_LIST = "📋 Список"
BTN_SETTINGS = "⚙️ Настройки"
BTN_HELP = "❓ Помощь"
BTN_CHAT = "💬 Чат"


def _main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_LIST), KeyboardButton(text=BTN_SETTINGS)],
            [KeyboardButton(text=BTN_CHAT), KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Напишите напоминание или выберите кнопку…",
    )


def _menu_kb(is_admin: bool) -> InlineKeyboardMarkup:
    """Стартовое меню с выбором раздела. Для админа добавляется перезагрузка."""
    rows = [
        [InlineKeyboardButton(text="📋 Список напоминаний", callback_data="menu:list")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu:settings")],
        [InlineKeyboardButton(text="💬 Чат с ИИ", callback_data="menu:chat")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="menu:help")],
    ]
    if is_admin:
        rows.append(
            [InlineKeyboardButton(text="♻️ Перезагрузить бота", callback_data="menu:restart")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _menu_text() -> str:
    return "🏠 <b>Главное меню</b>\n\nВыберите раздел:"

HELP_TEXT = (
    "🤖 <b>Бот-напоминалка</b>\n\n"
    "Просто напишите, о чём и когда напомнить:\n"
    "• <i>напомни купить продукты завтра в 12</i>\n"
    "• <i>позвонить маме через 2 часа</i>\n"
    "• <i>сдать отчёт 15 января в 9:30</i>\n"
    "• <i>тренировка в пятницу в 18:00</i>\n\n"
    "Когда сработает напоминание, нажмите «✅ Стоп / Выполнено». "
    "Если не нажать — бот повторит его ещё раз через заданный интервал.\n\n"
    "<b>Кнопки снизу:</b>\n"
    "📋 Список — активные напоминания\n"
    "⚙️ Настройки — число повторов и интервал\n"
    "❓ Помощь — эта справка\n\n"
    "Те же действия командами: /list, /settings, /help"
)


async def _ensure_settings(db: Database, config: Config, chat_id: int) -> dict:
    s = await db.get_settings(chat_id)
    if s is None:
        await db.set_settings(
            chat_id, config.default_repeat_count, config.default_interval_minutes
        )
        s = {
            "chat_id": chat_id,
            "repeat_count": config.default_repeat_count,
            "interval_minutes": config.default_interval_minutes,
        }
    return s


def _settings_view(s: dict) -> tuple[str, InlineKeyboardMarkup]:
    text = (
        "⚙️ <b>Настройки повторов</b>\n\n"
        f"Количество повторов: <b>{s['repeat_count']}</b>\n"
        f"Интервал между повторами: <b>{s['interval_minutes']} мин</b>\n\n"
        "Эти настройки применяются к новым напоминаниям."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➖ повтор", callback_data="set:rep:dec"),
                InlineKeyboardButton(text=f"{s['repeat_count']}", callback_data="set:noop"),
                InlineKeyboardButton(text="➕ повтор", callback_data="set:rep:inc"),
            ],
            [
                InlineKeyboardButton(text="➖ мин", callback_data="set:int:dec"),
                InlineKeyboardButton(text=f"{s['interval_minutes']} мин", callback_data="set:noop"),
                InlineKeyboardButton(text="➕ мин", callback_data="set:int:inc"),
            ],
            [InlineKeyboardButton(text="Закрыть", callback_data="set:close")],
        ]
    )
    return text, kb


def _list_view(reminders: list[dict]) -> tuple[str, InlineKeyboardMarkup | None]:
    if not reminders:
        return "У вас нет активных напоминаний.", None
    lines = ["📋 <b>Активные напоминания:</b>\n"]
    buttons = []
    for r in reminders:
        dt = datetime.fromisoformat(r["next_fire_at"])
        when = dt.strftime("%d.%m.%Y %H:%M")
        lines.append(f"• {html.escape(r['text'])} — <i>{when}</i>")
        short = (r["text"][:25] + "…") if len(r["text"]) > 25 else r["text"]
        buttons.append(
            [InlineKeyboardButton(text=f"❌ {short}", callback_data=f"cancel:{r['id']}")]
        )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


async def _send_list(message: Message, db: Database) -> None:
    reminders = await db.active_for_chat(message.chat.id)
    text, kb = _list_view(reminders)
    await message.answer(text, reply_markup=kb)


async def _send_settings(message: Message, db: Database, config: Config) -> None:
    s = await _ensure_settings(db, config, message.chat.id)
    text, kb = _settings_view(s)
    await message.answer(text, reply_markup=kb)


@router.message(CommandStart())
async def cmd_start(message: Message, config: Config) -> None:
    is_admin = message.from_user is not None and message.from_user.id in config.admin_ids
    await message.answer(HELP_TEXT, reply_markup=_main_keyboard())
    await message.answer(_menu_text(), reply_markup=_menu_kb(is_admin))


@router.message(Command("menu"))
async def cmd_menu(message: Message, config: Config) -> None:
    is_admin = message.from_user is not None and message.from_user.id in config.admin_ids
    await message.answer(_menu_text(), reply_markup=_menu_kb(is_admin))


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=_main_keyboard())


@router.message(Command("settings"))
async def cmd_settings(message: Message, db: Database, config: Config) -> None:
    await _send_settings(message, db, config)


@router.message(Command("list"))
async def cmd_list(message: Message, db: Database) -> None:
    await _send_list(message, db)


# --- Кнопки главного меню (приходят обычным текстом, ловим ДО разбора напоминаний) ---


@router.message(F.text == BTN_LIST)
async def btn_list(message: Message, db: Database) -> None:
    await _send_list(message, db)


@router.message(F.text == BTN_SETTINGS)
async def btn_settings(message: Message, db: Database, config: Config) -> None:
    await _send_settings(message, db, config)


@router.message(F.text == BTN_HELP)
async def btn_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=_main_keyboard())


@router.callback_query(F.data == "menu:list")
async def menu_list(cb: CallbackQuery, db: Database) -> None:
    await _send_list(cb.message, db)
    await cb.answer()


@router.callback_query(F.data == "menu:settings")
async def menu_settings(cb: CallbackQuery, db: Database, config: Config) -> None:
    await _send_settings(cb.message, db, config)
    await cb.answer()


@router.callback_query(F.data == "menu:help")
async def menu_help(cb: CallbackQuery) -> None:
    await cb.message.answer(HELP_TEXT, reply_markup=_main_keyboard())
    await cb.answer()


@router.callback_query(F.data.startswith("set:"))
async def on_settings(cb: CallbackQuery, db: Database, config: Config) -> None:
    action = cb.data.split(":", 1)[1]
    if action == "close":
        await cb.message.edit_text("Настройки сохранены ✅")
        await cb.answer()
        return
    if action == "noop":
        await cb.answer()
        return

    s = await _ensure_settings(db, config, cb.message.chat.id)
    rc, im = s["repeat_count"], s["interval_minutes"]
    if action == "rep:inc":
        rc = min(REPEAT_MAX, rc + 1)
    elif action == "rep:dec":
        rc = max(REPEAT_MIN, rc - 1)
    elif action == "int:inc":
        im = min(INTERVAL_MAX, im + 1)
    elif action == "int:dec":
        im = max(INTERVAL_MIN, im - 1)

    await db.set_settings(cb.message.chat.id, rc, im)
    text, kb = _settings_view({"repeat_count": rc, "interval_minutes": im})
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("stop:"))
async def on_stop(cb: CallbackQuery, db: Database, scheduler: ReminderScheduler) -> None:
    reminder_id = int(cb.data.split(":", 1)[1])
    rem = await db.get_reminder(reminder_id)
    await scheduler.stop(reminder_id)
    text = html.escape(rem["text"]) if rem else ""
    await cb.message.edit_text(f"✅ Остановлено: {text}")
    await cb.answer("Напоминание остановлено")


@router.callback_query(F.data.startswith("cancel:"))
async def on_cancel(cb: CallbackQuery, db: Database, scheduler: ReminderScheduler) -> None:
    reminder_id = int(cb.data.split(":", 1)[1])
    await scheduler.cancel(reminder_id)
    reminders = await db.active_for_chat(cb.message.chat.id)
    text, kb = _list_view(reminders)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer("Отменено")


@router.message(F.text & ~F.text.startswith("/"))
async def on_text(
    message: Message, db: Database, scheduler: ReminderScheduler, config: Config
) -> None:
    text, dt, error = parse_reminder(message.text, config.timezone)
    if error and dt is None:
        await message.answer(
            "Не понял дату и время 🤔\n"
            "Примеры: <i>купить продукты завтра в 12</i>, "
            "<i>позвонить через 30 минут</i>, <i>отчёт 15 января в 9:30</i>."
        )
        return
    if error:
        await message.answer(f"⚠️ {error}")
        return

    s = await _ensure_settings(db, config, message.chat.id)
    now_iso = datetime.now(config.timezone).isoformat()
    reminder_id = await db.create_reminder(
        chat_id=message.chat.id,
        text=text,
        fire_at_iso=dt.isoformat(),
        repeat_total=s["repeat_count"],
        interval_minutes=s["interval_minutes"],
        created_at_iso=now_iso,
    )
    scheduler.schedule_new(reminder_id, dt)

    when = dt.strftime("%d.%m.%Y в %H:%M")
    await message.answer(
        f"✅ Напомню: <b>{html.escape(text)}</b>\n"
        f"🗓 {when}\n"
        f"🔁 Повторов при отсутствии ответа: {s['repeat_count']} "
        f"(каждые {s['interval_minutes']} мин)"
    )
