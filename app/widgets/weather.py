# Weather widget: today's weather from Open-Meteo (https://open-meteo.com), with MET
# Norway (https://api.met.no, CC BY 4.0) as the fallback.
# Open-Meteo is free without a key, but its 10,000 calls/day limit counts per IP, and
# Render's free tier shares IPs between many apps, so it often answers 429 there even
# though this app makes only a few dozen calls a day. MET Norway identifies clients by
# User-Agent instead; its forecast is converted to Open-Meteo's response shape so
# fetch() works the same for both. Responses are cached per city.
import logging
import math
import time
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

import requests
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import User
from app.widgets.registry import ConfigField, WidgetContext, WidgetDefinition, register

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MET_FORECAST_URL = "https://api.met.no/weatherapi/locationforecast/2.0/complete"
MET_SUN_URL = "https://api.met.no/weatherapi/sunrise/3.0/sun"
CACHE_SECONDS = 600
MET_CACHE_SECONDS = 1800  # MET Norway asks clients not to poll more often than their data updates
OPEN_METEO_PAUSE_SECONDS = 3600  # after a 429 (shared-IP daily limit), go straight to MET Norway
STALE_SECONDS = 6 * 3600  # if Open-Meteo fails, keep showing the last forecast this long
# Identify the app (some APIs turn away anonymous requests from shared cloud IPs)
USER_AGENT = "PersonalDashboard/1.0 (https://github.com/Florin5678/FastAPI; personal non-commercial dashboard)"
logger = logging.getLogger(__name__)

