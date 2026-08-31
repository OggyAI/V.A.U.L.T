"""Sample emails so the whole pipeline runs before Gmail is connected.

Shapes match what gmail.fetch_messages() returns, so `--source fixtures` and
`--source gmail` exercise identical code downstream.

Deliberately mixed: monthly and annual subscriptions, a price change, a
duplicate-category pair, plus decoys the prefilter should reject.
"""

SAMPLE_EMAILS = [
    {
        "id": "fixture-001",
        "thread_id": "t-001",
        "received_at": "2026-07-02T08:14:00Z",
        "sender": "Netflix <info@mailer.netflix.com>",
        "subject": "Your Netflix membership",
        "body": (
            "Hi,\n\nYour Netflix membership fee of $22.99 was charged on 2 July 2026 "
            "to your Visa ending 4242. Your next billing date is 2 August 2026.\n\n"
            "Plan: Standard with ads\n\nThe Netflix Team"
        ),
    },
    {
        "id": "fixture-002",
        "thread_id": "t-002",
        "received_at": "2026-07-05T11:02:00Z",
        "sender": "Spotify <no-reply@spotify.com>",
        "subject": "Your Spotify Premium receipt",
        "body": (
            "Receipt for Spotify Premium Individual\n\n"
            "Amount: AUD 13.99\nDate: 5 July 2026\n"
            "Your subscription renews on 5 August 2026.\n\n"
            "Manage your plan in Account Settings."
        ),
    },
    {
        "id": "fixture-003",
        "thread_id": "t-003",
        "received_at": "2026-06-28T02:30:00Z",
        "sender": "Adobe <billing@adobe.com>",
        "subject": "Invoice for your Creative Cloud subscription",
        "body": (
            "Invoice #AD-88213\n\nCreative Cloud All Apps — annual plan, paid monthly\n"
            "Amount due: $87.99 AUD\n"
            "Billing period: 28 Jun 2026 – 27 Jul 2026\n"
            "Auto-renews 28 July 2026."
        ),
    },
    {
        "id": "fixture-004",
        "thread_id": "t-004",
        "received_at": "2026-03-15T19:45:00Z",
        "sender": "GitHub <billing@github.com>",
        "subject": "Payment receipt for GitHub Copilot",
        "body": (
            "Thanks for your payment.\n\nGitHub Copilot Individual — yearly\n"
            "USD 100.00 charged on March 15, 2026.\n"
            "Your plan renews on March 15, 2027."
        ),
    },
    {
        "id": "fixture-005",
        "thread_id": "t-005",
        "received_at": "2026-07-08T06:00:00Z",
        "sender": "Notion <team@makenotion.com>",
        "subject": "Your Notion Plus plan has been renewed",
        "body": (
            "Your Notion Plus subscription was renewed.\n\n"
            "Charged: $11.00 USD per member / month\n"
            "Next billing date: August 8, 2026"
        ),
    },
    {
        "id": "fixture-006",
        "thread_id": "t-006",
        "received_at": "2026-07-09T09:20:00Z",
        "sender": "Obsidian <sync@obsidian.md>",
        "subject": "Obsidian Sync — payment confirmation",
        "body": (
            "Payment received for Obsidian Sync.\n\n"
            "$4.00 USD billed monthly. Next billing 9 August 2026."
        ),
    },
    # Same category as Notion — should surface in duplicate detection.
    {
        "id": "fixture-007",
        "thread_id": "t-007",
        "received_at": "2026-07-11T13:10:00Z",
        "sender": "Evernote <billing@evernote.com>",
        "subject": "Your Evernote Personal receipt",
        "body": (
            "Receipt — Evernote Personal\nAUD 10.99 charged 11 July 2026.\n"
            "Subscription renews on 11 August 2026."
        ),
    },
    # ── Decoys the prefilter should reject ──────────────────
    {
        "id": "fixture-008",
        "thread_id": "t-008",
        "received_at": "2026-07-10T15:00:00Z",
        "sender": "Figma <hello@figma.com>",
        "subject": "Upgrade now and save 30% on your first year",
        "body": (
            "Limited time: save 30% when you upgrade to Figma Professional. "
            "Try it free for 14 days. Unsubscribe from these emails anytime."
        ),
    },
    {
        "id": "fixture-009",
        "thread_id": "t-009",
        "received_at": "2026-07-10T21:33:00Z",
        "sender": "Google <no-reply@accounts.google.com>",
        "subject": "Security alert: new sign-in from Windows",
        "body": "We detected a new sign-in attempt to your Google Account.",
    },
    {
        "id": "fixture-010",
        "thread_id": "t-010",
        "received_at": "2026-07-12T10:05:00Z",
        "sender": "Amazon <shipment-tracking@amazon.com.au>",
        "subject": "Your order has shipped",
        "body": "Your package is out for delivery. Order total was $34.50.",
    },
]


def fetch_messages(limit: int | None = None, **_ignored) -> list[dict]:
    """Mirror of gmail.fetch_messages(), backed by the samples above."""
    return SAMPLE_EMAILS[:limit] if limit else list(SAMPLE_EMAILS)


def commit_state():
    """No-op — fixtures keep no sync state. Mirrors gmail.commit_state()."""
