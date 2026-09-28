# Assistant prompt

What the Assistant widget sends to Claude together with your daily briefing.
Edit the text under each heading (keep the four `## ` headings as they are).
`{when}` is replaced with the current day and time. "Default question" is what
the "Brief me" button asks Claude, after the briefing.

Under "Extra instructions", each line is one extra request added to the prompt:
`- [x] Name: what to ask Claude` is on, `- [ ] Name: ...` is off. Tick or untick
the box to switch one, edit the text after the colon, or add your own lines.

Under "Briefing", each line is one widget:
- a number = how many items (emails, events, headlines...) are sent
- `off` = leave that widget out of the briefing
- `on` = include it as is (for widgets without a list)
Widgets missing from the list are included as usual. Widgets you haven't added to
the dashboard are never sent, and your journal is never included.

## Instructions

Here is my personal dashboard briefing for {when}. Use it as context.

## Extra instructions

- [x] Daily forecast: Tell me about upcoming Calendar events, time, weather, current week number, moon phase (and/or any significant astronomical events observable today).
- [x] Email: Tell me which whether there are any important emails need whether any of them need a reply today.
- [x] Slack: Check for any new Slack messages from the last 24 hours and tell me which ones need a reply.
- [x] Urgent tasks: Tell me which urgent tasks need addressing (see Notes & reminders).
- [x] Meal recommendations: Suggest meals and snacks for the rest of today that fit what I've already eaten (see Nutrition).
- [x] Workout recommendations: Suggest today's workout based on what I've trained recently (see Gym), so muscle groups get enough rest.
- [x] News digest: Present up to 3 most important news headlines (if any).
- [x] Mental health: Either give me a practical suggestion for my wellbeing today (a break, a walk, time offline, reaching out to someone) based on how busy my day looks; alternatively give me one journaling question for today.

## Default question

Brief me.

## Briefing

- Email: 10
- Calendar: 12
- Weather: on
- Nutrition: 8
- Notes & reminders: 10
- News: 6
- Gym: on
- Language: off
- Animal of the day: off
