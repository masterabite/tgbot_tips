from datetime import date

from cycle_logic import cycle_day, should_order_reminder, should_pill_reminder


def test_cycle_day_counts_from_first_day():
    assert cycle_day(date(2026, 10, 1), date(2026, 10, 1)) == 1
    assert cycle_day(date(2026, 10, 1), date(2026, 10, 10)) == 10
    assert cycle_day(date(2026, 10, 1), date(2026, 10, 15)) == 15


def test_order_reminder_on_day_10():
    assert should_order_reminder(date(2026, 10, 1), date(2026, 10, 10)) is True
    assert should_order_reminder(date(2026, 10, 1), date(2026, 10, 9)) is False


def test_pill_reminder_in_window_from_15_to_25():
    assert should_pill_reminder(date(2026, 10, 1), date(2026, 10, 15)) is True
    assert should_pill_reminder(date(2026, 10, 1), date(2026, 10, 20)) is True
    assert should_pill_reminder(date(2026, 10, 1), date(2026, 10, 25)) is True
    assert should_pill_reminder(date(2026, 10, 1), date(2026, 10, 14)) is False
    assert should_pill_reminder(date(2026, 10, 1), date(2026, 10, 26)) is False
