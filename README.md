# Телеграм-бот «Напоминалка»

Бот принимает напоминания на естественном языке («напомни купить продукты завтра в 12»),
присылает уведомление в нужное время и **повторяет его**, пока вы не нажмёте «Стоп».
Количество повторов и интервал между ними настраиваются индивидуально для каждого пользователя.

## Возможности

- Создание напоминания обычным текстом: «позвонить маме через 2 часа», «отчёт 15 января в 9:30».
- Повтор уведомления при отсутствии ответа (по умолчанию 3 раза каждые 5 минут).
- Кнопка «✅ Стоп / Выполнено» — мгновенно прекращает повторы.
- `/list` — список активных напоминаний с возможностью отмены.
- `/settings` — настройка числа повторов и интервала кнопками.
- Напоминания хранятся в SQLite и восстанавливаются после перезапуска бота.

## Структура проекта

| Файл | Назначение |
|------|------------|
| `bot.py` | точка входа, запуск бота |
| `config.py` | чтение настроек из `.env` |
| `database.py` | хранилище (SQLite) |
| `parsing.py` | разбор даты/времени из текста |
| `scheduler.py` | планировщик и логика повторов |
| `handlers.py` | команды и кнопки |

---

## Как развернуть на Ubuntu-сервере

### 1. Получить токен бота
В Telegram напишите [@BotFather](https://t.me/BotFather), команда `/newbot`, задайте имя
и username. BotFather пришлёт токен вида `123456:ABC-DEF...` — он понадобится дальше.

### 2. Установить зависимости системы
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

### 3. Загрузить код и создать окружение
```bash
# поместите файлы проекта, например, в /opt/reminder_bot
sudo mkdir -p /opt/reminder_bot
sudo chown $USER:$USER /opt/reminder_bot
cd /opt/reminder_bot
# ... скопируйте сюда файлы проекта ...

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Настроить `.env`
```bash
cp .env.example .env
nano .env
```
Впишите ваш `BOT_TOKEN` и при необходимости поправьте `TIMEZONE`
(например, `Europe/Moscow`, `Asia/Yekaterinburg`, `Europe/Berlin`).

### 5. Проверить запуск вручную
```bash
source .venv/bin/activate
python bot.py
```
В логах должно появиться «Бот запущен.». Напишите боту в Telegram — он должен ответить.
Остановите проверку: `Ctrl + C`.

### 6. Запустить как сервис (автозапуск + перезапуск при сбоях)
Создайте файл сервиса:
```bash
sudo nano /etc/systemd/system/reminder-bot.service
```
Содержимое (поправьте `User` и пути под себя):
```ini
[Unit]
Description=Telegram Reminder Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/opt/reminder_bot
ExecStart=/opt/reminder_bot/.venv/bin/python /opt/reminder_bot/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
Включите и запустите:
```bash
sudo systemctl daemon-reload
sudo systemctl enable reminder-bot
sudo systemctl start reminder-bot
```

### 7. Управление и логи
```bash
sudo systemctl status reminder-bot      # статус
sudo systemctl restart reminder-bot     # перезапуск
journalctl -u reminder-bot -f           # живой просмотр логов
```

---

## Как пользоваться

Просто напишите боту, например:
- `напомни купить продукты завтра в 12`
- `позвонить маме через 2 часа`
- `тренировка в пятницу в 18:00`

Когда придёт уведомление — нажмите **«✅ Стоп / Выполнено»**. Если не нажать,
бот повторит напоминание через заданный интервал столько раз, сколько указано в `/settings`.

## Примечания

- Время указывается в таймзоне из `TIMEZONE`. Сейчас она общая для всех пользователей;
  при желании можно добавить персональную таймзону в `user_settings`.
- Если бот был выключен в момент срабатывания напоминания, после запуска он напомнит
  с небольшой задержкой (просроченные напоминания не теряются).
- Чтобы сбросить все данные — остановите бота и удалите файл `reminders.db`.
