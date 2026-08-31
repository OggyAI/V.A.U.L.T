"""Claude-backed extraction of subscription facts from an email.

Three cost controls, in order of impact:

1. prefilter.check() runs first — most emails never reach this module.
2. The system prompt + schema is a cached prefix (`cache_control`), so the
   instructions are billed at ~0.1x on every call after the first. It is
   written long enough to clear Opus 5's 512-token minimum cacheable prefix;
   trimming it below that silently disables caching.
3. extract_batch() uses the Batch API for backfills — 50% off, results
   typically within the hour. Use it for the initial 12-month scan; use
   extract_one() for incremental syncs where latency matters.

Output shape is enforced by the API via output_config.format, so malformed
JSON is not a failure mode we have to handle.
"""

import json
import os
import time

MODEL = "claude-opus-5"
MAX_TOKENS = 1024  # the JSON payload is tiny; no need for headroom

CATEGORIES = [
    "streaming", "software", "gaming", "music", "news", "fitness",
    "cloud_storage", "productivity", "education", "finance",
    "shopping", "utilities", "other",
]

BILLING_CYCLES = ["weekly", "monthly", "quarterly", "yearly", "unknown"]

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "is_subscription": {
            "type": "boolean",
            "description": "True only for a recurring charge. False for one-off purchases, "
                           "shipping notices, marketing, free trials with no charge, and refunds.",
        },
        "merchant_name": {
            "type": "string",
            "description": "Canonical merchant name, e.g. 'Netflix', 'Adobe', 'GitHub'. "
                           "Not the product tier. Empty string when is_subscription is false.",
        },
        "category": {"type": "string", "enum": CATEGORIES},
        "amount": {
            "anyOf": [{"type": "number"}, {"type": "null"}],
            "description": "The recurring charge amount as a number, no currency symbol. "
                           "Null if no amount is stated.",
        },
        "currency": {
            "type": "string",
            "description": "ISO 4217 code, e.g. AUD, USD, EUR. Infer from the symbol and "
                           "context when not stated explicitly.",
        },
        "billing_cycle": {"type": "string", "enum": BILLING_CYCLES},
        "next_renewal_date": {
            "anyOf": [{"type": "string", "format": "date"}, {"type": "null"}],
            "description": "Next charge date as YYYY-MM-DD. Null if not stated. "
                           "Do not compute it from the billing cycle — only report a date "
                           "the email actually gives.",
        },
        "confidence": {
            "type": "number",
            "description": "0.0-1.0. How certain that this is a recurring subscription AND "
                           "that the extracted fields are correct.",
        },
    },
    "required": [
        "is_subscription", "merchant_name", "category", "amount",
        "currency", "billing_cycle", "next_renewal_date", "confidence",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You extract subscription billing facts from emails.

You will be given the sender, subject, and body of a single email. Decide \
whether it documents a RECURRING subscription charge, and if so, extract the \
billing details. Return only the structured object — no commentary.

## What counts as a subscription

A subscription is a charge that repeats on a schedule without the customer \
re-purchasing each time: streaming services, SaaS seats, cloud storage, \
memberships, recurring donations, insurance premiums.

These are NOT subscriptions, and must return is_subscription: false:
- One-off purchases, even from a merchant that also sells subscriptions.
- Shipping and delivery notifications.
- Marketing, promotional offers, and upgrade pitches.
- Free trial confirmations where no money has been or will imminently be charged.
- Refunds, chargebacks, and failed-payment notices.
- Account security mail, password resets, and login alerts.
- Invoices you issued to someone else, rather than were charged.

## Extraction rules

**merchant_name** — the company, in its canonical short form. "Netflix", not \
"Netflix Australia Pty Ltd" and not "Netflix Standard with ads". Strip legal \
suffixes, plan names, and tiers. This field is used to detect repeat charges \
across months, so it must be stable: the same service must always produce the \
same string.

**amount** — the recurring charge only, as a bare number. Exclude one-off \
setup fees, shipping, and account credits. If the email shows both a \
pre-discount and a charged amount, report what was actually charged. If tax is \
shown separately, report the total the customer paid. If several currencies \
appear, report the one actually billed.

**currency** — the ISO 4217 code for the amount you reported. Infer it when \
only a symbol appears: a bare "$" alongside Australian context is AUD, \
alongside US context is USD. When genuinely ambiguous, prefer the currency \
named nearest the amount.

**billing_cycle** — how often the charge repeats. An annual plan billed in \
monthly instalments is "monthly", because that is the charge cadence. Use \
"unknown" rather than guessing when the email does not say.

**next_renewal_date** — only a date the email states, normalized to \
YYYY-MM-DD. Never derive it by adding a cycle length to the charge date. \
Resolve relative phrasing ("renews in 30 days") only when the email also gives \
the reference date. Otherwise null.

**confidence** — your certainty that this is a recurring charge AND that the \
fields above are right. Be honest and well calibrated; a low score routes the \
row to a human review queue, which is the correct outcome for a genuinely \
ambiguous email. Use below 0.7 when the email is unclear, the amount is \
uncertain, or you had to infer heavily. Use above 0.9 only for an unambiguous \
receipt stating merchant, amount, and cadence plainly.

When is_subscription is false, set merchant_name to an empty string, amount \
and next_renewal_date to null, category to "other", billing_cycle to \
"unknown", and confidence to your certainty that it is NOT a subscription."""


class ExtractionUnavailable(RuntimeError):
    """Raised when the Anthropic client or API key is missing."""


def _client():
    try:
        import anthropic
    except ImportError as e:
        raise ExtractionUnavailable(
            "anthropic package not installed - run: pip install anthropic"
        ) from e

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ExtractionUnavailable(
            "ANTHROPIC_API_KEY is not set - add it to .env (see HANDOFF.md step 5)"
        )
    return anthropic.Anthropic()


def _system_blocks() -> list[dict]:
    """System prompt as a cached prefix.

    The breakpoint sits on the last (only) system block, so both it and the
    tool-free request prefix cache together. Every extraction after the first
    reads it at ~0.1x input cost.
    """
    return [{
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
    }]


def _user_content(email: dict) -> str:
    body = (email.get("body") or "")[:6000]  # long footers add cost, not signal
    return (
        f"From: {email.get('sender', '')}\n"
        f"Subject: {email.get('subject', '')}\n"
        f"Received: {email.get('received_at', '')}\n\n"
        f"{body}"
    )


def _request_params(email: dict) -> dict:
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": _system_blocks(),
        # effort "low": classification against a fixed schema is not a
        # reasoning-heavy task, and low keeps per-email cost and latency down.
        "output_config": {
            "effort": "low",
            "format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA},
        },
        "messages": [{"role": "user", "content": _user_content(email)}],
    }


def _parse(response) -> dict:
    """output_config.format guarantees the first text block is valid JSON."""
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def extract_one(email: dict) -> dict:
    """Extract from a single email. Use for incremental syncs."""
    client = _client()
    response = client.messages.create(**_request_params(email))
    if response.stop_reason == "refusal":
        return {
            "is_subscription": False,
            "merchant_name": "",
            "category": "other",
            "amount": None,
            "currency": "",
            "billing_cycle": "unknown",
            "next_renewal_date": None,
            "confidence": 0.0,
            "_refused": True,
        }
    return _parse(response)


def extract_batch(emails: list[dict], poll_seconds: int = 30,
                  timeout_seconds: int = 86400) -> dict[str, dict]:
    """Extract from many emails via the Batch API — 50% cheaper.

    Returns {email_id: extraction}. Use for the initial backfill; most batches
    finish within the hour, and the caller can safely be a long-running script.
    """
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    client = _client()

    requests = [
        Request(
            custom_id=str(e["id"]),
            params=MessageCreateParamsNonStreaming(**_request_params(e)),
        )
        for e in emails
    ]

    batch = client.messages.batches.create(requests=requests)
    print(f"[extract] Batch {batch.id} submitted with {len(requests)} emails.")

    waited = 0
    while True:
        batch = client.messages.batches.retrieve(batch.id)
        if batch.processing_status == "ended":
            break
        if waited >= timeout_seconds:
            raise TimeoutError(f"Batch {batch.id} still running after {waited}s")
        time.sleep(poll_seconds)
        waited += poll_seconds
        print(f"[extract] ...{waited}s, status={batch.processing_status}")

    results: dict[str, dict] = {}
    for result in client.messages.batches.results(batch.id):
        # Results arrive in arbitrary order — key by custom_id, never position.
        if result.result.type == "succeeded":
            msg = result.result.message
            if msg.stop_reason == "refusal":
                continue
            try:
                results[result.custom_id] = _parse(msg)
            except (StopIteration, json.JSONDecodeError):
                continue
        else:
            print(f"[extract] {result.custom_id}: {result.result.type}")

    return results


def estimate_cost(emails: list[dict], batched: bool = True) -> dict:
    """Rough pre-flight cost estimate, so a big backfill holds no surprises.

    Deliberately ignores the caching discount on the system prefix, so the
    real bill comes in under this rather than over.
    """
    # Opus 5: $5 / $25 per million tokens. ~4 chars per token.
    in_per_m, out_per_m = 5.0, 25.0
    system_tokens = len(SYSTEM_PROMPT) // 4
    body_tokens = sum(len(_user_content(e)) // 4 for e in emails)
    input_tokens = system_tokens * len(emails) + body_tokens
    output_tokens = 150 * len(emails)

    cost = (input_tokens / 1_000_000 * in_per_m) + (output_tokens / 1_000_000 * out_per_m)
    if batched:
        cost *= 0.5

    return {
        "emails": len(emails),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "usd_upper_bound": round(cost, 2),
        "batched": batched,
    }


if __name__ == "__main__":
    from subs import fixtures, prefilter

    candidates = [e for e in fixtures.SAMPLE_EMAILS if prefilter.check(e)[0]]
    print(json.dumps(estimate_cost(candidates), indent=2))
