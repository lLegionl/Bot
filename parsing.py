"""Разбор естественного языка: вытаскиваем дату/время и текст напоминания.

Использует dateparser, который понимает русские выражения вроде
«завтра в 12», «через 2 часа», «15 января в 9:30», «в пятницу в 18:00».
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from dateparser.search import search_dates

# Слова-триггеры, которые нужно убрать из текста напоминания.
TRIGGER_WORDS = [
    "напомни мне", "напомни", "напомнить", "напоминание",
    "напомните", "не забыть", "что",
]

# Месяцы — чтобы не спутать «в 15 января» (дата) с временем «15:00».
_MONTHS = (
    "январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр|год|числ"
)

# «в 12», «в 9:30», «в 18 часов» — необязательная часть суток.
_RE_AT = re.compile(
    rf"\bв\s+(\d{{1,2}})(?:[:.](\d{{2}}))?(?:\s*час[а-я]*)?"
    rf"(?:\s+(утра|ночи|дня|вечера))?\b(?!\s*(?:{_MONTHS}))",
    re.IGNORECASE,
)
# «8 вечера», «9 утра» без предлога «в».
_RE_PERIOD = re.compile(
    r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(?:час[а-я]*\s*)?(утра|ночи|дня|вечера)\b",
    re.IGNORECASE,
)


def _to_hhmm(hour: int, minute: int, period: str | None) -> str:
    period = (period or "").lower()
    if period in ("дня", "вечера") and hour < 12:
        hour += 12
    if period in ("утра", "ночи") and hour == 12:
        hour = 0
    hour %= 24
    return f"{hour:02d}:{minute:02d}"


def _normalize_time_phrases(text: str) -> str:
    """Переводит «в 12», «в 8 вечера» и т.п. в надёжный формат ЧЧ:ММ."""
    def repl(m: re.Match) -> str:
        hour = int(m.group(1))
        if hour > 23:
            return m.group(0)
        minute = int(m.group(2)) if m.group(2) else 0
        return _to_hhmm(hour, minute, m.group(3))

    text = _RE_AT.sub(repl, text)
    text = _RE_PERIOD.sub(repl, text)
    return text


def parse_reminder(
    text: str, tz: ZoneInfo, now: datetime | None = None
) -> tuple[str | None, datetime | None, str | None]:
    """Возвращает (текст_напоминания, дата_время, ошибка).

    Если ошибка не None — значит распарсить не удалось или время в прошлом.
    """
    now = now or datetime.now(tz)
    settings = {
        "PREFER_DATES_FROM": "future",
        "TIMEZONE": str(tz),
        "TO_TIMEZONE": str(tz),
        "RETURN_AS_TIMEZONE_AWARE": True,
        "RELATIVE_BASE": now.replace(tzinfo=None),
        "DATE_ORDER": "DMY",
    }

    normalized = _normalize_time_phrases(text)
    found = search_dates(normalized, languages=["ru"], settings=settings)
    if not found:
        return None, None, "Не удалось распознать дату и время."

    # Берём самое «длинное» совпадение — обычно оно самое информативное.
    matched, dt = max(found, key=lambda x: len(x[0]))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)

    # Вырезаем из текста распознанную дату и слова-триггеры.
    rest = normalized.replace(matched, " ")
    for word in TRIGGER_WORDS:
        rest = re.sub(rf"\b{re.escape(word)}\b", " ", rest, flags=re.IGNORECASE)
    rest = re.sub(r"\s+", " ", rest).strip(" ,.;:-—«»\"'")

    if not rest:
        rest = "напоминание"

    if dt <= now:
        return rest, dt, "Указанное время уже прошло. Уточните дату/время."

    return rest, dt, None
