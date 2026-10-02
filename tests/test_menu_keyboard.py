from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from telegram.ext import ApplicationBuilder

from bot import (
    MAIN_KEYBOARD,
    MORNING_GREETING_NAMES,
    evening_reminder_text,
    morning_reminder_text,
    month_navigation_keyboard,
    parse_moscow_reminder_time,
    restore_pending_reminders,
    schedule_pending_reminder,
    schedule_daily_jobs,
    shift_month,
)


def test_main_keyboard_has_readable_labels_for_all_requested_actions():
    labels = [[button.text for button in row] for row in MAIN_KEYBOARD.keyboard]

    assert labels == [
        ["Первый день", "Последний день"],
        ["Узнать день", "Календарь"],
        ["Дополнительное напоминание"],
    ]


def test_calendar_navigation_can_move_between_adjacent_months():
    assert shift_month(date(2026, 1, 1), -1) == date(2025, 12, 1)
    assert shift_month(date(2026, 12, 1), 1) == date(2027, 1, 1)

    keyboard = month_navigation_keyboard(
        date(2026, 9, 1),
        [{"first_day": "2026-08-01", "last_day": "2026-08-03"}],
        today=date(2026, 10, 1),
    )

    assert [
        [(button.text, button.callback_data) for button in row]
        for row in keyboard.inline_keyboard
    ] == [[("‹", "calendar:2026-08"), ("›", "calendar:2026-10")]]


def test_pill_reminders_use_moscow_time_and_do_not_send_late():
    application = ApplicationBuilder().token("123456:placeholder").build()
    schedule_daily_jobs(application.job_queue)

    jobs = application.job_queue.jobs()
    assert len(jobs) == 3
    pill_jobs = [job.job for job in jobs if job.name.startswith("send_pill_reminder")]
    assert len(pill_jobs) == 2
    assert {job.trigger.fields[5].expressions[0].__str__() for job in pill_jobs} == {"7", "19"}
    assert all(job.trigger.timezone == ZoneInfo("Europe/Moscow") for job in pill_jobs)
    assert all(job.misfire_grace_time == 60 for job in pill_jobs)


def test_morning_and_evening_reminder_text():
    morning_text = morning_reminder_text()
    assert morning_text.startswith("Доброе утро, ")
    assert morning_text.endswith(". Не забудь принять дюфастон.")
    assert any(f"Доброе утро, {name}." in morning_text for name in MORNING_GREETING_NAMES)
    assert evening_reminder_text() == "Не забудь принять Дюфастон."


def test_additional_reminder_time_must_be_future_today_in_moscow():
    now = datetime(2026, 10, 1, 18, 0, tzinfo=ZoneInfo("Europe/Moscow"))

    assert parse_moscow_reminder_time("19:30", now).isoformat() == "2026-10-01T19:30:00+03:00"
    for value in ("18:00", "17:59", "24:00", "7:30"):
        try:
            parse_moscow_reminder_time(value, now)
        except ValueError:
            continue
        raise AssertionError(f"Expected invalid/past time {value!r} to be rejected")


def test_pending_reminder_jobs_are_named_replaceable_and_moscow_aware():
    application = ApplicationBuilder().token("123456:placeholder").build()
    reminder = {
        "id": "reminder-id",
        "text": "Дюфастон",
        "due_at": (datetime.now(ZoneInfo("Europe/Moscow")) + timedelta(hours=1)).isoformat(),
        "active": True,
    }

    schedule_pending_reminder(application.job_queue, "user-id", reminder)
    schedule_pending_reminder(application.job_queue, "user-id", reminder)

    jobs = application.job_queue.get_jobs_by_name("pill-reminder:user-id:reminder-id")
    assert len(jobs) == 1
    assert jobs[0].data == {"user_id": "user-id", "reminder_id": "reminder-id"}


def test_only_scheduled_reminders_are_restored_after_restart(monkeypatch):
    application = ApplicationBuilder().token("123456:placeholder").build()
    due_at = (datetime.now(ZoneInfo("Europe/Moscow")) + timedelta(minutes=30)).isoformat()
    monkeypatch.setattr(
        "bot.load_users",
        lambda: {
            "user-id": {
                "reminders": [
                    {"id": "sent", "due_at": due_at, "active": True, "scheduled": False},
                    {"id": "pending", "due_at": due_at, "active": True, "scheduled": True},
                ]
            }
        },
    )

    restore_pending_reminders(application.job_queue)

    assert len(application.job_queue.jobs()) == 1
    assert application.job_queue.jobs()[0].name == "pill-reminder:user-id:pending"
