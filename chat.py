"""Раздел «Чат»: общение с языковой моделью DeepSeek.

Особенности:
- У каждого пользователя свой диалог (история хранится отдельно по chat_id).
- API DeepSeek не хранит контекст — историю отправляем сами при каждом запросе.
- Режим чата включается кнопкой; пока он активен, сообщения уходят в модель,
  а не превращаются в напоминания. Выход — кнопкой «🚪 Выйти из чата».
- Запросы идут обычным HTTPS (через системный/VPN-трафик).
"""
import logging
import re

import aiohttp
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup

from config import Config

log = logging.getLogger(__name__)
router = Router()

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
SYSTEM_PROMPT = (
    "Ты — дружелюбный помощник. Отвечай кратко и по делу на русском языке. "
    "Пиши обычным текстом без Markdown-разметки: не используй звёздочки (*), "
    "решётки (#), обратные кавычки для выделения. Списки оформляй простыми "
    "строками с тире."
)

MAX_HISTORY = 20          # сколько последних сообщений (user+assistant) держим
REQUEST_TIMEOUT = 120     # секунд на ответ модели

BTN_CHAT = "💬 Чат"
BTN_CHAT_EXIT = "🚪 Выйти из чата"
BTN_CHAT_CLEAR = "🧹 Очистить диалог"

# Состояние в памяти: кто сейчас в режиме чата и история диалогов.
_chat_mode: set[int] = set()
_history: dict[int, list[dict]] = {}


def _provider(config: Config) -> tuple[str, str, str] | None:
    """Возвращает (url, api_key, model) активного провайдера или None.

    Приоритет у OpenRouter (бесплатные модели). Если его ключа нет —
    используется DeepSeek. Если нет ни одного — чат отключён.
    """
    if config.openrouter_api_key:
        return OPENROUTER_URL, config.openrouter_api_key, config.openrouter_model
    if config.deepseek_api_key:
        return DEEPSEEK_URL, config.deepseek_api_key, config.deepseek_model
    return None


def chat_enabled(config: Config) -> bool:
    return _provider(config) is not None


def is_in_chat(chat_id: int) -> bool:
    return chat_id in _chat_mode


def _chat_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CHAT_CLEAR), KeyboardButton(text=BTN_CHAT_EXIT)]],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Напишите сообщение модели…",
    )


def _build_messages(model: str, history: list[dict]) -> list[dict]:
    """Собирает messages с учётом особенностей модели.

    Gemma не поддерживает отдельную роль `system`, поэтому для неё системную
    инструкцию подклеиваем к первому сообщению пользователя. Для остальных
    моделей используем обычное system-сообщение.
    """
    if "gemma" in model.lower():
        msgs = [dict(m) for m in history]  # копия, исходную историю не трогаем
        for m in msgs:
            if m["role"] == "user":
                m["content"] = f"{SYSTEM_PROMPT}\n\n{m['content']}"
                break
        return msgs
    return [{"role": "system", "content": SYSTEM_PROMPT}, *history]


async def _ask_model(config: Config, history: list[dict]) -> str:
    prov = _provider(config)
    if prov is None:
        raise RuntimeError("Не задан ключ ни для одного провайдера.")
    url, api_key, model = prov
    payload = {
        "model": model,
        "messages": _build_messages(model, history),
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            data = await resp.json()
            if resp.status != 200:
                msg = data.get("error", {}).get("message", f"HTTP {resp.status}")
                raise RuntimeError(msg)
            return data["choices"][0]["message"]["content"].strip()


def _clean_markdown(text: str) -> str:
    """Убирает Markdown-разметку, которую модель иногда добавляет, чтобы в
    чате не торчали звёздочки и решётки. Текст отправляется как простой."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.S)   # **жирный**
    text = re.sub(r"__(.+?)__", r"\1", text, flags=re.S)        # __жирный__
    text = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"\1", text, flags=re.S)  # *курсив*
    text = re.sub(r"`([^`]+)`", r"\1", text)                    # `код`
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)           # ## заголовки
    text = re.sub(r"(?m)^\s*[-*]\s+", "— ", text)               # маркеры списка -> тире
    return text.strip()


@router.callback_query(F.data == "menu:chat")
async def menu_enter_chat(cb: CallbackQuery, config: Config) -> None:
    if not chat_enabled(config):
        await cb.message.answer("⚠️ Чат недоступен: не задан ключ модели (OPENROUTER_API_KEY).")
        await cb.answer()
        return
    _chat_mode.add(cb.message.chat.id)
    _history.setdefault(cb.message.chat.id, [])
    await cb.message.answer(
        "💬 <b>Режим чата включён.</b>\n"
        "Пишите сообщения — отвечает модель. История диалога сохраняется.\n"
        "Чтобы вернуться к напоминаниям, нажмите «🚪 Выйти из чата».",
        reply_markup=_chat_keyboard(),
    )
    await cb.answer()


@router.message(Command("chat"))
@router.message(F.text == BTN_CHAT)
async def enter_chat(message: Message, config: Config) -> None:
    if not chat_enabled(config):
        await message.answer("⚠️ Чат недоступен: не задан ключ модели (OPENROUTER_API_KEY).")
        return
    _chat_mode.add(message.chat.id)
    _history.setdefault(message.chat.id, [])
    await message.answer(
        "💬 <b>Режим чата включён.</b>\n"
        "Пишите сообщения — отвечает модель DeepSeek. История диалога сохраняется.\n"
        "Чтобы вернуться к напоминаниям, нажмите «🚪 Выйти из чата».",
        reply_markup=_chat_keyboard(),
    )


@router.message(F.text == BTN_CHAT_CLEAR)
async def clear_chat(message: Message) -> None:
    if not is_in_chat(message.chat.id):
        return
    _history[message.chat.id] = []
    await message.answer("🧹 Диалог очищен. Можно начать заново.")


@router.message(F.text == BTN_CHAT_EXIT)
async def exit_chat(message: Message) -> None:
    _chat_mode.discard(message.chat.id)
    # Локальный импорт, чтобы не было циклического импорта на уровне модуля.
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
    history = _history.setdefault(chat_id, [])
    history.append({"role": "user", "content": message.text})

    await message.bot.send_chat_action(chat_id, "typing")
    try:
        answer = await _ask_model(config, history)
    except Exception as e:
        log.exception("Ошибка запроса к DeepSeek")
        history.pop()  # откатываем неотвеченное сообщение
        await message.answer(f"⚠️ Не удалось получить ответ: {e}")
        return

    history.append({"role": "assistant", "content": answer})
    # Ограничиваем длину истории, чтобы не разрастался запрос (и счёт за токены).
    if len(history) > MAX_HISTORY:
        del history[: len(history) - MAX_HISTORY]

    # parse_mode=None — отправляем как простой текст, без HTML/Markdown,
    # предварительно убрав markdown-символы из ответа модели.
    await message.answer(_clean_markdown(answer), parse_mode=None)
