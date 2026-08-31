"""Orchestrator: fetch -> prefilter -> extract -> upsert -> alerts.

Every email that gets fetched is written to email_scan_log regardless of what
happens next, so a missed subscription can always be traced to the stage that
dropped it.
"""

from datetime import date, timedelta

from subs import db, extract, prefilter

RENEWAL_ALERT_DAYS = 7


def _source_module(source: str):
    if source == "fixtures":
        from subs import fixtures
        return fixtures
    if source == "gmail":
        from subs import gmail
        return gmail
    raise ValueError(f"Unknown source: {source!r} (use 'fixtures' or 'gmail')")


def run(source: str = "fixtures", limit: int | None = None,
        batched: bool = True, dry_run: bool = False,
        months: int = 12, db_path=None) -> dict:
    """Run one sync pass. Returns a summary dict."""
    conn = db.connect(db_path)
    mod = _source_module(source)

    print(f"[sync] Fetching from {source}...")
    emails = mod.fetch_messages(limit=limit, months=months)
    print(f"[sync] {len(emails)} emails fetched.")

    fresh, skipped_seen = [], 0
    for e in emails:
        if db.already_scanned(conn, e["id"]):
            skipped_seen += 1
            continue
        fresh.append(e)

    candidates, rejected = [], 0
    for e in fresh:
        should, reason = prefilter.check(e)
        if should:
            candidates.append(e)
        else:
            # Also skipped on a dry run — writing rows would mark these
            # "already scanned" and hide them from the real sync.
            if not dry_run:
                db.log_email(conn, e, status="not_subscription", skip_reason=reason)
            rejected += 1

    print(f"[sync] {skipped_seen} already scanned, {rejected} filtered out, "
          f"{len(candidates)} to extract.")

    if not candidates:
        return _summary(conn, extracted=0, new=0, updated=0,
                        rejected=rejected, skipped_seen=skipped_seen)

    est = extract.estimate_cost(candidates, batched=batched)
    print(f"[sync] Estimated cost: <= ${est['usd_upper_bound']} "
          f"({'batched' if batched else 'live'})")

    if dry_run:
        print("[sync] Dry run - no API calls made, nothing written.")
        return _summary(conn, extracted=0, new=0, updated=0,
                        rejected=rejected, skipped_seen=skipped_seen,
                        dry_run=True, estimate=est)

    # Batch for anything sizeable; live calls when it's a handful.
    if batched and len(candidates) > 5:
        extractions = extract.extract_batch(candidates)
    else:
        extractions = {}
        for i, e in enumerate(candidates, 1):
            print(f"[sync] Extracting {i}/{len(candidates)}: {e['subject'][:50]}")
            extractions[str(e["id"])] = extract.extract_one(e)

    new_count = updated_count = 0
    for e in candidates:
        data = extractions.get(str(e["id"]))
        if data is None:
            db.log_email(conn, e, status="error", skip_reason="no_extraction_returned")
            continue

        scan_id = db.log_email(conn, e, status="pending")

        if not data.get("is_subscription"):
            db.mark_scanned(conn, scan_id, "not_subscription", raw=data)
            continue

        _, was_new = db.upsert_subscription(
            conn, data, source_email_id=scan_id, received_at=e.get("received_at")
        )
        db.mark_scanned(conn, scan_id, "parsed", raw=data)
        new_count += was_new
        updated_count += not was_new

    generate_alerts(conn)

    # Only now — every fetched email has been extracted and stored, so it is
    # safe to advance the sync cursor. A crash anywhere above leaves it alone
    # and the next run re-fetches this window.
    mod.commit_state()

    return _summary(conn, extracted=len(extractions), new=new_count,
                    updated=updated_count, rejected=rejected,
                    skipped_seen=skipped_seen)


def _summary(conn, **kwargs) -> dict:
    return {**kwargs, "totals": db.totals(conn)}


def generate_alerts(conn, within_days: int = RENEWAL_ALERT_DAYS) -> int:
    """Queue renewal alerts. The UNIQUE index makes this idempotent."""
    created = 0
    for sub in db.upcoming_renewals(conn, within_days=within_days):
        cur = conn.execute(
            """INSERT OR IGNORE INTO alerts (subscription_id, alert_type, alert_date)
               VALUES (?, 'renewal_upcoming', ?)""",
            (sub["id"], sub["next_renewal_date"]),
        )
        created += cur.rowcount
    conn.commit()
    return created


def find_duplicates(conn) -> list[dict]:
    """Active subscriptions sharing a category — candidates for cleanup.

    Category overlap is a far more reliable signal than "rarely used", which
    Gmail data alone cannot tell you anything about.
    """
    by_category: dict[str, list[dict]] = {}
    for sub in db.list_subscriptions(conn, status="active"):
        by_category.setdefault(sub["category"] or "other", []).append(sub)

    groups = []
    for category, subs in by_category.items():
        if category == "other" or len(subs) < 2:
            continue

        # Same rule as db.totals(): sum per currency, never across.
        per_currency: dict[str, float] = {}
        for s in subs:
            code = (s["currency"] or db.DEFAULT_CURRENCY).strip().upper()
            per_currency[code] = per_currency.get(code, 0.0) + db.monthly_equivalent(
                s["amount"], s["billing_cycle"]
            )
        per_currency = {c: round(v, 2) for c, v in sorted(per_currency.items())}

        groups.append({
            "category": category,
            "count": len(subs),
            "merchants": [s["merchant_name"] for s in subs],
            "monthly_by_currency": per_currency,
            "monthly_display": " + ".join(
                f"{c} {v:,.2f}" for c, v in per_currency.items()
            ) or "0.00",
            # Sort key only — not displayed, so cross-currency mixing is safe here.
            "_sort_total": sum(per_currency.values()),
        })
    return sorted(groups, key=lambda g: g["_sort_total"], reverse=True)
