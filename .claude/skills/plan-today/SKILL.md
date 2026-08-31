---
name: plan-today
description: >
  Draft a daily plan based on active projects, recent reports, and calendar
  context. Use when the user says "plan today", "what's on today", "plan my
  day", "daily plan", "what should I work on", or "priorities".
allowed-tools: Read, Write, Grep, Glob
---

# Plan Today

1. Read `vault/99-Meta/index.md` to orient.
2. Check `vault/10-Projects/` for active projects (any note modified in the last 14 days).
3. Check `vault/30-Reports/` for the most recent trend scan and weekly status.
4. Check `vault/00-Inbox/` for unprocessed items.
5. Draft a daily plan with:
   - **Top 3 priorities** — ranked by urgency and recency.
   - **Quick wins** — small tasks from inbox or project notes.
   - **Blocked / waiting** — items that need external input.
6. Write to `vault/30-Reports/plan-{YYYY-MM-DD}.md`.
7. Return the plan inline.
