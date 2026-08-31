---
name: weekly-status-writer
description: >
  Compile a weekly status report from vault notes and recent activity. Use when
  the user says "weekly status", "weekly report", "write the weekly",
  "status update", "week in review", or "what happened this week".
allowed-tools: Read, Write, Grep, Glob
---

# Weekly Status Writer

1. Scan `vault/30-Reports/` for all notes from the past 7 days.
2. Scan `vault/10-Projects/` for any notes modified this week.
3. Compile a status report with sections:
   - **Completed** — work finished this week (from reports).
   - **In Progress** — active projects with recent changes.
   - **Upcoming** — any TODOs or scheduled items found in notes.
   - **Blockers** — anything tagged `#blocked` or mentioning "waiting on".
4. Write to `vault/30-Reports/weekly-status-{YYYY-MM-DD}.md` with `[[wikilinks]]` to source notes.
5. Return a one-paragraph summary inline.
