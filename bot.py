import json
import logging
import os
import random
import re
import uuid
from datetime import date, datetime, time, timedelta
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest  # ← добавьте эту строку

from cycle_calendar import (
    ensure_period_history,
    record_first_day,
    record_last_day,
    render_month_image,
)
from cycle_logic import cycle_day, should_order_reminder, should_pill_reminder

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DATA_DIR = Path(__file__).resolve().parent / "data"
USERS_FILE = DATA_DIR / "users.json"
DATE_INPUT_FORMAT = "%d.%m.%Y"
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
MISFIRE_GRACE_SECONDS = 60
REMINDER_JOB_PREFIX = "pill-reminder:"
MORNING_GREETING_NAMES = (
    "Женечка",
    "Солнце",
    "Дорогая",
    "Кошка",
    "Зайчик",
    "Малышка",
    "Мышка",
)
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("Первый день"), KeyboardButton("Последний день")],
        [KeyboardButton("Узнать день"), KeyboardButton("Календарь")],
        [KeyboardButton("Дополнительное напоминание")],
    ],
    resize_keyboard=True,
)


def parse_input_date(value: str) -> date:
    parsed = datetime.strptime(value, DATE_INPUT_FORMAT).date()
    if parsed.strftime(DATE_INPUT_FORMAT) != value:
        raise ValueError("Дата должна быть в формате DD.MM.ГГГГ")
    return parsed


def ensure_store() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    if not USERS_FILE.exists():
        USERS_FILE.write_text("{}", encoding="utf-8")


def load_users() -> dict:
    ensure_store()
    try:
        with USERS_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_users(users: dict) -> None:
    ensure_store()
    with USERS_FILE.open("w", encoding="utf-8") as file:
        json.dump(users, file, ensure_ascii=False, indent=2)


def user_key(update: Update) -> str:
    return str(update.effective_user.id)


def get_user_profile(update: Update) -> dict:
    users = load_users()
    return users.get(user_key(update), {})


def moscow_today() -> date:
    return datetime.now(MOSCOW_TZ).date()


