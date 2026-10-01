# Facts about today for the Assistant's briefing, worked out here instead of asking Claude
# (which skips or guesses them): the date and ISO week, moon phase (same maths as the
# dashboard header, frontend/src/lib/moon.ts), public holidays in Denmark and Romania,
# daylight-saving changes and the year's main sky events. No API calls.
import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import holidays

HOLIDAY_COUNTRIES = {"DK": "Denmark", "RO": "Romania"}
LOOKAHEAD_DAYS = 14

# Mean synodic month from a known new moon: within about half a day
SYNODIC_DAYS = 29.530588853
KNOWN_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
PHASES = [  # (age in days up to, name)
    (1.85, "new moon"), (5.54, "waxing crescent"), (9.23, "first quarter"), (SYNODIC_DAYS / 2, "waxing gibbous"),
    (20.3, "waning gibbous"), (23.99, "last quarter"), (27.68, "waning crescent"), (SYNODIC_DAYS, "new moon"),
]

# Peaks of the main meteor showers and the solstices/equinoxes (they move by a day at most)
SKY_EVENTS = [
    ((1, 3), "Quadrantids meteor shower peaks (night of 3–4 Jan)"),
    ((3, 20), "March equinox (spring starts)"),
    ((4, 22), "Lyrids meteor shower peaks (night of 22–23 Apr)"),
    ((5, 6), "Eta Aquariids meteor shower peaks (before dawn, 5–6 May)"),
    ((6, 21), "June solstice (longest day)"),
    ((8, 12), "Perseids meteor shower peaks (night of 12–13 Aug)"),
    ((9, 22), "September equinox (autumn starts)"),
    ((10, 21), "Orionids meteor shower peaks (night of 21–22 Oct)"),
    ((11, 17), "Leonids meteor shower peaks (night of 17–18 Nov)"),
    ((12, 14), "Geminids meteor shower peaks (night of 13–14 Dec)"),
    ((12, 21), "December solstice (shortest day)"),
]


def _moon_age(moment: datetime) -> float:
    return ((moment - KNOWN_NEW_MOON).total_seconds() / 86400) % SYNODIC_DAYS


def _next_age(moment: datetime, target_age: float) -> datetime:
    """When the moon next reaches `target_age` (0 = new, half the month = full)."""
    wait = (target_age - _moon_age(moment)) % SYNODIC_DAYS
    return moment + timedelta(days=wait)


def moon_line(moment: datetime, zone: ZoneInfo) -> str:
    age = _moon_age(moment)
    lit = round((1 - math.cos(2 * math.pi * age / SYNODIC_DAYS)) / 2 * 100)
    name = next(n for max_age, n in PHASES if age < max_age)
    if abs(age - SYNODIC_DAYS / 2) <= 1:
        name = "full moon"
    full, new = _next_age(moment, SYNODIC_DAYS / 2), _next_age(moment, 0)
    return (f"Moon tonight: {name}, {lit}% lit. Next full moon {full.astimezone(zone):%a %d %b}, "
            f"next new moon {new.astimezone(zone):%a %d %b}.")


def _last_sunday(year: int, month: int) -> date:
    last = date(year, month + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() + 1) % 7)


def _upcoming(today: date) -> list[tuple[date, str]]:
    """Holidays, clock changes and sky events from today to LOOKAHEAD_DAYS ahead."""
    end = today + timedelta(days=LOOKAHEAD_DAYS)
    years = sorted({today.year, end.year})
    found: list[tuple[date, str]] = []
    for code, country in HOLIDAY_COUNTRIES.items():
        try:
            calendar = holidays.country_holidays(code, years=years, language="en_US")
        except (NotImplementedError, KeyError):
            calendar = holidays.country_holidays(code, years=years)
        found += [(day, f"{name} (public holiday in {country})") for day, name in calendar.items() if today <= day <= end]
    for year in years:
        found.append((_last_sunday(year, 3), "Clocks go forward 1 hour in Europe (summer time starts)"))
        found.append((_last_sunday(year, 10), "Clocks go back 1 hour in Europe (summer time ends)"))
        found += [(date(year, m, d), text) for (m, d), text in SKY_EVENTS]
    return sorted((day, text) for day, text in found if today <= day <= end)


def today_section(tz: str | None) -> str:
    zone = ZoneInfo(tz or "Europe/Copenhagen")
    now = datetime.now(zone)
    today = now.date()
    lines = [
        f"{now:%A %d %B %Y}, ISO week {today.isocalendar().week}, day {today.timetuple().tm_yday} of the year.",
        moon_line(now, zone),
    ]
    events = _upcoming(today)
    todays = [text for day, text in events if day == today]
    lines.append("Today: " + ("; ".join(todays) if todays else "no public holidays (Denmark, Romania) or notable sky events."))
    later = [f"- {day:%a %d %b}: {text}" for day, text in events if day != today]
    if later:
        lines.append(f"Coming up (next {LOOKAHEAD_DAYS} days):")
        lines += later
    return "\n".join(lines)
