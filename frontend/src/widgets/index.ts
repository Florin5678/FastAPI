// Frontend half of the widget registry: backend widget id -> how to render it.
// To add a widget: register it in app/widgets/ on the backend, then add its component here.
import { EmailSummaryWidget } from './EmailSummaryWidget'
import { WeatherWidget } from './WeatherWidget'
import { NutritionWidget } from './NutritionWidget'
import { NotesWidget } from './NotesWidget'
import { NewsWidget } from './NewsWidget'
import type { WidgetUI } from './types'

export const WIDGET_UI: Record<string, WidgetUI> = {
  email_summary: { icon: '✉️', component: EmailSummaryWidget },
  weather: { icon: '🌤️', component: WeatherWidget },
  nutrition: { icon: '🥗', component: NutritionWidget },
  notes: { icon: '📝', component: NotesWidget },
  news: { icon: '📰', component: NewsWidget },
}
