import { useState } from 'react'
import type { WidgetProps } from './types'

type Condition = { code: number; label: string; icon: string }

export type WeatherData = {
  city: string
  country: string
  cities: string[]
  local_time: string
  current: { temperature: number; feels_like: number; humidity: number; wind_kmh: number; weather: Condition }
  today: { high: number; low: number; precipitation_probability: number | null; sunrise: string; sunset: string; weather: Condition }
  hours: { time: string; temperature: number; precipitation_probability: number | null; weather: Condition }[]
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
    <div className="weather-widget">
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
      <div className="muted small">
        Feels like {current.feels_like}° · {data.city} {data.local_time}
      </div>

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
    </div>
  )
}
