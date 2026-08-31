"""SQLite store for the subscription tracker.

Schema follows the build spec, minus the multi-tenant columns: this is a
single-user local database, so `user_id` / `auth.users` foreign keys are gone.
Everything else — the scan log for auditability, confidence-gated review,
fingerprint dedupe — is kept as specified.

The DB lives at subs.db in the project root (gitignored).
"""

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "subs.db"

DEFAULT_CURRENCY = "AUD"

# Below this, an extraction is not trusted and lands in the review queue
# instead of being treated as a confirmed subscription.
CONFIDENCE_THRESHOLD = 0.7

SCHEMA = """
CREATE TABLE IF NOT EXISTS email_scan_log (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_message_id   TEXT NOT NULL UNIQUE,
    gmail_thread_id    TEXT,
    received_at        TEXT,
    sender             TEXT,
    subject            TEXT,
    extraction_status  TEXT NOT NULL DEFAULT 'pending',
    extraction_raw     TEXT,
    skip_reason        TEXT,
    processed_at       TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_name         TEXT NOT NULL,
    category              TEXT,
    amount                REAL,
    currency              TEXT NOT NULL DEFAULT 'AUD',
    billing_cycle         TEXT,
    next_renewal_date     TEXT,
    status                TEXT NOT NULL DEFAULT 'active',
    confidence            REAL,
    source_email_id       INTEGER REFERENCES email_scan_log(id),
    merchant_fingerprint  TEXT NOT NULL,
    notes                 TEXT,
    created_at            TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_subs_fingerprint
    ON subscriptions(merchant_fingerprint);

CREATE TABLE IF NOT EXISTS alerts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id  INTEGER REFERENCES subscriptions(id),
    alert_type       TEXT,
    alert_date       TEXT,
    sent             INTEGER NOT NULL DEFAULT 0,
    sent_at          TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_unique
    ON alerts(subscription_id, alert_type, alert_date);

-- Gmail historyId and other sync bookkeeping. Key/value so it can grow
-- without a migration.
CREATE TABLE IF NOT EXISTS sync_state (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open the database, creating the schema if needed."""
    path = Path(db_path) if db_path else DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection):
    """Additive column migrations for databases created by earlier versions."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(subscriptions)")}

    # When this subscription was last seen being charged. Distinct from
    # updated_at (touched by any edit) and from source_email_id (overwritten
    # on every upsert regardless of the email's date).
    if "last_charge_seen" not in cols:
        conn.execute("ALTER TABLE subscriptions ADD COLUMN last_charge_seen TEXT")
        conn.commit()


# ── Sync state ───────────────────────────────────────────

def get_state(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_state(conn: sqlite3.Connection, key: str, value: str):
    conn.execute(
        """INSERT INTO sync_state (key, value, updated_at)
           VALUES (?, ?, datetime('now'))
           ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                          updated_at = datetime('now')""",
        (key, value),
    )
    conn.commit()


# ── Scan log ─────────────────────────────────────────────

def already_scanned(conn: sqlite3.Connection, gmail_message_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM email_scan_log WHERE gmail_message_id = ?", (gmail_message_id,)
    ).fetchone()
    return row is not None


def log_email(conn: sqlite3.Connection, email: dict, status: str = "pending",
              skip_reason: str | None = None) -> int:
    """Record an inspected email. Returns its scan-log row id."""
    cur = conn.execute(
        """INSERT INTO email_scan_log
               (gmail_message_id, gmail_thread_id, received_at, sender,
                subject, extraction_status, skip_reason)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(gmail_message_id) DO UPDATE SET
               extraction_status = excluded.extraction_status,
               skip_reason = excluded.skip_reason""",
        (
            email.get("id"),
            email.get("thread_id"),
            email.get("received_at"),
            email.get("sender"),
            email.get("subject"),
            status,
            skip_reason,
        ),
    )
    conn.commit()

    if cur.lastrowid:
        return cur.lastrowid
    row = conn.execute(
        "SELECT id FROM email_scan_log WHERE gmail_message_id = ?", (email.get("id"),)
    ).fetchone()
    return row["id"]


def mark_scanned(conn: sqlite3.Connection, scan_id: int, status: str,
                 raw: dict | None = None):
    conn.execute(
        """UPDATE email_scan_log
              SET extraction_status = ?, extraction_raw = ?, processed_at = datetime('now')
            WHERE id = ?""",
        (status, json.dumps(raw) if raw is not None else None, scan_id),
    )
    conn.commit()


# ── Subscriptions ────────────────────────────────────────

def fingerprint(merchant_name: str, amount: float | None) -> str:
    """Normalized merchant+amount key used to match repeat charges.

    Rounding to whole units keeps small price drift (tax changes, FX) from
    creating a duplicate row for what is clearly the same subscription.
    """
    merchant = (merchant_name or "").strip().lower()
    if amount is None:
        return f"{merchant}|?"
    return f"{merchant}|{round(float(amount))}"


def upsert_subscription(conn: sqlite3.Connection, data: dict,
                        source_email_id: int | None = None,
                        received_at: str | None = None) -> tuple[int, bool]:
    """Insert or update by fingerprint. Returns (row id, was_new).

    On a fingerprint hit we refresh the renewal date, amount, and confidence
    rather than creating a second row — a monthly receipt arriving every month
    should update one subscription, not accumulate twelve.
    """
    fp = fingerprint(data.get("merchant_name"), data.get("amount"))
    confidence = float(data.get("confidence") or 0.0)
    status = "active" if confidence >= CONFIDENCE_THRESHOLD else "needs_review"

    existing = conn.execute(
        "SELECT id, status FROM subscriptions WHERE merchant_fingerprint = ?", (fp,)
    ).fetchone()

    if existing:
        # Don't silently flip something the user already confirmed or cancelled
        # back to needs_review on a later low-confidence sighting.
        keep_status = existing["status"] if existing["status"] in ("cancelled", "paused", "active") else status
        conn.execute(
            """UPDATE subscriptions
                  SET amount = COALESCE(?, amount),
                      currency = COALESCE(?, currency),
                      billing_cycle = COALESCE(?, billing_cycle),
                      next_renewal_date = COALESCE(?, next_renewal_date),
                      category = COALESCE(?, category),
                      confidence = ?,
                      status = ?,
                      source_email_id = COALESCE(?, source_email_id),
                      -- MAX, not overwrite: batch results arrive in arbitrary
                      -- order, so a later upsert may carry an older email.
                      last_charge_seen = MAX(
                          COALESCE(?, ''), COALESCE(last_charge_seen, '')
                      ),
                      updated_at = datetime('now')
                WHERE id = ?""",
            (
                data.get("amount"),
                data.get("currency"),
                data.get("billing_cycle"),
                data.get("next_renewal_date"),
                data.get("category"),
                confidence,
                keep_status,
                source_email_id,
                received_at,
                existing["id"],
            ),
        )
        conn.commit()
        return existing["id"], False

    cur = conn.execute(
        """INSERT INTO subscriptions
               (merchant_name, category, amount, currency, billing_cycle,
                next_renewal_date, status, confidence, source_email_id,
                merchant_fingerprint, last_charge_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data.get("merchant_name"),
            data.get("category"),
            data.get("amount"),
            data.get("currency") or DEFAULT_CURRENCY,
            data.get("billing_cycle"),
            data.get("next_renewal_date"),
            status,
            confidence,
            source_email_id,
            fp,
            received_at,
        ),
    )
    conn.commit()
    return cur.lastrowid, True


