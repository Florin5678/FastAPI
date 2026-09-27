# Weather widget: today's weather from Open-Meteo (https://open-meteo.com).
# Free for non-commercial use, no API key. Free-tier cap: 10,000 calls/day, so
# responses are cached per city for 10 minutes (this app makes a few dozen a day).
import time

import requests
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import User
from app.widgets.registry import ConfigField, WidgetContext, WidgetDefinition, register

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
CACHE_SECONDS = 600

CITIES = {
    "Aarhus": {"latitude": 56.1567, "longitude": 10.2108, "country": "Denmark"},
    "Bucharest": {"latitude": 44.4268, "longitude": 26.1025, "country": "Romania"},
}

# WMO weather interpretation codes -> (label, day icon, night icon)
WMO = {
    0: ("Clear sky", "☀️", "🌙"),
    1: ("Mainly clear", "🌤️", "🌙"),
    2: ("Partly cloudy", "⛅", "☁️"),
    3: ("Overcast", "☁️", "☁️"),
    45: ("Fog", "🌫️", "🌫️"),
    48: ("Freezing fog", "🌫️", "🌫️"),
    51: ("Light drizzle", "🌦️", "🌧️"),
    53: ("Drizzle", "🌦️", "🌧️"),
    55: ("Heavy drizzle", "🌧️", "🌧️"),
    56: ("Freezing drizzle", "🌧️", "🌧️"),
    57: ("Freezing drizzle", "🌧️", "🌧️"),
    61: ("Light rain", "🌦️", "🌧️"),
    63: ("Rain", "🌧️", "🌧️"),
    65: ("Heavy rain", "🌧️", "🌧️"),
    66: ("Freezing rain", "🌧️", "🌧️"),
    67: ("Freezing rain", "🌧️", "🌧️"),
    71: ("Light snow", "🌨️", "🌨️"),
    73: ("Snow", "🌨️", "🌨️"),
    75: ("Heavy snow", "❄️", "❄️"),
    77: ("Snow grains", "🌨️", "🌨️"),
    80: ("Light showers", "🌦️", "🌧️"),
    81: ("Showers", "🌧️", "🌧️"),
    82: ("Violent showers", "⛈️", "⛈️"),
    85: ("Snow showers", "🌨️", "🌨️"),
    86: ("Heavy snow showers", "❄️", "❄️"),
    95: ("Thunderstorm", "⛈️", "⛈️"),
    96: ("Thunderstorm with hail", "⛈️", "⛈️"),
    99: ("Thunderstorm with hail", "⛈️", "⛈️"),
}

_cache: dict[str, tuple[float, dict]] = {}


def _describe(code: int, is_day: bool = True) -> dict:
    label, day_icon, night_icon = WMO.get(code, ("Unknown", "🌡️", "🌡️"))
    return {"code": code, "label": label, "icon": day_icon if is_day else night_icon}


def _forecast(city: str) -> dict:
    cached = _cache.get(city)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]

    place = CITIES[city]
    try:
        response = requests.get(
            FORECAST_URL,
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m,is_day",
                "hourly": "temperature_2m,weather_code,precipitation_probability,is_day",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
                "timezone": "auto",  # times come back in the city's local time
                "forecast_days": 2,  # tomorrow's early hours keep the hourly strip full late in the day
            },
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException:
        if cached:
            return cached[1]  # stale beats nothing
        raise HTTPException(status_code=502, detail="The weather service didn't respond. Try again in a minute.")

    data = response.json()
    _cache[city] = (time.time(), data)
    return data


def fetch(db: Session, user: User, settings: dict, ctx: WidgetContext) -> dict:
    city = settings["city"] if settings["city"] in CITIES else "Aarhus"
    raw = _forecast(city)
    current, hourly, daily = raw["current"], raw["hourly"], raw["daily"]

    # Next 12 hours from the current local hour (hourly times are local, "YYYY-MM-DDTHH:00")
    now_hour = current["time"][:13]
    start = next((i for i, t in enumerate(hourly["time"]) if t[:13] >= now_hour), 0)
    hours = [
        {
            "time": hourly["time"][i][11:16],
            "temperature": round(hourly["temperature_2m"][i]),
            "precipitation_probability": hourly["precipitation_probability"][i],
            "weather": _describe(hourly["weather_code"][i], bool(hourly["is_day"][i])),
        }
        for i in range(start, min(start + 12, len(hourly["time"])))
    ]

    return {
        "city": city,
        "country": CITIES[city]["country"],
        "cities": list(CITIES),
        "local_time": current["time"][11:16],
        "current": {
            "temperature": round(current["temperature_2m"]),
            "feels_like": round(current["apparent_temperature"]),
            "humidity": current["relative_humidity_2m"],
            "wind_kmh": round(current["wind_speed_10m"]),
            "weather": _describe(current["weather_code"], bool(current["is_day"])),
        },
        "today": {
            "high": round(daily["temperature_2m_max"][0]),
            "low": round(daily["temperature_2m_min"][0]),
            "precipitation_probability": daily["precipitation_probability_max"][0],
            "sunrise": daily["sunrise"][0][11:16],
            "sunset": daily["sunset"][0][11:16],
            "weather": _describe(daily["weather_code"][0]),
        },
        "hours": hours,
    }


register(WidgetDefinition(
    id="weather",
    name="Weather",
    description="Today's weather for Aarhus or Bucharest (Open-Meteo, free).",
    fetch=fetch,
    default_size=(4, 8),
    min_size=(3, 6),
    refresh_seconds=900,
    enabled_by_default=True,
    config_fields=(
        ConfigField("city", "City", "select", default="Aarhus", options=list(CITIES)),
    ),
))
