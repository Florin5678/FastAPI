import type { ComponentType } from 'react'

// Things any widget can ask the dashboard to do
export type DashboardActions = {
  openEmail: (id: number) => void
  goTo: (view: 'today' | 'inbox', options?: { category?: string }) => void
}

export type WidgetProps<T> = {
  data: T
  settings: Record<string, unknown>
  actions: DashboardActions
  // Save some of this widget's settings (e.g. a quick toggle inside the widget);
  // the widget reloads with the new settings afterwards
  updateSettings: (changes: Record<string, unknown>) => Promise<void>
}

export type WidgetUI<T = any> = {
  icon: string // a single emoji keeps widgets recognizable without an icon library
  component: ComponentType<WidgetProps<T>>
}
