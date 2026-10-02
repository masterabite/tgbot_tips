from __future__ import annotations

import calendar
from datetime import date
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


MONTH_NAMES = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
WEEKDAY_HEADERS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
PERIOD_COLOR = "#FB6F92"


def ensure_period_history(profile: dict) -> bool:
    if isinstance(profile.get("periods"), list):
        return False

    profile["periods"] = []
    first_day = profile.get("first_day")
    if first_day:
        profile["periods"].append(
            {
                "first_day": first_day,
                "last_day": profile.get("last_day"),
            }
        )
    return True


def record_first_day(profile: dict, first_day: date) -> None:
    ensure_period_history(profile)
    periods = profile["periods"]
    if periods and periods[-1].get("first_day") == first_day.isoformat():
        latest_period = periods[-1]
    elif periods and not periods[-1].get("last_day"):
        periods[-1]["first_day"] = first_day.isoformat()
        latest_period = periods[-1]
    else:
        periods.append({"first_day": first_day.isoformat(), "last_day": None})
        latest_period = periods[-1]

    profile["first_day"] = first_day.isoformat()
    if latest_period.get("last_day"):
        profile["last_day"] = latest_period["last_day"]
    else:
        profile.pop("last_day", None)


def record_last_day(profile: dict, last_day: date) -> None:
    ensure_period_history(profile)
    periods = profile["periods"]
    if periods and periods[-1].get("first_day"):
        periods[-1]["last_day"] = last_day.isoformat()
    profile["last_day"] = last_day.isoformat()


def marked_period_days(periods: list[dict], month: date) -> set[int]:
    marked: set[int] = set()
    month_start = date(month.year, month.month, 1)
    month_end = date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])

    for period in periods:
        try:
            first_day = date.fromisoformat(period["first_day"])
            last_day = date.fromisoformat(period.get("last_day") or period["first_day"])
        except (KeyError, TypeError, ValueError):
            continue
        if last_day < first_day or last_day < month_start or first_day > month_end:
            continue

        start = max(first_day, month_start)
        end = min(last_day, month_end)
        marked.update(range(start.day, end.day + 1))

    return marked


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    font_paths = (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    )
    for font_path in font_paths:
        if font_path.exists():
            return ImageFont.truetype(str(font_path), size)
    for font_name in ("Arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    raise RuntimeError("Не найден шрифт для создания изображения календаря.")


def _periods_cache_key(periods: list[dict]) -> tuple[tuple[str, str], ...]:
    entries = []
    for period in periods:
        first_day = period.get("first_day")
        last_day = period.get("last_day") or first_day
        if isinstance(first_day, str) and isinstance(last_day, str):
            entries.append((first_day, last_day))
    return tuple(entries)


@lru_cache(maxsize=24)
def _render_month_image(month: date, periods: tuple[tuple[str, str], ...]) -> bytes:
    width, height = 800, 710
    background = "#FFFFFF"
    foreground = "#252525"
    muted = "#777777"
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    title_font = _load_font(38)
    weekday_font = _load_font(22)
    day_font = _load_font(24)
    legend_font = _load_font(17)

    title = f"{MONTH_NAMES[month.month - 1].capitalize()} {month.year}"
    title_bounds = draw.textbbox((0, 0), title, font=title_font)
    draw.text(((width - (title_bounds[2] - title_bounds[0])) / 2, 38), title, fill=foreground, font=title_font)

    margin_x = 34
    grid_top = 128
    cell_width = (width - margin_x * 2) // 7
    cell_height = 84
    for column, weekday in enumerate(WEEKDAY_HEADERS):
        bounds = draw.textbbox((0, 0), weekday, font=weekday_font)
        x = margin_x + column * cell_width + (cell_width - (bounds[2] - bounds[0])) / 2
        draw.text((x, grid_top), weekday, fill=muted, font=weekday_font)

    marked = marked_period_days([{"first_day": start, "last_day": end} for start, end in periods], month)
    for week_index, week in enumerate(calendar.monthcalendar(month.year, month.month)):
        for column, day_number in enumerate(week):
            if not day_number:
                continue
            left = margin_x + column * cell_width
            top = grid_top + 48 + week_index * cell_height
            center_x = left + cell_width // 2
            center_y = top + cell_height // 2
            if day_number in marked:
                radius = 29
                draw.ellipse(
                    (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
                    fill=PERIOD_COLOR,
                )
                fill = "#FFFFFF"
            else:
                fill = foreground
            label = str(day_number)
            bounds = draw.textbbox((0, 0), label, font=day_font)
            text_x = center_x - (bounds[2] - bounds[0]) / 2
            text_y = center_y - (bounds[3] - bounds[1]) / 2 - bounds[1]
            draw.text((text_x, text_y), label, fill=fill, font=day_font)

    legend_y = height - 42
    draw.ellipse((margin_x, legend_y, margin_x + 18, legend_y + 18), fill=PERIOD_COLOR)
    draw.text((margin_x + 28, legend_y - 2), "Дни месячных", fill=muted, font=legend_font)

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def render_month_image(month: date, periods: list[dict]) -> bytes:
    return _render_month_image(month.replace(day=1), _periods_cache_key(periods))