def list_subscriptions(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM subscriptions"
    params: tuple = ()
    if status:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY next_renewal_date IS NULL, next_renewal_date, merchant_name"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def set_status(conn: sqlite3.Connection, sub_id: int, status: str):
    conn.execute(
        "UPDATE subscriptions SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (status, sub_id),
    )
    conn.commit()


# ── Derived figures ──────────────────────────────────────

_CYCLE_MONTHLY_FACTOR = {
    "weekly": 52 / 12,
    "monthly": 1.0,
    "quarterly": 1 / 3,
    "yearly": 1 / 12,
    "annual": 1 / 12,
}


def monthly_equivalent(amount: float | None, billing_cycle: str | None) -> float:
    """Normalize any billing cycle to a monthly figure."""
    if not amount:
        return 0.0
    factor = _CYCLE_MONTHLY_FACTOR.get((billing_cycle or "").strip().lower())
    if factor is None:
        return 0.0  # unknown cycle — excluded rather than guessed
    return float(amount) * factor


def totals(conn: sqlite3.Connection) -> dict:
    """Monthly and yearly spend, broken out per currency.

    Amounts are NOT converted between currencies — that would need a live FX
    rate, and a wrong rate silently misstates the number the user is here to
    read. Totals are reported per currency and the caller decides how to
    present them.
    """
    active = list_subscriptions(conn, status="active")

    by_currency: dict[str, float] = {}
    unknown_cycle = 0
    for s in active:
        cycle = (s["billing_cycle"] or "").strip().lower()
        if cycle not in _CYCLE_MONTHLY_FACTOR:
            unknown_cycle += 1
            continue
        code = (s["currency"] or DEFAULT_CURRENCY).strip().upper()
        by_currency[code] = by_currency.get(code, 0.0) + monthly_equivalent(
            s["amount"], s["billing_cycle"]
        )

    monthly = {c: round(v, 2) for c, v in sorted(by_currency.items())}
    yearly = {c: round(v * 12, 2) for c, v in monthly.items()}

    return {
        "monthly": monthly,
        "yearly": yearly,
        "currencies": list(monthly.keys()),
        "mixed_currency": len(monthly) > 1,
        "active_count": len(active),
        "needs_review_count": len(list_subscriptions(conn, status="needs_review")),
        "excluded_unknown_cycle": unknown_cycle,
    }


def format_totals(totals_dict: dict, period: str = "monthly") -> str:
    """Render per-currency totals as a single display string."""
    amounts = totals_dict.get(period) or {}
    if not amounts:
        return "0.00"
    return " + ".join(f"{code} {value:,.2f}" for code, value in amounts.items())


_CYCLE_DAYS = {
    "weekly": 7, "monthly": 31, "quarterly": 92,
    "yearly": 366, "annual": 366,
}

# How many billing cycles of silence before a subscription is called stale.
# Two, not one: a single missed or unparsed receipt is common, two in a row
# much less so.
STALE_CYCLES = 2


def stale_subscriptions(conn: sqlite3.Connection, cycles: int = STALE_CYCLES) -> list[dict]:
    """Active subscriptions with no charge seen for N+ billing cycles.

    A cancelled plan does not announce itself — it simply stops producing
    receipts. This flags that silence for review; it never cancels anything
    automatically, because a vendor changing its receipt format looks
    identical to a cancellation from here.

    Unknown billing cycles are skipped: with no cadence there is no way to
    tell late from silent.
    """
    out = []
    for sub in list_subscriptions(conn, status="active"):
        cycle = (sub["billing_cycle"] or "").strip().lower()
        period = _CYCLE_DAYS.get(cycle)
        if not period or not sub["last_charge_seen"]:
            continue

        row = conn.execute(
            "SELECT julianday('now') - julianday(?) AS age", (sub["last_charge_seen"],)
        ).fetchone()
        age = row["age"]
        if age is None:
            continue

        threshold = period * cycles
        if age > threshold:
            out.append({
                **sub,
                "days_since_charge": int(age),
                "cycles_missed": round(age / period, 1),
            })

    return sorted(out, key=lambda s: s["days_since_charge"], reverse=True)


def backfill_last_charge_seen(conn: sqlite3.Connection) -> int:
    """Populate last_charge_seen for rows created before the column existed.

    Recomputed from the scan log rather than from source_email_id, which is
    overwritten on every upsert and therefore does not identify the most
    recent charge.
    """
    import json as _json

    latest: dict[str, str] = {}
    for row in conn.execute(
        """SELECT received_at, extraction_raw FROM email_scan_log
            WHERE extraction_status = 'parsed' AND extraction_raw IS NOT NULL"""
    ):
        try:
            data = _json.loads(row["extraction_raw"])
        except (ValueError, TypeError):
            continue
        if not data.get("is_subscription"):
            continue
        fp = fingerprint(data.get("merchant_name"), data.get("amount"))
        received = row["received_at"] or ""
        if received > latest.get(fp, ""):
            latest[fp] = received

    updated = 0
    for fp, received in latest.items():
        cur = conn.execute(
            """UPDATE subscriptions
                  SET last_charge_seen = ?
                WHERE merchant_fingerprint = ?
                  AND (last_charge_seen IS NULL OR last_charge_seen < ?)""",
            (received, fp, received),
        )
        updated += cur.rowcount
    conn.commit()
    return updated


def upcoming_renewals(conn: sqlite3.Connection, within_days: int = 14) -> list[dict]:
    """Active subscriptions renewing within N days, soonest first."""
    today = date.today()
    out = []
    for s in list_subscriptions(conn, status="active"):
        if not s["next_renewal_date"]:
            continue
        try:
            due = datetime.strptime(s["next_renewal_date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        days = (due - today).days
        if 0 <= days <= within_days:
            out.append({**s, "days_until": days})
    return sorted(out, key=lambda s: s["days_until"])
