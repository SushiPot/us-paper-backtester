from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


NEW_YORK_TZ = ZoneInfo("America/New_York")


def now_new_york() -> datetime:
    """返回纽约当前时间。"""
    return datetime.now(NEW_YORK_TZ)


def is_us_market_trading_day(day: date | None = None) -> bool:
    """判断是否为美股交易日。覆盖常见 NYSE 假期，足够用于运行前安全门。"""
    current = day or now_new_york().date()
    if current.weekday() >= 5:
        return False
    return current not in nyse_holidays(current.year)


def is_regular_us_market_hours(moment: datetime | None = None) -> bool:
    """美股常规交易时间：纽约时间周一至周五 09:30-16:00。"""
    current = moment.astimezone(NEW_YORK_TZ) if moment else now_new_york()
    if not is_us_market_trading_day(current.date()):
        return False
    return time(9, 30) <= current.time() <= time(16, 0)


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
