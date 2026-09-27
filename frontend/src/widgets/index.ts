// Frontend half of the widget registry: backend widget id -> how to render it.
// To add a widget: register it in app/widgets/ on the backend, then add its component here.
import { EmailSummaryWidget } from './EmailSummaryWidget'
import { WeatherWidget } from './WeatherWidget'
import type { WidgetUI } from './types'

export const WIDGET_UI: Record<string, WidgetUI> = {
  email_summary: { icon: '✉️', component: EmailSummaryWidget },
  weather: { icon: '🌤️', component: WeatherWidget },
}
