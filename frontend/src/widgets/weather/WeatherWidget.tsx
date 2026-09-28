import { useState } from 'react'
import type { WidgetProps } from '../types'
import { CitySkyline } from './CitySkyline'
import './weather.css'

type Condition = { code: number; label: string; icon: string }

export type WeatherData = {
  city: string
  country: string
  cities: string[]
  local_time: string
  current: { temperature: number; feels_like: number; humidity: number; wind_kmh: number; is_day: boolean; weather: Condition }
  today: { high: number; low: number; precipitation_probability: number | null; sunrise: string; sunset: string; weather: Condition }
  hours: { time: string; temperature: number; precipitation_probability: number | null; weather: Condition }[]
  source: 'Open-Meteo' | 'MET Norway' // MET Norway is the fallback when Open-Meteo is unavailable
}

// Sky gradient for the background, from the WMO weather code
function sky(code: number, isDay: boolean): string {
  if (code >= 95) return 'storm'
  if (!isDay) return 'night'
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return 'snow'
  if (code >= 51) return 'rain'
  if (code >= 2) return 'cloudy'
  return 'clear'
}

export function WeatherWidget({ data, updateSettings }: WidgetProps<WeatherData>) {
  const [switching, setSwitching] = useState<string | null>(null)

  const switchCity = async (city: string) => {
    if (city === data.city) return
    setSwitching(city)
    await updateSettings({ city })
    setSwitching(null)
  }

  const { current, today } = data

  return (
    <div className={`weather-widget sky-${sky(current.weather.code, current.is_day)}`}>
      <CitySkyline city={data.city} />
      <div className="weather-place">
        <span className="weather-city">{data.city}</span>
        <span className="weather-country">{data.country} · {data.local_time}</span>
      </div>
      <div className="segmented" role="group" aria-label="City">
        {data.cities.map((city) => (
          <button
            key={city}
            className={(switching ?? data.city) === city ? 'active' : ''}
            aria-pressed={data.city === city}
            onClick={() => switchCity(city)}
            disabled={switching !== null}
          >
            {city}
          </button>
        ))}
      </div>

      <div className="weather-now">
        <span className="weather-icon" aria-hidden>{current.weather.icon}</span>
        <div>
          <div className="weather-temp">{current.temperature}°</div>
          <div className="weather-label">{current.weather.label}</div>
        </div>
        <div className="weather-range">
          <span>H {today.high}°</span>
          <span>L {today.low}°</span>
        </div>
      </div>
      <div className="weather-feels">Feels like {current.feels_like}°</div>

      <div className="weather-stats">
        <span title="Chance of rain today">💧 {today.precipitation_probability ?? '–'}%</span>
        <span title="Wind">💨 {current.wind_kmh} km/h</span>
        <span title="Humidity">≈ {current.humidity}%</span>
        <span title="Sunrise and sunset">🌅 {today.sunrise} – {today.sunset}</span>
      </div>

      <div className="hourly" aria-label="Next hours">
        {data.hours.map((h, i) => (
          <div key={h.time + i} className="hour">
            <span className="hour-time">{i === 0 ? 'Now' : h.time}</span>
            <span className="hour-icon" title={h.weather.label} aria-label={h.weather.label}>{h.weather.icon}</span>
            <span className="hour-temp">{h.temperature}°</span>
            {h.precipitation_probability ? <span className="hour-rain">{h.precipitation_probability}%</span> : <span className="hour-rain" />}
          </div>
        ))}
      </div>
      {data.source === 'MET Norway' && <div className="weather-source">Weather data: MET Norway</div>}
    </div>
  )
}