CITIES = {
    "Aarhus": {"latitude": 56.1567, "longitude": 10.2108, "country": "Denmark", "tz": "Europe/Copenhagen"},
    "Bucharest": {"latitude": 44.4268, "longitude": 26.1025, "country": "Romania", "tz": "Europe/Bucharest"},
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
    68: ("Sleet", "🌨️", "🌨️"),  # WMO 68/69: rain and snow (MET Norway "sleet")
    69: ("Heavy sleet", "🌨️", "🌨️"),
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

# MET Norway symbol codes (without _day/_night/_polartwilight) -> WMO codes above
MET_SYMBOLS = {
    "clearsky": 0, "fair": 1, "partlycloudy": 2, "cloudy": 3, "fog": 45,
    "lightrain": 61, "rain": 63, "heavyrain": 65,
    "lightrainshowers": 80, "rainshowers": 81, "heavyrainshowers": 82,
    "lightsleet": 68, "sleet": 68, "heavysleet": 69,
    "lightsleetshowers": 68, "sleetshowers": 68, "heavysleetshowers": 69,
    "lightsnow": 71, "snow": 73, "heavysnow": 75,
    "lightsnowshowers": 85, "snowshowers": 85, "heavysnowshowers": 86,
}

_cache: dict[str, tuple[float, dict]] = {}  # city -> (expires at, raw forecast)
_open_meteo_paused_until = 0.0


def _describe(code: int, is_day: bool = True) -> dict:
    label, day_icon, night_icon = WMO.get(code, ("Unknown", "🌡️", "🌡️"))
    return {"code": code, "label": label, "icon": day_icon if is_day else night_icon}


def _forecast(city: str) -> dict:
    """Open-Meteo's forecast for a city (or MET Norway's, converted to the same shape)."""
    global _open_meteo_paused_until
    cached = _cache.get(city)
    if cached and time.time() < cached[0]:
        return cached[1]

    reasons = []
    if time.time() >= _open_meteo_paused_until:
        try:
            data = _open_meteo(city)
            _cache[city] = (time.time() + CACHE_SECONDS, data)
            return data
        except requests.RequestException as e:
            reasons.append(f"Open-Meteo {_failure_reason(e)}")
            if getattr(getattr(e, "response", None), "status_code", None) == 429:
                _open_meteo_paused_until = time.time() + OPEN_METEO_PAUSE_SECONDS
    try:
        data = _met_norway(city)
        _cache[city] = (time.time() + MET_CACHE_SECONDS, data)
        return data
    except (requests.RequestException, KeyError, IndexError, ValueError) as e:
        reasons.append(f"MET Norway {_failure_reason(e) if isinstance(e, requests.RequestException) else type(e).__name__}")

    reason = "; ".join(reasons)
    logger.warning("Weather for %s failed: %s", city, reason)
    if cached and time.time() - cached[0] < STALE_SECONDS:
        return cached[1]  # stale beats nothing
    raise HTTPException(status_code=502, detail=f"The weather service didn't respond ({reason}). Try again in a minute.")


def _open_meteo(city: str) -> dict:
    place = CITIES[city]
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
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    data["source"] = "Open-Meteo"
    return data


def _apparent_temperature(temp_c: float, humidity: float, wind_ms: float) -> float:
    """Steadman's apparent temperature (the "feels like" formula Open-Meteo also uses)."""
    vapour = humidity / 100 * 6.105 * math.exp(17.27 * temp_c / (237.7 + temp_c))
    return temp_c + 0.33 * vapour - 0.70 * wind_ms - 4.00


def _met_code(symbol: str) -> tuple[int, Optional[bool]]:
    """MET symbol code -> (WMO code, is_day or None when the symbol doesn't say)."""
    base, _, variant = symbol.partition("_")
    if "thunder" in base:
        code = 95
    else:
        code = MET_SYMBOLS.get(base, 3)
    return code, (True if variant == "day" else False if variant in ("night", "polartwilight") else None)


def _met_sun(place: dict, day: date, zone: ZoneInfo) -> tuple[str, str]:
    offset = datetime.combine(day, datetime.min.time(), zone).strftime("%z")
    response = requests.get(
        MET_SUN_URL,
        params={"lat": round(place["latitude"], 4), "lon": round(place["longitude"], 4),
                "date": day.isoformat(), "offset": f"{offset[:3]}:{offset[3:]}"},
        headers={"User-Agent": USER_AGENT}, timeout=15,
    )
    response.raise_for_status()
    props = response.json()["properties"]
    return props["sunrise"]["time"][:16], props["sunset"]["time"][:16]


def _met_norway(city: str) -> dict:
    """MET Norway's forecast converted to Open-Meteo's response shape (local times)."""
    place = CITIES[city]
    zone = ZoneInfo(place["tz"])
    response = requests.get(
        MET_FORECAST_URL,
        params={"lat": round(place["latitude"], 4), "lon": round(place["longitude"], 4)},
        headers={"User-Agent": USER_AGENT}, timeout=15,
    )
    response.raise_for_status()
    series = response.json()["properties"]["timeseries"]
    now = datetime.now(zone)
    today = now.date()
    sunrise, sunset = _met_sun(place, today, zone)

    def local(ts: str) -> datetime:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(zone)

    def is_daytime(moment: datetime) -> bool:
        clock = moment.strftime("%H:%M")
        return sunrise[11:16] <= clock < sunset[11:16]

    hourly = {"time": [], "temperature_2m": [], "weather_code": [], "precipitation_probability": [], "is_day": []}
    for entry in series:
        next_hour = entry["data"].get("next_1_hours")
        if next_hour is None:
            break  # beyond ~2.5 days MET only gives 6-hour steps
        moment = local(entry["time"])
        code, day_flag = _met_code(next_hour["summary"]["symbol_code"])
        hourly["time"].append(moment.strftime("%Y-%m-%dT%H:00"))
        hourly["temperature_2m"].append(entry["data"]["instant"]["details"]["air_temperature"])
        hourly["weather_code"].append(code)
        probability = next_hour.get("details", {}).get("probability_of_precipitation")
        hourly["precipitation_probability"].append(round(probability) if probability is not None else None)
        hourly["is_day"].append(int(day_flag if day_flag is not None else is_daytime(moment)))

    first = series[0]["data"]
    details = first["instant"]["details"]
    summary = (first.get("next_1_hours") or first.get("next_6_hours") or {}).get("summary", {"symbol_code": "cloudy"})
    code, day_flag = _met_code(summary["symbol_code"])
    current_is_day = day_flag if day_flag is not None else is_daytime(now)

    today_temps = [t for t, ts in zip(hourly["temperature_2m"], hourly["time"], strict=True) if ts[:10] == today.isoformat()]
    today_probs = [p for p, ts in zip(hourly["precipitation_probability"], hourly["time"], strict=True)
                   if ts[:10] == today.isoformat() and p is not None]
    day_symbol = (first.get("next_12_hours") or first.get("next_6_hours") or {}).get("summary", summary)["symbol_code"]
    return {
        "source": "MET Norway",
        "current": {
            "time": now.strftime("%Y-%m-%dT%H:%M"),
            "temperature_2m": details["air_temperature"],
            "apparent_temperature": _apparent_temperature(details["air_temperature"], details["relative_humidity"], details["wind_speed"]),
            "weather_code": code,
            "wind_speed_10m": details["wind_speed"] * 3.6,  # m/s -> km/h
            "relative_humidity_2m": round(details["relative_humidity"]),
            "is_day": int(current_is_day),
        },
        "hourly": hourly,
        "daily": {
            "weather_code": [_met_code(day_symbol)[0]],
            "temperature_2m_max": [max(today_temps or [details["air_temperature"]])],
            "temperature_2m_min": [min(today_temps or [details["air_temperature"]])],
            "precipitation_probability_max": [max(today_probs) if today_probs else None],
            "sunrise": [sunrise],
            "sunset": [sunset],
        },
    }


def _failure_reason(e: requests.RequestException) -> str:
    """A short reason for the error message, e.g. "HTTP 429: Daily API request limit exceeded"."""
    response = getattr(e, "response", None)
    if response is None:
        return type(e).__name__  # e.g. ConnectTimeout, ConnectionError
    detail = ""
    try:
        detail = str(response.json().get("reason") or "")
    except ValueError:
        detail = response.text[:120]
    return f"HTTP {response.status_code}" + (f": {detail}" if detail else "")


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
            "is_day": bool(current["is_day"]),
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
        "source": raw.get("source", "Open-Meteo"),
    }


def brief(data: dict, limit: int | None = None) -> str:
    now, today = data["current"], data["today"]
    return (
        f"{data['city']}: {now['temperature']}°C, {now['weather']['label'].lower()} "
        f"(feels like {now['feels_like']}°C). Today {today['low']}–{today['high']}°C, "
        f"{today['precipitation_probability'] or 0}% chance of rain, wind {now['wind_kmh']} km/h."
    )


register(WidgetDefinition(
    id="weather",
    name="Weather",
    description="Today's weather for Aarhus or Bucharest (Open-Meteo, free).",
    fetch=fetch,
    brief=brief,
    default_size=(4, 9),
    min_size=(3, 7),
    layout_version=3,  # v2: next to the narrower email widget; v3: taller for the skyline
    refresh_seconds=900,
    enabled_by_default=True,
    config_fields=(
        ConfigField("city", "City", "select", default="Aarhus", options=list(CITIES)),
    ),
))