def parse_moscow_reminder_time(value: str, now: datetime) -> datetime:
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", value)
    if not match:
        raise ValueError("Введи время в формате ЧЧ:ММ.")
    hour, minute = map(int, match.groups())
    due_at = datetime.combine(now.date(), time(hour, minute), tzinfo=MOSCOW_TZ)
    if due_at <= now:
        raise ValueError("Это время сегодня уже прошло.")
    return due_at


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("awaiting_date", None)
    context.user_data.pop("awaiting_extra_reminder_time", None)
    await update.message.reply_text(
        "Привет! Я бот-помощник по циклу.\n\n"
        "Сначала сохрани даты:\n"
        "«Первый день» — отметить начало месячных\n"
        "«Последний день» — отметить окончание месячных\n"
        "«Узнать день» — показать текущий день цикла\n"
        "«Календарь» — открыть историю месячных\n\n"
        "«Дополнительное напоминание» — выбрать ещё одно время для напоминания о Дюфастоне\n\n"
        "/help — помощь\n\n"
        "Напоминания:\n"
        "- в 10-й день цикла: «Начинается подготовка к священным дням»\n"
        "- с 15 по 25 день цикла: утром в 7:00 и вечером в 19:00 — «Дюфастон»",
        reply_markup=MAIN_KEYBOARD,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("awaiting_date", None)
    context.user_data.pop("awaiting_extra_reminder_time", None)
    await update.message.reply_text(
        "Как пользоваться:\n"
        "1. Нажми «Первый день» и укажи дату в формате ДД.ММ.ГГГГ, например 01.10.2026\n"
        "2. Нажми «Последний день» и укажи дату в том же формате\n"
        "3. Нажми «Узнать день», чтобы проверить текущий день цикла\n"
        "4. Нажми «Календарь», чтобы посмотреть историю месячных\n"
        "5. «Дополнительное напоминание» позволяет выбрать время ещё одного напоминания о Дюфастоне\n"
        "6. Бот сам напомнит о важных датах твоего цикла.",
        reply_markup=MAIN_KEYBOARD,
    )


async def save_date(update: Update, context: ContextTypes.DEFAULT_TYPE, field: str, value: str) -> bool:
    try:
        saved_date = parse_input_date(value)
    except ValueError:
        await update.message.reply_text("Дата должна быть в формате ДД.ММ.ГГГГ, например 01.10.2026")
        return False

    users = load_users()
    profile = users.setdefault(user_key(update), {})
    if field == "first_day":
        record_first_day(profile, saved_date)
    else:
        record_last_day(profile, saved_date)
    save_users(users)
    context.user_data.pop("awaiting_date", None)
    context.user_data.pop("awaiting_extra_reminder_time", None)

    label = "первого" if field == "first_day" else "последнего"
    await update.message.reply_text(
        f"Сохранена дата {label} дня месячных: {saved_date.strftime(DATE_INPUT_FORMAT)}",
        reply_markup=MAIN_KEYBOARD,
    )
    return True


async def save_first_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        context.user_data["awaiting_date"] = "first_day"
        await update.message.reply_text(
            "Введи дату первого дня месячных в формате ДД.ММ.ГГГГ, например 01.10.2026",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    await save_date(update, context, "first_day", context.args[0])


async def save_last_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        context.user_data["awaiting_date"] = "last_day"
        await update.message.reply_text(
            "Введи дату последнего дня месячных в формате ДД.ММ.ГГГГ, например 05.10.2026",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    await save_date(update, context, "last_day", context.args[0])


async def receive_date_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    field = context.user_data.get("awaiting_date")
    if field in {"first_day", "last_day"}:
        await save_date(update, context, field, update.message.text.strip())
    elif context.user_data.get("awaiting_extra_reminder_time"):
        await save_extra_reminder_time(update, context, update.message.text.strip())


async def handle_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    button = update.message.text
    context.user_data.pop("awaiting_extra_reminder_time", None)
    context.user_data.pop("awaiting_date", None)
    if button == "Первый день":
        await save_first_day(update, context)
    elif button == "Последний день":
        await save_last_day(update, context)
    elif button == "Узнать день":
        await status_command(update, context)
    elif button == "Календарь":
        await show_calendar(update, context)
    elif button == "Дополнительное напоминание":
        context.user_data.pop("awaiting_date", None)
        context.user_data["awaiting_extra_reminder_time"] = True
        await update.message.reply_text(
            "На какое время поставить дополнительное напоминание сегодня? "
            "Введи время по Москве в формате ЧЧ:ММ, например 21:30.",
            reply_markup=MAIN_KEYBOARD,
        )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("awaiting_date", None)
    context.user_data.pop("awaiting_extra_reminder_time", None)
    profile = get_user_profile(update)
    first_day = profile.get("first_day")
    last_day = profile.get("last_day")

    if not first_day:
        await update.message.reply_text(
            "Сначала нажми «Первый день» и укажи дату начала месячных.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    first_date = date.fromisoformat(first_day)
    today = moscow_today()
    current_day = cycle_day(first_date, today)

    text = [
        f"Сегодня: {today.isoformat()}",
        f"Начало цикла: {first_date.isoformat()}",
        f"Текущий день цикла: {current_day}",
    ]

    if last_day:
        text.append(f"Последний день месячных: {last_day}")

    if should_order_reminder(first_date, today):
        text.append("✅ Сегодня 10-й день цикла. Начинается подготовка к священным дням.")
    elif 15 <= current_day <= 25:
        text.append("✅ Сейчас дни приёма Дюфастона: с 15 по 25 день цикла.")
    else:
        text.append("ℹ️ Сегодня напоминаний по приёму таблеток нет.")

    await update.message.reply_text("\n".join(text), reply_markup=MAIN_KEYBOARD)


def month_navigation_keyboard(
    month: date,
    periods: list[dict],
    today: date | None = None,
) -> InlineKeyboardMarkup | None:
    earliest_month = None
    for period in periods:
        try:
            first_day = date.fromisoformat(period["first_day"])
        except (KeyError, TypeError, ValueError):
            continue
        candidate = (first_day.year, first_day.month)
        if earliest_month is None or candidate < earliest_month:
            earliest_month = candidate

    today = today or moscow_today()
    current_month = (today.year, today.month)
    selected_month = (month.year, month.month)
    buttons = []
    if earliest_month and selected_month > earliest_month:
        previous = shift_month(month, -1)
        buttons.append(InlineKeyboardButton("‹", callback_data=f"calendar:{previous:%Y-%m}"))
    if selected_month < current_month:
        following = shift_month(month, 1)
        buttons.append(InlineKeyboardButton("›", callback_data=f"calendar:{following:%Y-%m}"))
    return InlineKeyboardMarkup([buttons]) if buttons else None


def shift_month(month: date, offset: int) -> date:
    month_index = month.year * 12 + month.month - 1 + offset
    return date(month_index // 12, month_index % 12 + 1, 1)


async def show_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("awaiting_date", None)
    context.user_data.pop("awaiting_extra_reminder_time", None)
    users = load_users()
    profile = users.get(user_key(update), {})
    if ensure_period_history(profile):
        users[user_key(update)] = profile
        save_users(users)

    month = moscow_today().replace(day=1)
    image = BytesIO(render_month_image(month, profile.get("periods", [])))
    image.name = "calendar.png"
    message = await update.message.reply_photo(
        photo=image,
        reply_markup=month_navigation_keyboard(month, profile.get("periods", [])),
    )
    cache_calendar_file_id(context, user_key(update), month, profile, message)


async def navigate_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    try:
        month = datetime.strptime(query.data.partition(":")[2], "%Y-%m").date().replace(day=1)
    except ValueError:
        await query.answer("Не удалось открыть этот месяц.", show_alert=True)
        return
    await query.answer()

    profile = get_user_profile(update)
    if ensure_period_history(profile):
        users = load_users()
        users[user_key(update)] = profile
        save_users(users)
    cache_key = calendar_cache_key(user_key(update), month, profile)
    file_id = context.bot_data.get("calendar_file_ids", {}).get(cache_key)
    image = file_id or BytesIO(render_month_image(month, profile.get("periods", [])))
    if isinstance(image, BytesIO):
        image.name = "calendar.png"
    message = await query.edit_message_media(
        media=InputMediaPhoto(media=image),
        reply_markup=month_navigation_keyboard(month, profile.get("periods", [])),
    )
    cache_calendar_file_id(context, user_key(update), month, profile, message)


def calendar_cache_key(user_id: str, month: date, profile: dict) -> str:
    periods = json.dumps(profile.get("periods", []), ensure_ascii=False, sort_keys=True)
    return f"{user_id}:{month:%Y-%m}:{periods}"


def cache_calendar_file_id(context: ContextTypes.DEFAULT_TYPE, user_id: str, month: date, profile: dict, message) -> None:
    if not message.photo:
        return
    cache = context.bot_data.setdefault("calendar_file_ids", {})
    cache[calendar_cache_key(user_id, month, profile)] = message.photo[-1].file_id


def schedule_daily_jobs(job_queue) -> None:
    job_kwargs = {"misfire_grace_time": MISFIRE_GRACE_SECONDS}
    job_queue.run_daily(
        send_order_reminder,
        time=time(9, 0, tzinfo=MOSCOW_TZ),
        job_kwargs=job_kwargs,
    )
    job_queue.run_daily(
        send_pill_reminder_morning,
        time=time(7, 0, tzinfo=MOSCOW_TZ),
        job_kwargs=job_kwargs,
    )
    job_queue.run_daily(
        send_pill_reminder_evening,
        time=time(19, 0, tzinfo=MOSCOW_TZ),
        job_kwargs=job_kwargs,
    )


def restore_pending_reminders(job_queue) -> None:
    for user_id, profile in load_users().items():
        for reminder in profile.get("reminders", []):
            if reminder.get("active", True) and reminder.get("scheduled", False):
                schedule_pending_reminder(job_queue, user_id, reminder)


def mark_reminder_delivered(user_id: str, reminder_id: str) -> None:
    users = load_users()
    reminder = get_reminder(users.get(user_id, {}), reminder_id)
    if reminder:
        reminder["scheduled"] = False
        save_users(users)


async def send_order_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    users = load_users()
    today = moscow_today()

    for user_id, profile in users.items():
        first_day = profile.get("first_day")
        if not first_day:
            continue

        try:
            first_date = date.fromisoformat(first_day)
        except ValueError:
            continue

        if should_order_reminder(first_date, today):
            await context.bot.send_message(
                chat_id=int(user_id),
                text="Начинается подготовка к священным дням",
            )


async def send_pill_reminder_morning(context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_pill_reminder(context, morning=True)


async def send_pill_reminder_evening(context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_pill_reminder(context, morning=False)


def reminder_keyboard(reminder_id: str, *, show_postpone_options: bool = False) -> InlineKeyboardMarkup:
    if show_postpone_options:
        return InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("На 30 минут", callback_data=f"pill:snooze:{reminder_id}:30"),
                InlineKeyboardButton("На час", callback_data=f"pill:snooze:{reminder_id}:60"),
            ]]
        )
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("Готово", callback_data=f"pill:done:{reminder_id}"),
            InlineKeyboardButton("Отложить", callback_data=f"pill:defer:{reminder_id}"),
        ]]
    )


def get_reminder(profile: dict, reminder_id: str) -> dict | None:
    for reminder in profile.get("reminders", []):
        if reminder.get("id") == reminder_id and reminder.get("active", True):
            return reminder
    return None


def schedule_pending_reminder(job_queue, user_id: str, reminder: dict) -> None:
    due_at = datetime.fromisoformat(reminder["due_at"])
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=MOSCOW_TZ)
    job_name = f"{REMINDER_JOB_PREFIX}{user_id}:{reminder['id']}"
    for existing_job in job_queue.get_jobs_by_name(job_name):
        existing_job.schedule_removal()
    job_queue.run_once(
        send_deferred_reminder,
        when=max(due_at, datetime.now(MOSCOW_TZ)),
        name=job_name,
        data={"user_id": user_id, "reminder_id": reminder["id"]},
        job_kwargs={"misfire_grace_time": MISFIRE_GRACE_SECONDS},
    )


