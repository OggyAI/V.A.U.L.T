---
name: deep-research
description: >
  Research a topic thoroughly using web search and return a sourced summary.
  Use for any research-heavy task that would pollute the main context window:
  competitor analysis, technology comparison, background reading, literature
  review, or "find out everything about X".
context: fork
agent: Explore
---

Research $ARGUMENTS thoroughly:

1. Search the web for authoritative sources (docs, papers, reputable articles).
2. Read and cross-reference at least 3 sources.
3. Return a ranked summary with:
   - Key findings (bulleted).
   - Source URLs with one-line descriptions.
   - Confidence level for each finding.
4. Do NOT edit any files — return the summary to the main thread.
