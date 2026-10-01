from __future__ import annotations

from datetime import date


def cycle_day(period_start: date, current_day: date | None = None) -> int:
    if current_day is None:
        current_day = date.today()

    if current_day < period_start:
        raise ValueError("Дата проверки не может быть раньше даты начала цикла.")

    return (current_day - period_start).days + 1


def should_order_reminder(period_start: date, current_day: date | None = None) -> bool:
    return cycle_day(period_start, current_day) == 10


def should_pill_reminder(period_start: date, current_day: date | None = None) -> bool:
    day_number = cycle_day(period_start, current_day)
    return 15 <= day_number <= 25
