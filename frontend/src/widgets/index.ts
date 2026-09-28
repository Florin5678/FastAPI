// Frontend half of the widget registry: backend widget id -> how to render it.
// To add a widget: register it in app/widgets/ on the backend, then add its folder
// (component + stylesheet) under src/widgets/<name>/ and an entry here.
import { EmailSummaryWidget } from './email/EmailSummaryWidget'
import { WeatherWidget } from './weather/WeatherWidget'
import { NutritionWidget } from './nutrition/NutritionWidget'
import { NotesWidget } from './notes/NotesWidget'
import { NewsWidget } from './news/NewsWidget'
import { JournalWidget } from './journal/JournalWidget'
import { CalendarWidget } from './calendar/CalendarWidget'
import { AnimalWidget } from './animal/AnimalWidget'
import { GymWidget } from './gym/GymWidget'
import { LanguageWidget } from './language/LanguageWidget'
import { BudgetWidget } from './budget/BudgetWidget'
import { AssistantWidget } from './assistant/AssistantWidget'
import type { WidgetUI } from './types'

export const WIDGET_UI: Record<string, WidgetUI> = {
  email_summary: { icon: '✉️', component: EmailSummaryWidget },
  weather: { icon: '🌤️', component: WeatherWidget },
  nutrition: { icon: '🥗', component: NutritionWidget },
  notes: { icon: '📝', component: NotesWidget },
  news: { icon: '📰', component: NewsWidget },
  journal: { icon: '📓', component: JournalWidget },
  calendar: { icon: '📅', component: CalendarWidget },
  animal: { icon: '🐾', component: AnimalWidget },
  gym: { icon: '🏋️', component: GymWidget },
  language: { icon: '🗣️', component: LanguageWidget },
  budget: { icon: '💰', component: BudgetWidget },
  assistant: { icon: '✨', component: AssistantWidget },
}
