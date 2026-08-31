"""Regex gate that runs before any API call.

Every email this rejects is an extraction we don't pay for. Gmail's server-side
query already narrows the set, but it still returns plenty of marketing mail
that merely contains the word "subscription".

Deliberately biased toward letting things through: a false positive costs one
extraction (fractions of a cent), a false negative means a missed subscription.
"""

import re

# Strong signals — a real charge notice almost always has one of these.
_BILLING_PHRASES = re.compile(
    r"\b("
    r"receipt|invoice|payment\s+(received|confirmation|successful)|"
    r"your\s+order|billed|we\s+charged|has\s+been\s+charged|charged\s+to|"
    r"subscription\s+(renew|confirm|start|updat)|auto[-\s]?renew|"
    r"renews?\s+on|next\s+billing|billing\s+(date|cycle|statement)|"
    r"membership\s+(renew|fee)|plan\s+renew"
    r")",
    re.I,
)

# A currency amount. Covers $12.99, AUD 12.99, 12.99 USD, £9, €10,50.
_AMOUNT = re.compile(
    r"(?:[$£€¥]\s?\d[\d,]*(?:[.,]\d{2})?)"
    r"|(?:\b(?:AUD|USD|EUR|GBP|NZD|INR|CAD)\s?\d[\d,]*(?:[.,]\d{2})?)"
    r"|(?:\b\d[\d,]*[.,]\d{2}\s?(?:AUD|USD|EUR|GBP|NZD|INR|CAD)\b)",
    re.I,
)

# Senders that are essentially always transactional.
_BILLING_SENDERS = re.compile(
    r"(billing|invoice|receipt|payments?|no-?reply@.*(pay|bill))",
    re.I,
)

# Hard rejects — marketing that often name-drops billing words.
_MARKETING = re.compile(
    r"\b("
    r"unsubscribe\s+from\s+(these|our)\s+(emails?|updates?)|"
    r"\d+%\s+off|save\s+\d+%|limited\s+time|flash\s+sale|"
    r"black\s+friday|cyber\s+monday|"
    r"upgrade\s+now|try\s+.{0,20}\s+free|start\s+your\s+free\s+trial|"
    r"newsletter|webinar|last\s+chance"
    r")",
    re.I,
)

# Never subscriptions, regardless of other signals.
_NON_SUBSCRIPTION = re.compile(
    r"\b("
    r"password\s+reset|verify\s+your\s+email|security\s+alert|"
    r"sign[-\s]?in\s+(attempt|from)|two[-\s]?factor|"
    r"shipping\s+confirmation|out\s+for\s+delivery|has\s+shipped|"
    r"appointment|calendar\s+invit"
    r")",
    re.I,
)


def check(email: dict) -> tuple[bool, str]:
    """Decide whether an email is worth spending an extraction on.

    Returns (should_extract, reason). The reason is stored in the scan log
    so rejections stay auditable — if the tracker misses a subscription you
    can query the log and see exactly which rule dropped it.
    """
    subject = email.get("subject") or ""
    sender = email.get("sender") or ""
    body = email.get("body") or ""
    haystack = f"{subject}\n{body}"

    if _NON_SUBSCRIPTION.search(haystack):
        return False, "non_subscription_transactional"

    has_amount = bool(_AMOUNT.search(haystack))
    has_billing = bool(_BILLING_PHRASES.search(haystack))
    from_billing_sender = bool(_BILLING_SENDERS.search(sender))

    # Marketing mail only gets rejected when it lacks the transactional pair.
    # A genuine receipt with a promo footer still has both an amount and a
    # billing phrase, so it survives.
    if _MARKETING.search(haystack) and not (has_amount and has_billing):
        return False, "marketing"

    if has_amount and has_billing:
        return True, "amount+billing_phrase"
    if from_billing_sender and has_amount:
        return True, "billing_sender+amount"
    if has_billing and from_billing_sender:
        return True, "billing_sender+billing_phrase"

    if not has_amount and not has_billing:
        return False, "no_billing_signal"
    if not has_amount:
        return False, "no_amount"
    return False, "amount_only"


# Gmail server-side query for the initial backfill. Narrows what we download;
# check() then narrows what we pay to extract.
GMAIL_QUERY = (
    "(receipt OR invoice OR renewal OR subscription OR billing OR "
    '"payment received" OR "your order") -in:spam -in:trash'
)


if __name__ == "__main__":
    from subs import fixtures

    print(f"{'VERDICT':<8} {'REASON':<34} SUBJECT")
    print("-" * 90)
    for e in fixtures.SAMPLE_EMAILS:
        ok, reason = check(e)
        print(f"{'PASS' if ok else 'SKIP':<8} {reason:<34} {e['subject'][:44]}")