def persist_reminder(user_id: str, reminder: dict) -> None:
    users = load_users()
    profile = users.setdefault(user_id, {})
    reminders = profile.setdefault("reminders", [])
    reminders[:] = [item for item in reminders if item.get("id") != reminder["id"]]
    reminders.append(reminder)
    save_users(users)


async def send_deferred_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(context.job.data["user_id"])
    reminder_id = context.job.data["reminder_id"]
    profile = load_users().get(user_id, {})
    reminder = get_reminder(profile, reminder_id)
    if not reminder:
        return

    await context.bot.send_message(
        chat_id=int(user_id),
        text=reminder["text"],
        reply_markup=reminder_keyboard(reminder_id),
    )
    mark_reminder_delivered(user_id, reminder_id)


async def send_pill_reminder(context: ContextTypes.DEFAULT_TYPE, *, morning: bool) -> None:
    users = load_users()
    now = datetime.now(MOSCOW_TZ)
    today = now.date()

    for user_id, profile in users.items():
        first_day = profile.get("first_day")
        if not first_day:
            continue

        try:
            first_date = date.fromisoformat(first_day)
        except ValueError:
            continue

        if not should_pill_reminder(first_date, today):
            continue

        reminder_id = uuid.uuid4().hex
        text = (
            morning_reminder_text()
            if morning
            else evening_reminder_text()
        )
        reminder = {
            "id": reminder_id,
            "text": text,
            "due_at": now.isoformat(),
            "active": True,
            "scheduled": True,
        }
        profile.setdefault("reminders", []).append(reminder)
        save_users(users)
        await context.bot.send_message(
            chat_id=int(user_id),
            text=text,
            reply_markup=reminder_keyboard(reminder_id),
        )
        mark_reminder_delivered(user_id, reminder_id)


