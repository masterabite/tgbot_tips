from datetime import date
from io import BytesIO

from PIL import Image

from cycle_calendar import (
    ensure_period_history,
    record_first_day,
    record_last_day,
    render_month_image,
)


def test_migrates_existing_dates_and_keeps_the_history():
    profile = {"first_day": "2026-09-28", "last_day": "2026-10-02"}

    assert ensure_period_history(profile) is True
    assert profile["periods"] == [
        {"first_day": "2026-09-28", "last_day": "2026-10-02"}
    ]

    record_first_day(profile, date(2026, 10, 25))
    record_last_day(profile, date(2026, 10, 29))

    assert profile["periods"] == [
        {"first_day": "2026-09-28", "last_day": "2026-10-02"},
        {"first_day": "2026-10-25", "last_day": "2026-10-29"},
    ]


def test_calendar_starts_weeks_on_monday_and_marks_period_days():
    rendered = render_month_image(
        date(2026, 10, 1),
        [{"first_day": "2026-10-01", "last_day": "2026-10-03"}],
    )
    image = Image.open(BytesIO(rendered)).convert("RGB")

    assert image.size == (800, 710)
    assert image.getpixel((398, 195)) == (251, 111, 146)
    assert image.getpixel((710, 195)) != (251, 111, 146)
