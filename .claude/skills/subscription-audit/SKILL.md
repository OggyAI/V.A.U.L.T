---
name: subscription-audit
description: >
  Report what recurring subscriptions are being paid for, total monthly and
  yearly spend, upcoming renewals, and overlapping services. Use when the user
  says "what am I paying for", "my subscriptions", "subscription audit",
  "recurring charges", "what's renewing", "am I paying for anything twice",
  "cancel suggestions", or asks about monthly spend on services.
allowed-tools: Read, Write, Bash, Grep, Glob
---

# Subscription Audit

Reads the local tracker database and reports on recurring spend. Read-only with
respect to the user's accounts — this reports and recommends, it never cancels
anything.

## Steps

1. Refresh the data if the user asked for a scan ("check my email for new
   subscriptions"), otherwise skip to step 2:
   ```
   python -m subs.cli sync --source gmail
   ```
   If that reports Gmail isn't configured, say so and point at HANDOFF.md
   step 10. Fall back to reporting on existing data rather than stopping.

2. Read the current state:
   ```
   python -m subs.cli list
   ```

3. Write the report:
   ```
   python -m subs.cli report
   ```
   This writes `vault/30-Reports/subscriptions-{YYYY-MM-DD}.md` with
   `[[wikilinks]]`. Confirm the path back to the user.

4. Summarize inline, in this order:
   - **Total spend** — monthly and yearly. If several currencies are present,
     report each separately; they are deliberately not converted.
   - **Renewing soon** — anything within 7 days, with the amount.
   - **Overlap** — categories with more than one active service.
   - **Needs review** — count of low-confidence extractions, if any.

## Rules

- **Never suggest that VAULT cancel a subscription.** Recommending that the
  user cancel something is fine and useful; taking the action is not. If asked
  to cancel, explain that they need to do it through the vendor, and give the
  merchant name and renewal date so they can act before the next charge.
- Do not report a combined total across currencies. `AUD 135.96 + USD 23.33` is
  correct; adding them into one number is not.
- Subscriptions with an unknown billing cycle are excluded from totals. If any
  exist, say how many rather than letting the total look complete.
- If confidence is below 0.7 the row is in the review queue, not the active
  set — describe those as unconfirmed, not as spend.
