"""Gmail fetch layer — read-only.

Scope is gmail.readonly and nothing else: this module can read mail and can
neither send, modify, nor delete anything.

Requires a Google Cloud OAuth client (credentials.json) that you create and
consent to yourself — see HANDOFF.md step 10. Until then every entry point
raises GmailNotConfigured with a pointer, and `--source fixtures` exercises
the same downstream code.

Neither credentials.json nor token.json is ever read by anything but the
Google client library, and both are gitignored.
"""

import base64
import html
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from subs import db, prefilter

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_PATH = Path(os.environ.get("GMAIL_CREDENTIALS_PATH") or PROJECT_ROOT / "credentials.json")
TOKEN_PATH = Path(os.environ.get("GMAIL_TOKEN_PATH") or PROJECT_ROOT / "token.json")

HISTORY_ID_KEY = "gmail_history_id"


class GmailNotConfigured(RuntimeError):
    """Raised when OAuth setup hasn't been completed."""


def _require_libs():
    try:
        from google.auth.transport.requests import Request  # noqa: F401
        from google.oauth2.credentials import Credentials  # noqa: F401
        from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: F401
        from googleapiclient.discovery import build  # noqa: F401
    except ImportError as e:
        raise GmailNotConfigured(
            "Google API libraries not installed - run:\n"
            "  pip install google-api-python-client google-auth-oauthlib"
        ) from e


def _service():
    """Build an authorized Gmail client, running the consent flow if needed."""
    _require_libs()
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                raise GmailNotConfigured(
                    f"No OAuth client at {CREDENTIALS_PATH}.\n"
                    "Create one in Google Cloud Console and download it - "
                    "see HANDOFF.md step 10."
                )
            # Opens a browser for consent. You approve; the token is written
            # locally and this process never sees your password.
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)

        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        print(f"[gmail] Token saved to {TOKEN_PATH}")

    return build("gmail", "v1", credentials=creds)


# ── Message parsing ──────────────────────────────────────

def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\n\s*\n\s*\n+")


def _strip_html(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", text)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    return _WS.sub("\n\n", text).strip()


def _extract_body(payload: dict) -> str:
    """Walk the MIME tree, preferring text/plain over stripped HTML."""
    plain, html_body = [], []

    def walk(part):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data:
            if mime == "text/plain":
                plain.append(_decode(data))
            elif mime == "text/html":
                html_body.append(_decode(data))
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)

    if plain:
        return "\n".join(plain).strip()
    if html_body:
        return _strip_html("\n".join(html_body))
    return ""


def _headers(payload: dict) -> dict:
    return {h["name"].lower(): h["value"] for h in payload.get("headers", [])}


def _to_email(message: dict) -> dict:
    payload = message.get("payload", {})
    hdr = _headers(payload)

    received = ""
    if message.get("internalDate"):
        received = datetime.fromtimestamp(
            int(message["internalDate"]) / 1000, tz=timezone.utc
        ).isoformat()

    return {
        "id": message.get("id"),
        "thread_id": message.get("threadId"),
        "received_at": received,
        "sender": hdr.get("from", ""),
        "subject": hdr.get("subject", ""),
        "body": _extract_body(payload),
    }


# ── Fetching ─────────────────────────────────────────────

# Set by fetch_messages, written only by commit_state(). Keeping these apart
# is what makes a sync crash-safe: if extraction dies, the historyId is never
# advanced, so the next run re-fetches the same window instead of skipping it.
_pending_history_id: str | None = None


def commit_state():
    """Persist the historyId from the last fetch.

    Call only after the fetched emails have been successfully processed.
    Committing earlier means a crash or an interrupted run silently loses
    every email in that window.
    """
    global _pending_history_id
    if _pending_history_id:
        db.set_state(db.connect(), HISTORY_ID_KEY, str(_pending_history_id))
        _pending_history_id = None


