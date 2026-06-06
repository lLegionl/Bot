"""Раздел «Чат»: общение с языковыми моделями через OpenRouter.

- Несколько моделей на выбор (CHAT_PROFILES). При входе в чат пользователь
  выбирает модель; выбор запоминается отдельно для каждого пользователя.
- У каждого пользователя свой диалог (история по chat_id).
- API не хранит контекст — историю отправляем сами при каждом запросе.
- Режим чата: пока активен, сообщения уходят в модель, а не в напоминания.
"""
import logging
import re

import aiohttp
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from config import Config

log = logging.getLogger(__name__)
router = Router()

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
SYSTEM_PROMPT = (
    "Ты — дружелюбный помощник. Отвечай кратко и по делу на русском языке. "
    "Пиши обычным текстом без Markdown-разметки: не используй звёздочки (*), "
    "решётки (#), обратные кавычки для выделения. Списки оформляй простыми "
    "строками с тире."
)

# Профили моделей: ключ -> (подпись кнопки, id модели на OpenRouter).
# Чтобы добавить/сменить модель — отредактируйте этот словарь.
CHAT_PROFILES: dict[str, tuple[str, str]] = {
    "gemma": ("💬 Gemma 4 31B", "google/gemma-4-31b-it:free"),
    "qwen": ("🐧 Qwen3 Next 80B", "qwen/qwen3-next-80b-a3b-instruct:free"),
    "gptoss": ("🤖 GPT-OSS 120B", "openai/gpt-oss-120b:free"),
}

MAX_HISTORY = 20          # сколько последних сообщений держим
REQUEST_TIMEOUT = 120     # секунд на ответ модели

BTN_CHAT = "💬 Чат"
BTN_CHAT_EXIT = "🚪 Выйти из чата"
BTN_CHAT_CLEAR = "🧹 Очистить диалог"

# Состояние в памяти.
_chat_mode: set[int] = set()           # кто сейчас в режиме чата
_history: dict[int, list[dict]] = {}   # история диалога по chat_id
_chat_model: dict[int, str] = {}       # выбранная модель (id) по chat_id


def chat_enabled(config: Config) -> bool:
    return bool(config.openrouter_api_key)


def is_in_chat(chat_id: int) -> bool:
    return chat_id in _chat_mode


def _chat_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CHAT_CLEAR), KeyboardButton(text=BTN_CHAT_EXIT)]],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Напишите сообщение модели…",
    )


def _select_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=name, callback_data=f"chat:start:{key}")]
        for key, (name, _) in CHAT_PROFILES.items()
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:actions")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


_SELECT_TEXT = "🤖 <b>Чат</b>\n\nВыберите модель для общения:"


def _build_messages(model: str, history: list[dict]) -> list[dict]:
    """Gemma и Nemotron (сделан на базе Gemma-3-4B) не поддерживают отдельную
    system-роль — для них подклеиваем инструкцию к первому сообщению."""
    if any(x in model.lower() for x in ("gemma", "nemotron")):
        msgs = [dict(m) for m in history]
        for m in msgs:
            if m["role"] == "user":
                m["content"] = f"{SYSTEM_PROMPT}\n\n{m['content']}"
                break
        return msgs
    return [{"role": "system", "content": SYSTEM_PROMPT}, *history]


async def _ask_model(config: Config, model: str, history: list[dict]) -> str:
    payload = {"model": model, "messages": _build_messages(model, history), "stream": False}
    headers = {
        "Authorization": f"Bearer {config.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(OPENROUTER_URL, json=payload, headers=headers) as resp:
            data = await resp.json()
            if resp.status != 200:
                msg = data.get("error", {}).get("message", f"HTTP {resp.status}")
                raise RuntimeError(msg)
            return data["choices"][0]["message"]["content"].strip()


def _clean_markdown(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.S)
    text = re.sub(r"__(.+?)__", r"\1", text, flags=re.S)
    text = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"\1", text, flags=re.S)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*[-*]\s+", "— ", text)
    return text.strip()


async def _show_select(message: Message, config: Config, edit: bool) -> None:
    if not chat_enabled(config):
        await message.answer("⚠️ Чат недоступен: не задан OPENROUTER_API_KEY.")
        return
    if edit:
        await message.edit_text(_SELECT_TEXT, reply_markup=_select_kb())
    else:
        await message.answer(_SELECT_TEXT, reply_markup=_select_kb())


@router.callback_query(F.data == "menu:chat")
async def menu_chat(cb: CallbackQuery, config: Config) -> None:
    await _show_select(cb.message, config, edit=True)
    await cb.answer()


@router.message(Command("chat"))
@router.message(F.text == BTN_CHAT)
async def cmd_chat(message: Message, config: Config) -> None:
    await _show_select(message, config, edit=False)


@router.callback_query(F.data.startswith("chat:start:"))
async def start_chat(cb: CallbackQuery, config: Config) -> None:
    key = cb.data.split(":", 2)[2]
    profile = CHAT_PROFILES.get(key)
    if profile is None or not chat_enabled(config):
        await cb.answer("Недоступно", show_alert=True)
        return
    name, model = profile
    chat_id = cb.message.chat.id
    _chat_mode.add(chat_id)
    _chat_model[chat_id] = model
    _history[chat_id] = []  # новый диалог при выборе модели
    await cb.message.answer(
        f"💬 Чат с моделью <b>{name}</b> включён.\n"
        f"Пишите сообщения. Выход — «🚪 Выйти из чата».",
        reply_markup=_chat_keyboard(),
    )
    await cb.answer()


@router.message(F.text == BTN_CHAT_CLEAR)
async def clear_chat(message: Message) -> None:
    if not is_in_chat(message.chat.id):
        return
    _history[message.chat.id] = []
    await message.answer("🧹 Диалог очищен. Можно начать заново.")


@router.message(F.text == BTN_CHAT_EXIT)
async def exit_chat(message: Message) -> None:
    _chat_mode.discard(message.chat.id)
    from handlers import _main_keyboard
    await message.answer(
        "Вышли из чата. Снова можно ставить напоминания.",
        reply_markup=_main_keyboard(),
    )


def _in_chat_filter(message: Message) -> bool:
    return is_in_chat(message.chat.id)


@router.message(F.text, _in_chat_filter)
async def chat_message(message: Message, config: Config) -> None:
    chat_id = message.chat.id
    model = _chat_model.get(chat_id) or next(iter(CHAT_PROFILES.values()))[1]
    history = _history.setdefault(chat_id, [])
    history.append({"role": "user", "content": message.text})

    await message.bot.send_chat_action(chat_id, "typing")
    try:
        answer = await _ask_model(config, model, history)
    except Exception as e:
        log.exception("Ошибка запроса к модели")
        history.pop()
        await message.answer(f"⚠️ Не удалось получить ответ: {e}")
        return

    history.append({"role": "assistant", "content": answer})
    if len(history) > MAX_HISTORY:
        del history[: len(history) - MAX_HISTORY]

    await message.answer(_clean_markdown(answer), parse_mode=None)
