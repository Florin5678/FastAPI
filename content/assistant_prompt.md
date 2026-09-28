# Assistant prompt

What the Assistant widget sends to Claude together with your daily briefing.
Edit the text under each heading (keep the four `## ` headings as they are).
`{when}` is replaced with the current day and time.

Under "Briefing", each line is one widget:
- a number = how many items (emails, events, headlines...) are sent
- `off` = leave that widget out of the briefing
- `on` = include it as is (for widgets without a list)
Widgets missing from the list are included as usual. Widgets you haven't added to
the dashboard are never sent, and your journal is never included.

## Instructions

Here is my personal dashboard briefing for {when}. Use it as context.

## Default question

Brief me.

## Suggestions

- Plan my day
- Anything I should not forget today?
- Plan my meals for the day
- Summarize my week so far

## Briefing

- Email: 5
- Calendar: 12
- Weather: on
- Nutrition: 8
- Notes & reminders: 10
- News: 6
- Gym: on
- Language: on
- Animal of the day: on
