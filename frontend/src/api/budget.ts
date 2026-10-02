// Budget widget: entries, the monthly report, budgets, CSV import/export
import { json, request } from './client'

export type BudgetEntry = { id: number; month: string; path: string[]; amount: number }

export type BudgetMonth = {
  month: string // YYYY-MM
  currency: string
  entries: BudgetEntry[]
  income: number
  expenses: number
  previous: { month: string; income: number | null; expenses: number | null; categories: Record<string, number> }
  budgets: Record<string, number>
  history: { month: string; income: number; expenses: number }[]
  first_month: string | null
  paths: string[][]
  expense_categories: string[] // the fixed sub-categories under Expenses, alphabetical
}

export const budgetApi = {
  month: (month: string) => request<BudgetMonth>(`/widgets/budget/month?month=${month}`),
  add: (entry: { month: string; path: string[]; amount: number }) =>
    request<BudgetEntry>('/widgets/budget/entries', { method: 'POST', ...json(entry) }),
  update: (id: number, changes: Partial<Omit<BudgetEntry, 'id'>>) =>
    request<BudgetEntry>(`/widgets/budget/entries/${id}`, { method: 'PATCH', ...json(changes) }),
  remove: (id: number) => request<unknown>(`/widgets/budget/entries/${id}`, { method: 'DELETE' }),
  removeGroup: (path: string[], month: string) =>
    request<{ deleted: number }>('/widgets/budget/delete-group', { method: 'POST', ...json({ path, month }) }),
  setBudgets: (budgets: Record<string, number | null>) =>
    request<{ budgets: Record<string, number> }>('/widgets/budget/budgets', { method: 'PUT', ...json({ budgets }) }),
  importCsv: (csv: string, replace: boolean) =>
    request<{ imported: number; skipped: number; problems: string[] }>('/widgets/budget/import', { method: 'POST', ...json({ csv, replace }) }),
  exportUrl: '/widgets/budget/export',
}