def fetch_messages(limit: int | None = None, months: int = 12,
                   incremental: bool = True, **_ignored) -> list[dict]:
    """Fetch candidate emails.

    On the first run this is a bounded backfill (default 12 months) using the
    prefilter's Gmail query. Afterwards it uses the stored historyId so each
    sync only pulls what arrived since — the whole mailbox is scanned once,
    never again.

    Does NOT persist sync state; the caller must call commit_state() once the
    emails have actually been extracted and stored.
    """
    global _pending_history_id
    service = _service()
    conn = db.connect()
    history_id = db.get_state(conn, HISTORY_ID_KEY) if incremental else None

    if history_id:
        ids, new_history_id = _incremental_ids(service, history_id)
        print(f"[gmail] Incremental: {len(ids)} new message(s) since history {history_id}")
    else:
        ids, new_history_id = _backfill_ids(service, months=months, limit=limit)
        print(f"[gmail] Backfill: {len(ids)} candidate message(s) over {months} months")

    if limit:
        ids = ids[:limit]

    emails, missing, failed = [], 0, []
    for i, msg_id in enumerate(ids, 1):
        if i % 25 == 0:
            print(f"[gmail] Downloaded {i}/{len(ids)}")
        try:
            msg = service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()
            emails.append(_to_email(msg))
        except Exception as e:
            # A 404 here is normal: the message was deleted or moved between
            # the list call and the get. Counted, not dumped — one stack trace
            # per missing message buries the actual result.
            if "404" in str(e) or "not found" in str(e).lower():
                missing += 1
            else:
                failed.append((msg_id, str(e).split("\n")[0][:100]))

    if missing:
        print(f"[gmail] {missing} message(s) no longer exist (deleted or moved) - skipped.")
    for msg_id, err in failed[:5]:
        print(f"[gmail] Failed {msg_id}: {err}")
    if len(failed) > 5:
        print(f"[gmail] ...and {len(failed) - 5} more failures.")

    _pending_history_id = new_history_id
    return emails


def _backfill_ids(service, months: int, limit: int | None) -> tuple[list[str], str | None]:
    after = (datetime.now(timezone.utc) - timedelta(days=months * 31)).strftime("%Y/%m/%d")
    query = f"{prefilter.GMAIL_QUERY} after:{after}"

    ids, page_token = [], None
    while True:
        resp = service.users().messages().list(
            userId="me", q=query, pageToken=page_token, maxResults=500
        ).execute()
        ids.extend(m["id"] for m in resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token or (limit and len(ids) >= limit):
            break

    profile = service.users().getProfile(userId="me").execute()
    return ids, profile.get("historyId")


def _incremental_ids(service, start_history_id: str) -> tuple[list[str], str | None]:
    ids, page_token, latest = set(), None, start_history_id
    while True:
        try:
            resp = service.users().history().list(
                userId="me", startHistoryId=start_history_id,
                historyTypes=["messageAdded"], pageToken=page_token,
            ).execute()
        except Exception as e:
            # A historyId older than Gmail's retention window is expired —
            # fall back to a short backfill rather than silently syncing nothing.
            print(f"[gmail] History expired ({e}); falling back to a 1-month backfill.")
            return _backfill_ids(service, months=1, limit=None)

        for record in resp.get("history", []):
            for added in record.get("messagesAdded", []):
                ids.add(added["message"]["id"])
        latest = resp.get("historyId", latest)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return list(ids), latest


def check_setup() -> tuple[bool, str]:
    """Report whether Gmail is usable, without triggering the consent flow."""
    try:
        _require_libs()
    except GmailNotConfigured as e:
        return False, str(e)
    if not CREDENTIALS_PATH.exists():
        return False, f"Missing {CREDENTIALS_PATH.name} - see HANDOFF.md step 10"
    if not TOKEN_PATH.exists():
        return False, "Not yet authorized - run: python -m subs.cli sync --source gmail"
    return True, "Gmail configured"


if __name__ == "__main__":
    ok, message = check_setup()
    print(f"{'OK' if ok else 'NOT READY'}: {message}")
