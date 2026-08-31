---
name: morning-trend-scan
description: >
  Pull trending topics and write a ranked brief. Use every morning, or when the
  user says "what's trending", "trend scan", "morning scan", "what's hot",
  "trending topics", or "news brief".
allowed-tools: Read, Write, Bash, Grep, Glob, WebSearch
---

# Morning Trend Scan

1. Run `${CLAUDE_SKILL_DIR}/scripts/scan.py` to fetch raw trend data.
   - The script prints JSON to stdout: `{"trends": [{"title": ..., "source": ..., "score": ...}, ...]}`.
   - If the script fails or returns empty data, note the failure and continue with whatever partial data is available.
2. Rank items by relevance to the user's interests (check `vault/20-Areas/` for context).
3. Write the result to `vault/30-Reports/trend-scan-{YYYY-MM-DD}.md` with:
   - A summary line at the top.
   - Numbered list of trends with source attribution.
   - `[[wikilinks]]` to any recurring topics found in existing vault notes.
4. Return the top 3 inline to the user.
