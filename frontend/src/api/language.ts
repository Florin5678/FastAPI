// Language widget: flashcard reviews
import { json, request } from './client'

export type ReviewGrade = 'again' | 'good' | 'easy'

export const languageApi = {
  review: (review: { language: string; word: string; grade: ReviewGrade; day: string }) =>
    request<{ word: string; due: string; interval_days: number }>('/widgets/language/review', { method: 'POST', ...json(review) }),
}
