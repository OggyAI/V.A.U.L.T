"""Command line for the subscription tracker.

    python -m subs.cli sync --source fixtures     # safe: no Gmail needed
    python -m subs.cli sync --source fixtures --dry-run
    python -m subs.cli sync --source gmail --months 12
    python -m subs.cli list
    python -m subs.cli review
    python -m subs.cli report
"""

import argparse
import sys

from subs import db, sync


def _money(amount, currency) -> str:
    if amount is None:
        return "-"
    return f"{currency or ''} {amount:,.2f}".strip()


def cmd_sync(args):
    from dotenv import load_dotenv
    load_dotenv()

    result = sync.run(
        source=args.source,
        limit=args.limit,
        batched=not args.live,
        dry_run=args.dry_run,
        months=args.months,
    )

    print()
    print(f"  new subscriptions : {result.get('new', 0)}")
    print(f"  updated           : {result.get('updated', 0)}")
    print(f"  filtered out      : {result.get('rejected', 0)}")
    print(f"  already scanned   : {result.get('skipped_seen', 0)}")

    t = result["totals"]
    print()
    print(f"  active            : {t['active_count']}")
    print(f"  needs review      : {t['needs_review_count']}")
    print(f"  monthly spend     : {db.format_totals(t, 'monthly')}")
    print(f"  yearly spend      : {db.format_totals(t, 'yearly')}")
    if t["mixed_currency"]:
        print("  (currencies are not converted - no FX rate configured)")
    if t["excluded_unknown_cycle"]:
        print(f"  (excluded {t['excluded_unknown_cycle']} with unknown billing cycle)")


def cmd_list(args):
    conn = db.connect()
    subs = db.list_subscriptions(conn, status=args.status)
    if not subs:
        print("No subscriptions. Run: python -m subs.cli sync --source fixtures")
        return

    print(f"{'ID':<5}{'MERCHANT':<22}{'AMOUNT':<14}{'CYCLE':<11}{'RENEWS':<12}{'CONF':<6}STATUS")
    print("-" * 84)
    for s in subs:
        print(
            f"{s['id']:<5}{(s['merchant_name'] or '')[:21]:<22}"
            f"{_money(s['amount'], s['currency']):<14}"
            f"{(s['billing_cycle'] or '-'):<11}"
            f"{(s['next_renewal_date'] or '-'):<12}"
            f"{(s['confidence'] or 0):.2f}  {s['status']}"
        )

    t = db.totals(conn)
    print("-" * 84)
    print(f"{t['active_count']} active - {db.format_totals(t, 'monthly')}/month "
          f"({db.format_totals(t, 'yearly')}/year)")
    if t["mixed_currency"]:
        print("currencies are not converted - no FX rate configured")

    stale = db.stale_subscriptions(conn)
    if stale:
        print(f"\n{len(stale)} may be cancelled (no charge in 2+ cycles): "
              f"{', '.join(s['merchant_name'] for s in stale)}")
        print("  python -m subs.cli stale")

    dupes = sync.find_duplicates(conn)
    if dupes:
        print("\nPossible overlap:")
        for g in dupes:
            print(f"  {g['category']}: {', '.join(g['merchants'])} "
                  f"- {g['monthly_display']}/month combined")


def cmd_stale(args):
    """Show subscriptions that have stopped producing receipts."""
    conn = db.connect()
    db.backfill_last_charge_seen(conn)
    stale = db.stale_subscriptions(conn, cycles=args.cycles)

    if not stale:
        print(f"Nothing stale (no active subscription has missed {args.cycles}+ cycles).")
        return

    total = 0.0
    print(f"{len(stale)} subscription(s) with no charge in {args.cycles}+ billing cycles.")
    print("These have most likely been cancelled.\n")
    for s in stale:
        print(f"  [{s['id']:>2}] {s['merchant_name']:<16} "
              f"{_money(s['amount'], s['currency']):<12} {s['billing_cycle']:<9} "
              f"last charged {s['days_since_charge']}d ago ({s['cycles_missed']} cycles)")
        total += db.monthly_equivalent(s["amount"], s["billing_cycle"])

    print(f"\nStill counted in your monthly total: ~{total:,.2f} (mixed currencies)")

    if args.drop_all:
        for s in stale:
            db.set_status(conn, s["id"], "cancelled")
        print(f"\nMarked {len(stale)} subscription(s) cancelled.")
    else:
        print("\nDrop them all:   python -m subs.cli stale --drop-all")
        print("Or one at a time: python -m subs.cli reject <id>")


