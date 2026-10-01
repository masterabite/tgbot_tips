import json
import logging
import os
from datetime import date, time
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from cycle_logic import cycle_day, should_order_reminder, should_pill_reminder

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DATA_DIR = Path(__file__).resolve().parent / "data"
USERS_FILE = DATA_DIR / "users.json"


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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Я бот-помощник по циклу.\n\n"
        "Сначала сохрани даты:\n"
        "/first_day YYYY-MM-DD — первый день месячных (когда началась кровь)\n"
        "/last_day YYYY-MM-DD — последний день месячных (когда кровь закончилась)\n"
        "/status — показать текущий день цикла\n"
        "/help — помощь\n\n"
        "Напоминания:\n"
        "- в 10-й день цикла: пора заказать таблетки\n"
        "- с 15 по 25 день цикла: утром в 7:00 и вечером в 19:00 — пора пить таблетку"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Как пользоваться:\n"
        "1. Укажите первую дату месячных: /first_day 2026-10-01\n"
        "2. Укажите последнюю дату месячных: /last_day 2026-10-05\n"
        "3. Проверяйте календарь командой /status\n"
        "4. Бот сам напомнит по вашему циклу."
    )


async def save_first_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Используйте формат: /first_day YYYY-MM-DD")
        return

    try:
        first_day = date.fromisoformat(context.args[0])
    except ValueError:
        await update.message.reply_text("Дата должна быть в формате YYYY-MM-DD")
        return

    users = load_users()
    profile = users.setdefault(user_key(update), {})
    profile["first_day"] = first_day.isoformat()
    save_users(users)

    await update.message.reply_text(f"Сохранена дата первого дня месячных: {first_day.isoformat()}")


async def save_last_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Используйте формат: /last_day YYYY-MM-DD")
        return

    try:
        last_day = date.fromisoformat(context.args[0])
    except ValueError:
        await update.message.reply_text("Дата должна быть в формате YYYY-MM-DD")
        return

    users = load_users()
    profile = users.setdefault(user_key(update), {})
    profile["last_day"] = last_day.isoformat()
    save_users(users)

    await update.message.reply_text(f"Сохранена дата последнего дня месячных: {last_day.isoformat()}")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    profile = get_user_profile(update)
    first_day = profile.get("first_day")
    last_day = profile.get("last_day")

    if not first_day:
        await update.message.reply_text("Сначала отметьте первый день месячных: /first_day YYYY-MM-DD")
        return

    first_date = date.fromisoformat(first_day)
    today = date.today()
    current_day = cycle_day(first_date, today)

    text = [
        f"Сегодня: {today.isoformat()}",
        f"Начало цикла: {first_date.isoformat()}",
        f"Текущий день цикла: {current_day}",
    ]

    if last_day:
        text.append(f"Последний день месячных: {last_day}")

    if should_order_reminder(first_date, today):
        text.append("✅ Сегодня 10-й день цикла — пора заказать таблетки.")
    elif 15 <= current_day <= 25:
        text.append("✅ Сейчас окно приёма таблеток: с 15 по 25 день цикла.")
    else:
        text.append("ℹ️ Сегодня напоминаний по приёму таблеток нет.")

    await update.message.reply_text("\n".join(text))


async def send_order_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    users = load_users()
    today = date.today()

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
                text="Пора заказать таблетки. Сегодня 10-й день цикла.",
            )


async def send_pill_reminder_morning(context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_pill_reminder(context, "morning")


async def send_pill_reminder_evening(context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_pill_reminder(context, "evening")


async def send_pill_reminder(context: ContextTypes.DEFAULT_TYPE, part_of_day: str) -> None:
    users = load_users()
    today = date.today()

    for user_id, profile in users.items():
        first_day = profile.get("first_day")
        if not first_day:
            continue

        try:
            first_date = date.fromisoformat(first_day)
        except ValueError:
            continue

        if should_pill_reminder(first_date, today):
            time_label = "утром" if part_of_day == "morning" else "вечером"
            await context.bot.send_message(
                chat_id=int(user_id),
                text=f"Пора пить таблетку {time_label}. С 15 по 25 день цикла — приём по расписанию.",
            )


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Неизвестная команда. Используйте /help")


def main() -> None:
    if not TOKEN:
        raise RuntimeError(
            "Токен бота не найден. Создайте файл .env на основе .env.example и укажите TELEGRAM_BOT_TOKEN."
        )

    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("first_day", save_first_day))
    application.add_handler(CommandHandler("last_day", save_last_day))
    application.add_handler(CommandHandler("period_start", save_first_day))
    application.add_handler(CommandHandler("period_end", save_last_day))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("cycle", status_command))
    application.add_handler(CommandHandler("unknown", unknown_command))

    application.job_queue.run_daily(send_order_reminder, time=time(9, 0))
    application.job_queue.run_daily(send_pill_reminder_morning, time=time(7, 0))
    application.job_queue.run_daily(send_pill_reminder_evening, time=time(19, 0))

    application.run_polling()


if __name__ == "__main__":
    main()
