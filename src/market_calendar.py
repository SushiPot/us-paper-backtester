from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd


NEW_YORK_TZ = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class MarketSession:
    """美股交易日历快照。"""

    trading_day: date
    is_trading_day: bool
    is_regular_hours: bool
    market_open: datetime | None
    market_close: datetime | None
    source: str


def now_new_york() -> datetime:
    """返回纽约当前时间。"""
    return datetime.now(NEW_YORK_TZ)


def is_us_market_trading_day(day: date | None = None) -> bool:
    """判断是否为美股交易日。优先使用 pandas_market_calendars，失败则回退到内置 NYSE 假期。"""
    current = day or now_new_york().date()
    session = get_us_market_session(datetime.combine(current, time(12, 0), tzinfo=NEW_YORK_TZ))
    if session.source != "fallback":
        return session.is_trading_day
    if current.weekday() >= 5:
        return False
    return current not in nyse_holidays(current.year)


def is_regular_us_market_hours(moment: datetime | None = None) -> bool:
    """美股正常交易时间。优先使用 NYSE 官方日历，包含提前收盘。"""
    current = moment.astimezone(NEW_YORK_TZ) if moment else now_new_york()
    return get_us_market_session(current).is_regular_hours


def get_us_market_session(moment: datetime | None = None) -> MarketSession:
    """返回当前/指定时刻对应的 NYSE 交易日历信息。"""
    current = moment.astimezone(NEW_YORK_TZ) if moment else now_new_york()
    try:
        return _session_from_pandas_market_calendars(current)
    except Exception:
        return _fallback_session(current)


def _session_from_pandas_market_calendars(current: datetime) -> MarketSession:
    import pandas_market_calendars as mcal

    calendar = mcal.get_calendar("NYSE")
    current_day = current.date()
    schedule = calendar.schedule(
        start_date=(current_day - timedelta(days=1)).isoformat(),
        end_date=(current_day + timedelta(days=1)).isoformat(),
    )
    if schedule.empty:
        return MarketSession(current_day, False, False, None, None, "pandas_market_calendars")

    day_key = pd.Timestamp(current_day)
    if day_key not in schedule.index:
        return MarketSession(current_day, False, False, None, None, "pandas_market_calendars")

    row = schedule.loc[day_key]
    market_open = pd.Timestamp(row["market_open"]).to_pydatetime().astimezone(NEW_YORK_TZ)
    market_close = pd.Timestamp(row["market_close"]).to_pydatetime().astimezone(NEW_YORK_TZ)
    return MarketSession(
        trading_day=current_day,
        is_trading_day=True,
        is_regular_hours=market_open <= current <= market_close,
        market_open=market_open,
        market_close=market_close,
        source="pandas_market_calendars",
    )


def _fallback_session(current: datetime) -> MarketSession:
    current_day = current.date()
    is_trading_day = current_day.weekday() < 5 and current_day not in nyse_holidays(current_day.year)
    market_open = datetime.combine(current_day, time(9, 30), tzinfo=NEW_YORK_TZ) if is_trading_day else None
    market_close = datetime.combine(current_day, time(16, 0), tzinfo=NEW_YORK_TZ) if is_trading_day else None
    is_regular = bool(is_trading_day and market_open and market_close and market_open <= current <= market_close)
    return MarketSession(current_day, is_trading_day, is_regular, market_open, market_close, "fallback")


def nyse_holidays(year: int) -> set[date]:
    """NYSE 常见休市日，含周末顺延和 Good Friday。"""
    holidays = {
        observed(date(year, 1, 1)),
        nth_weekday(year, 1, 0, 3),   # Martin Luther King Jr. Day
        nth_weekday(year, 2, 0, 3),   # Presidents Day
        good_friday(year),
        last_weekday(year, 5, 0),     # Memorial Day
        observed(date(year, 6, 19)),  # Juneteenth
        observed(date(year, 7, 4)),
        nth_weekday(year, 9, 0, 1),   # Labor Day
        nth_weekday(year, 11, 3, 4),  # Thanksgiving
        observed(date(year, 12, 25)),
    }
    return {holiday for holiday in holidays if holiday.year == year}


def observed(day: date) -> date:
    """周六假期通常周五观察，周日假期通常周一观察。"""
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    current = date(year, month, 1)
    while current.weekday() != weekday:
        current += timedelta(days=1)
    return current + timedelta(days=7 * (n - 1))


def last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        current = date(year, 12, 31)
    else:
        current = date(year, month + 1, 1) - timedelta(days=1)
    while current.weekday() != weekday:
        current -= timedelta(days=1)
    return current


def good_friday(year: int) -> date:
    """Meeus/Jones/Butcher 算法计算复活节，再向前两天得到 Good Friday。"""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day) - timedelta(days=2)
