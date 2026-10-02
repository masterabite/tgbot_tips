from datetime import date

import pytest

from bot import parse_input_date


def test_parse_date_in_day_month_year_format():
    assert parse_input_date("01.10.2026") == date(2026, 10, 1)


@pytest.mark.parametrize("value", ["2026-10-01", "01-10-2026", "1.10.2026", "01/10/2026", "31.02.2026"])
def test_rejects_invalid_or_noncanonical_date(value):
    with pytest.raises(ValueError):
        parse_input_date(value)