def morning_reminder_text() -> str:
    return f"Доброе утро, {random.choice(MORNING_GREETING_NAMES)}. Не забудь принять дюфастон."


def evening_reminder_text() -> str:
    return "Не забудь принять Дюфастон."


async def save_extra_reminder_time(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    value: str,
) -> None:
    now = datetime.now(MOSCOW_TZ)
    try:
        due_at = parse_moscow_reminder_time(value, now)
    except ValueError:
        if re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", value):
            message = "Это время сегодня уже прошло. Введи будущее время по Москве в формате ЧЧ:ММ."
        else:
            message = "Введи время в формате ЧЧ:ММ, например 21:30."
        await update.message.reply_text(
            message,
        )
        return

    user_id = user_key(update)
    reminder = {
        "id": uuid.uuid4().hex,
        "text": "Дюфастон",
        "due_at": due_at.isoformat(),
        "active": True,
        "scheduled": True,
    }
    persist_reminder(user_id, reminder)
    schedule_pending_reminder(context.job_queue, user_id, reminder)
    context.user_data.pop("awaiting_extra_reminder_time", None)
    await update.message.reply_text(
        f"Дополнительное напоминание «Дюфастон» установлено на {due_at:%H:%M} по Москве.",
        reply_markup=MAIN_KEYBOARD,
    )


