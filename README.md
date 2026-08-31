# V.A.U.L.T.

**V**oice-**A**ctivated **U**nified **L**ogic **T**erminal — a local-first personal
automation system built on Claude Code.

Two things it does:

- **Voice interface.** Hold a key or click a button, speak, and it transcribes
  locally on the GPU, routes the request by cost (regex → skill → Claude), and
  speaks a reply. Audio never leaves the machine; only the reasoning step calls
  an API.
- **Subscription tracker.** Scans Gmail read-only, extracts recurring charges
  with a language model, deduplicates repeat receipts into one row per
  subscription, flags plans that have silently stopped being charged, and warns
  about upcoming renewals.

Both write their output into a plain-markdown vault, so results accumulate as
notes rather than disappearing into a log.

---

## Status — read this first

This is a **personal project that runs on one laptop**. Being precise about that
is more useful than making it sound bigger:

- **Not deployed.** No server, no scheduler, no uptime. It runs when started by hand.
- **No automated tests.** Everything was verified by manual runs. There is no test suite.
- **Single user.** SQLite, no authentication, no multi-tenancy — by design, not oversight.
- **The web interface has no authentication at all** and exposes an endpoint that
  launches the Claude Code CLI. That is safe on `localhost` and would be remote
  code execution if exposed publicly. Do not bind it to `0.0.0.0`.
- **Windows-first.** The setup scripts and GPU DLL handling target Windows 11.
  The Python is portable; the packaging is not.

What it has actually done: one full scan of a real Gmail mailbox — 663 emails
fetched, 400 rejected by a regex prefilter before any API call, 263 sent for
extraction, 34 identified as subscription charges, deduplicated into 14 distinct
subscriptions.

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, Uvicorn |
| Database | SQLite — 4 tables, 2 indexes, additive migrations |
| Speech-to-text | faster-whisper (CUDA, CPU fallback) |
| Text-to-speech | Kokoro-ONNX (CPU) |
| Reasoning | Anthropic API — Claude Opus 5, structured outputs, Batch API, prompt caching |
| Email | Gmail API, OAuth2, `gmail.readonly` scope only |
| Frontend | Vanilla JavaScript, CSS, HTML — no framework |
| Memory | Plain markdown files (Obsidian-compatible) |

---

## Layout

```
.claude/skills/      Claude Code skills — one folder each, containing SKILL.md
.claude/agents/      Subagent definitions
.claude/commands/    Slash commands
voice/               capture → stt → router → tts pipeline
hud/                 FastAPI server, dashboard, CLI runner, voice bridge
subs/                Subscription tracker: db, prefilter, extraction, sync, CLI
vault.example/       Starter vault template (the live vault/ is gitignored)
docs/PLAN.md         Original architecture write-up
HANDOFF.md           Full setup guide, including everything not automated
```

---

## Running it

Requires **Python 3.11 or 3.12** (not 3.13 — some voice dependencies don't build).

```bash
git clone https://github.com/OggyAI/V.A.U.L.T.git
cd V.A.U.L.T
python -m venv .venv
.venv\Scripts\activate.bat          # Windows CMD
pip install -r requirements.txt
cp .env.example .env                # then add your Anthropic API key
```

**Voice, text mode** — no microphone or model files needed:

```bash
python -m voice.loop --text
```

**Dashboard** at http://127.0.0.1:8550:

```bash
uvicorn hud.server:app --port 8550
```

**Subscription tracker against sample data** — no Gmail account needed:

```bash
python -m subs.cli sync --source fixtures
python -m subs.cli list
```

Speech output needs two Kokoro model files (~340 MB) and `espeak-ng`. GPU
transcription needs `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` — the full CUDA
Toolkit is *not* required. Real Gmail scanning needs a Google Cloud OAuth client.
All three are covered step by step in [HANDOFF.md](HANDOFF.md).

Everything degrades rather than crashing: no model files means text-only replies,
no GPU means CPU transcription, no Gmail credentials means the sample dataset.

---

## Design decisions worth explaining

**Sync state commits after processing, not after fetching.** The Gmail cursor is
staged in memory and written only once every email has been extracted and stored.
An earlier version saved it on download; a crash mid-run then meant the next run
resumed past 663 unprocessed emails and silently reported nothing. This chooses
at-least-once (re-fetch, absorbed by deduplication) over at-most-once (skip data
permanently and invisibly).

**Currency totals are never converted.** Multi-currency spend is reported as
`AUD 135.96 + USD 23.33`, not a single number. Summing them requires an FX rate,
and a stale rate silently misstates the exact figure the tool exists to report.
Subscriptions with an unknown billing cycle are excluded from totals and the
exclusion is stated, rather than guessed.

**Cancellation is inferred but never applied.** A cancelled plan doesn't announce
itself — it just stops producing receipts. Two consecutive missed billing cycles
flags a subscription for review. It is never auto-cancelled, because a vendor
changing its receipt template is indistinguishable from a real cancellation at
this layer.

**Cost control is layered.** A regex prefilter rejects most email before any API
call; the model prompt is a cached prefix; backfills use the Batch API. On the
one real run, 400 of 663 emails were rejected for free.

**Command execution is allowlisted.** The dashboard can launch Claude Code, but
only via a fixed map of button keys to hardcoded prompts. No caller-supplied text
reaches the command line, arguments are passed as a list rather than a shell
string, tool access is scoped, and jobs are killed after 10 minutes.

---

## Security notes

**Present:** read-only OAuth scope (`gmail.readonly`); allowlisted command
execution with no shell interpolation; secrets gitignored and never logged;
input validation returning 400/404/503; idempotent writes via UNIQUE constraints;
confidence-gated extraction routing low-certainty results to human review;
read-only with respect to vendor accounts — it recommends cancellations, never
performs them.

**Absent:** authentication, HTTPS, CSRF protection, rate limiting, audit logging,
secret encryption at rest, and automated tests. The threat model assumes a single
user on a trusted machine and a loopback-only bind.

---

## Attribution

The five-layer architecture in [docs/PLAN.md](docs/PLAN.md) is reconstructed from
a third-party write-up, noted in that file. The implementation in this repository
was built with Claude Code.

---

## Licence

No licence yet — all rights reserved.