def cmd_review(args):
    conn = db.connect()
    pending = db.list_subscriptions(conn, status="needs_review")
    if not pending:
        print("Nothing to review.")
        return

    print(f"{len(pending)} low-confidence extraction(s).\n")
    for s in pending:
        print(f"  [{s['id']}] {s['merchant_name']} - {_money(s['amount'], s['currency'])} "
              f"{s['billing_cycle']} (confidence {s['confidence']:.2f})")

    print("\nConfirm or reject:")
    print("  python -m subs.cli confirm <id>")
    print("  python -m subs.cli reject <id>")


def cmd_confirm(args):
    db.set_status(db.connect(), args.id, "active")
    print(f"Subscription {args.id} confirmed as active.")


def cmd_reject(args):
    db.set_status(db.connect(), args.id, "cancelled")
    print(f"Subscription {args.id} marked cancelled.")


def cmd_report(args):
    """Write a markdown report into the vault."""
    from datetime import date
    from pathlib import Path

    conn = db.connect()
    t = db.totals(conn)
    active = db.list_subscriptions(conn, status="active")
    renewals = db.upcoming_renewals(conn, within_days=30)
    dupes = sync.find_duplicates(conn)

    today = date.today().isoformat()
    lines = [
        f"# Subscription Audit — {today}",
        "",
        f"**{t['active_count']} active subscriptions** — "
        f"{db.format_totals(t, 'monthly')}/month "
        f"({db.format_totals(t, 'yearly')}/year)",
        "",
    ]
    if t["mixed_currency"]:
        lines += ["> Currencies are listed separately — no FX rate is configured.", ""]
    lines += [
        "## Active",
        "",
        "| Merchant | Amount | Cycle | Next renewal |",
        "|---|---|---|---|",
    ]
    for s in active:
        lines.append(
            f"| {s['merchant_name']} | {_money(s['amount'], s['currency'])} "
            f"| {s['billing_cycle'] or '-'} | {s['next_renewal_date'] or '-'} |"
        )

    if renewals:
        lines += ["", "## Renewing in the next 30 days", ""]
        for s in renewals:
            lines.append(
                f"- **{s['merchant_name']}** — {_money(s['amount'], s['currency'])} "
                f"in {s['days_until']} days ({s['next_renewal_date']})"
            )

    if dupes:
        lines += ["", "## Possible overlap", ""]
        for g in dupes:
            lines.append(
                f"- **{g['category']}** — {', '.join(g['merchants'])} "
                f"({g['monthly_display']}/month combined)"
            )

    pending = db.list_subscriptions(conn, status="needs_review")
    if pending:
        lines += ["", "## Needs review", ""]
        for s in pending:
            lines.append(
                f"- {s['merchant_name']} — {_money(s['amount'], s['currency'])} "
                f"(confidence {s['confidence']:.2f})"
            )

    lines += ["", "---", "", "Related: [[vault]] · [[ai-tooling]]", ""]

    out_dir = Path("vault/30-Reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"subscriptions-{today}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out}")


def main():
    parser = argparse.ArgumentParser(prog="subs", description="Subscription tracker")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("sync", help="Fetch, extract, and store")
    p.add_argument("--source", choices=["fixtures", "gmail"], default="fixtures")
    p.add_argument("--limit", type=int, help="Cap emails fetched")
    p.add_argument("--months", type=int, default=12, help="Gmail backfill depth")
    p.add_argument("--live", action="store_true",
                   help="Skip the Batch API (2x cost, immediate results)")
    p.add_argument("--dry-run", action="store_true",
                   help="Prefilter and estimate cost, make no API calls")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("list", help="Show tracked subscriptions")
    p.add_argument("--status", choices=["active", "needs_review", "cancelled", "paused"])
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("stale", help="Show subscriptions that stopped being charged")
    p.add_argument("--cycles", type=int, default=db.STALE_CYCLES,
                   help=f"Billing cycles of silence before flagging (default {db.STALE_CYCLES})")
    p.add_argument("--drop-all", action="store_true",
                   help="Mark every stale subscription cancelled")
    p.set_defaults(func=cmd_stale)

    p = sub.add_parser("review", help="Show low-confidence extractions")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("confirm", help="Confirm a reviewed subscription")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_confirm)

    p = sub.add_parser("reject", help="Reject a reviewed subscription")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_reject)

    p = sub.add_parser("report", help="Write a markdown report to the vault")
    p.set_defaults(func=cmd_report)

    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