async def handle_pill_reminder_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    parts = (query.data or "").split(":")
    if len(parts) < 3 or parts[0] != "pill":
        await query.answer("Не удалось обработать напоминание.", show_alert=True)
        return

    action, reminder_id = parts[1], parts[2]
    user_id = str(update.effective_user.id)
    users = load_users()
    profile = users.get(user_id, {})
    reminder = get_reminder(profile, reminder_id)
    if not reminder:
        await query.answer("Это напоминание уже завершено.")
        return

    if action == "done":
        reminder["active"] = False
        profile["reminders"] = [
            item for item in profile.get("reminders", []) if item.get("id") != reminder_id
        ]
        save_users(users)
        job = context.job_queue.get_jobs_by_name(f"{REMINDER_JOB_PREFIX}{user_id}:{reminder_id}")
        for scheduled_job in job:
            scheduled_job.schedule_removal()
        await query.answer("Отмечено: таблетка принята.")
        await query.edit_message_text(f"{reminder['text']}\n\n✅ Готово")
        return

    if action == "defer":
        await query.answer()
        await query.edit_message_reply_markup(
            reply_markup=reminder_keyboard(reminder_id, show_postpone_options=True)
        )
        return

    if action == "snooze" and len(parts) == 4 and parts[3] in {"30", "60"}:
        minutes = int(parts[3])
        reminder["due_at"] = (datetime.now(MOSCOW_TZ) + timedelta(minutes=minutes)).isoformat()
        reminder["text"] = "Дюфастон"
        reminder["scheduled"] = True
        persist_reminder(user_id, reminder)
        schedule_pending_reminder(context.job_queue, user_id, reminder)
        await query.answer(f"Напомню через {minutes} минут.")
        await query.edit_message_text(f"Дюфастон отложен на {minutes} минут.")
        return

    await query.answer("Не удалось обработать напоминание.", show_alert=True)


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Неизвестная команда. Используй /help")


def main() -> None:
    if not TOKEN:
        raise RuntimeError(
            "Токен бота не найден. Создай файл .env на основе .env.example и укажи TELEGRAM_BOT_TOKEN."
        )

    # Прокси v2rayA: socks5h — DNS через прокси
    proxy_url = os.getenv("PROXY_URL", "socks5h://127.0.0.1:20170")

    request = HTTPXRequest(
        proxy=proxy_url,       # ← ИСПРАВЛЕНО: новый параметр
        connect_timeout=30.0,
        read_timeout=30.0,
    )

    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .request(request)
        .get_updates_request(request)   # важно: тот же прокси для polling
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("first_day", save_first_day))
    application.add_handler(CommandHandler("last_day", save_last_day))
    application.add_handler(CommandHandler("period_start", save_first_day))
    application.add_handler(CommandHandler("period_end", save_last_day))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("cycle", status_command))
    application.add_handler(CommandHandler("unknown", unknown_command))
    application.add_handler(
        MessageHandler(
            filters.Regex(
                r"^(Первый день|Последний день|Узнать день|Календарь|Дополнительное напоминание)$"
            ),
            handle_menu_button,
        )
    )
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_date_input))
    application.add_handler(CallbackQueryHandler(navigate_calendar, pattern=r"^calendar:"))
    application.add_handler(CallbackQueryHandler(handle_pill_reminder_action, pattern=r"^pill:"))

    schedule_daily_jobs(application.job_queue)
    restore_pending_reminders(application.job_queue)

    application.run_polling()


if __name__ == "__main__":
    main()
