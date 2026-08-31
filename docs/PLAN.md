# Build Your Own "Jarvis" (V.A.U.L.T.) — Full Setup Guide

A voice-driven, local-first AI command center built on **Claude Code**. This guide reconstructs the architecture from the CHASE AI carousel into something you can actually build, in build order, with the gotchas the carousel glosses over.

---

## 0. What you're actually building

Forget the cinematic framing — there is no single "Jarvis" product. V.A.U.L.T. is **five independent layers** glued together, four of which already exist as off-the-shelf tools. Claude Code is the conductor in the middle.

| Layer | Carousel name | What it really is | Tool |
|-------|---------------|-------------------|------|
| Brain | Skill Architecture | Procedural know-how, loaded on demand | Claude Code `.claude/skills/` |
| Memory | Obsidian Vault | Long-term notes Claude reads + writes | Obsidian / plain markdown |
| Voice | 100% Local Voice | Speech in, speech out, offline | faster-whisper + Kokoro |
| Face | One HUD | A dashboard over the above | Local HTML/web app |
| Handoff | Bundle / Ship / Reskin | The repo that packages it all | Git + `setup.sh` |

The genius of the design is **progressive disclosure**: skills cost ~100 tokens each until invoked, so you can have 50 of them installed and Claude only pulls the full instructions for the one the moment needs. That's what lets a single agent behave like a whole "OS."

### The honest version of the pitch
- "Runs on any model" is true — Claude Code lets you pick Opus / Sonnet / Haiku, and the voice router uses cheap Haiku for classification.
- "100% local voice" is true for the **ears and mouth** (STT + TTS). The actual *reasoning* still calls Claude in the cloud unless you swap in a local LLM. The carousel is precise about this if you read slide 5 carefully ("each line routes via regex, a local model, **or Haiku**").
- This is a **weekend-to-fortnight** project if you build it in the order below, not an afternoon.

---

## 1. Prerequisites & stack

**Your machine (Windows 11 + AMD RX 6750 XT):** everything here runs, but see the **AMD warning in Step 3** — it changes which STT tool you should pick.

Install these once:

- **Node.js 18+** and **Claude Code**: `npm install -g @anthropic-ai/claude-code`
- **Python 3.11 or 3.12** (⚠️ *not* 3.13 — several voice deps like `misaki`/`numpy<2.0` don't build cleanly on 3.13 yet). Use `pyenv-win` or a clean venv.
- **Obsidian** (free) — or just a folder of `.md` files; Obsidian is only the viewer.
- **Git** + a GitHub account.
- A code editor (you already live in Claude Code desktop, so you're set).

---

## 2. Step 1 — The Brain: Skill Architecture

> *"Map your work into branches, break each into skills — folders with a SKILL.md. Claude loads only what the moment needs."*

### 2.1 The mental model
- **Branch** = a domain of your work (the carousel shows: MEMORY, PRODUCTIVITY, RESEARCH, CONTENT, COMMUNITY, AGENCY, SALES, FINANCE, OPS/CUSTOM).
- **Skill** = one repeatable workflow inside a branch ("draft a sponsor pitch," "run the morning trend scan," "generate the weekly client status").
- Each skill is a folder with a single **`SKILL.md`** file. That's the only required file.

### 2.2 Directory layout
Skills live in one of two places:
- **Project-level:** `<your-project>/.claude/skills/` (shared via the repo)
- **Personal/global:** `~/.claude/skills/` (every session, every repo)

```
.claude/
├── CLAUDE.md                # always-loaded project context (conventions, paths)
├── skills/
│   ├── morning-trend-scan/
│   │   ├── SKILL.md
│   │   └── scripts/scan.py  # optional helper; its code never enters context
│   ├── weekly-client-status/
│   │   └── SKILL.md
│   └── sponsor-pitch-deck/
│       └── SKILL.md
├── agents/                  # subagents (isolated context workers)
│   └── deep-research.md
├── commands/                # slash commands (/morning, /ship)
│   └── morning.md
└── settings.json            # hooks (run scripts on events)
```

### 2.3 Anatomy of a SKILL.md
The frontmatter is what Claude reads at startup (cheap). The body loads only when the skill fires.

```markdown
---
name: morning-trend-scan
description: Pull trending topics across the channel's niche and write a ranked
  brief. Use every morning, or when the user says "what's trending" / "trend scan".
allowed-tools: Read, Bash, WebSearch
---

# Morning Trend Scan

1. Run `scripts/scan.py` to fetch raw trend data.
2. Rank items by relevance to the channel (gaming/AI/automation).
3. Write the result to the Obsidian vault at `Reports/trend-scan-{date}.md`
   with `[[wikilinks]]` to any recurring topics.
4. Return the top 3 inline.
```

**Rules that actually matter:**
- The folder must contain a file named **exactly `SKILL.md`**.
- The `description` is everything — it's the only thing Claude sees when deciding whether to use the skill. Pack it with trigger words ("when the user says X / mentions Y").
- Keep the body **concise**. Once invoked, it stays in context for the rest of the turn, so every line is a recurring token cost. State *what to do*, not *why*.
- Put bundled scripts in `scripts/` and reference them with `${CLAUDE_SKILL_DIR}/scripts/...` so paths resolve at any install level. **Script code never enters context — only its output does.** This is the single biggest efficiency win.

### 2.4 Subagents (the carousel's "isolated workers")
A subagent is a markdown file in `.claude/agents/` with its own fresh context window. Use them for noisy read-heavy tasks (research, repo scans) so they don't pollute your main thread. Run a research task on cheap Haiku and only the summary comes back.

```markdown
---
name: deep-research
description: Research a topic thoroughly and return a sourced summary.
context: fork
agent: Explore
---
Research $ARGUMENTS thoroughly: find sources, read them, return a ranked
summary with links. Do not edit any files.
```

### 2.5 Slash commands & hooks
- **Slash commands** (`.claude/commands/morning.md`) are explicit entry points you type: `/morning` could fire the trend scan + inbox brief + plan-today skills in sequence.
- **Hooks** (`.claude/settings.json`) run scripts on events (e.g. after every file write, re-index the vault). This is your bridge to deterministic automation — exactly the kind of thing you'd otherwise reach for n8n to do.

> **Don't hand-write 30 skills.** Use the `skill-creator` skill (or just ask Claude Code to scaffold them): "Create a skill for X that does Y, writes output to my vault." Generate the skeleton, then tighten the descriptions by hand.

---

## 3. Step 2 — The Memory: An Obsidian Vault

> *"Plain markdown becomes long-term memory. Every note links into a graph Claude can traverse — no database. Every report the OS generates lands back as an Obsidian Markdown file."*

### 3.1 Why this works
You don't need a vector DB for personal scale. A folder of markdown files with `[[wikilinks]]` *is* a graph. Claude reads files with `Read`/`Grep`/`Glob`, follows links, and writes new notes back. Obsidian is just the pretty graph viewer on top — the data is plain text you own.

### 3.2 Suggested vault structure
```
Vault/
├── 00-Inbox/            # raw captures
├── 10-Projects/         # one note per active project (ride-hailing, YT pipeline...)
├── 20-Areas/            # ongoing responsibilities (capstone, library shifts)
├── 30-Reports/          # ← where the OS WRITES its generated reports
│   ├── trend-scan-2026-06-25.md
│   └── weekly-status-2026-06-25.md
├── 40-Reference/        # evergreen notes
└── 99-Meta/
    └── index.md         # hub note linking everything (Claude's entry point)
```

### 3.3 The write-back loop (the part that makes it feel alive)
Every skill that produces output should **end by writing a markdown file into `30-Reports/`** with wikilinks to relevant project/area notes. Next time you ask "what did we decide about the Gelephu beachhead," Claude greps the vault, follows the links, and answers from your own history instead of starting cold.

Two practical tips:
- Give Claude the vault path in `CLAUDE.md` so it always knows where memory lives: `Vault root: C:/Users/you/Obsidian/Vault`.
- Add a hook that runs after report writes to keep an `index.md` hub note updated — that's the single file Claude reads first to orient.

---

## 4. Step 3 — The Voice: 100% Local STT + TTS

> *"Mic in → faster-whisper transcribes locally. Each line routes via regex, a local model, or Haiku — then Kokoro speaks back. Ears + mouth stay 100% local."*

This is the hardest layer and the one with a **real hardware gotcha for you.**

### 4.1 ⚠️ AMD warning (read this before installing anything)
**faster-whisper is built on CTranslate2, which only supports NVIDIA CUDA + CPU. It has no AMD/ROCm backend on Windows.** On your RX 6750 XT it will **silently fall back to CPU** — it won't error, it just won't touch your GPU. You'll only notice from a log line about no NVIDIA driver.

Your three honest options:

| Option | GPU-accelerated on your RX 6750 XT? | Effort | Verdict |
|--------|-------------------------------------|--------|---------|
| **faster-whisper on CPU** | No (CPU only) | Low | ✅ Fine for short voice commands with `tiny`/`base`/`small` models — these run near-real-time on a modern CPU |
| **whisper.cpp (Vulkan/HIP backend)** | Yes | Medium | Best if you want GPU speed on AMD; it's the C++ port with an AMD path |
| **CTranslate2-ROCm fork in Docker** | Yes | High | A "research project" per the community; only worth it for long-form batch transcription |

**Recommendation:** for a voice command center you're speaking short phrases into, just run **faster-whisper on CPU with the `base` or `small` model**. Voice commands are 1–3 seconds of audio; CPU transcription is effectively instant at that length. Don't burn a weekend fighting ROCm for a use case that doesn't need it. Reach for whisper.cpp only if you later want to transcribe hour-long recordings.

### 4.2 Install the ears (STT)
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install faster-whisper sounddevice numpy
```
Minimal capture-and-transcribe:
```python
from faster_whisper import WhisperModel

# device="cpu" is your reality on AMD; compute_type="int8" keeps it fast
model = WhisperModel("base", device="cpu", compute_type="int8")

def transcribe(wav_path: str) -> str:
    segments, _ = model.transcribe(wav_path, language="en")
    return " ".join(s.text for s in segments).strip()
```

### 4.3 Install the mouth (TTS) — Kokoro
Kokoro-82M is Apache-2.0, ~327 MB, 54 voices, and **designed to run fast on CPU** — so the AMD limitation doesn't bite here at all. Two ways:

**Simple (official):**
```bash
pip install kokoro soundfile
# plus the espeak-ng system binary (download the Windows installer from the
# espeak-ng GitHub releases; add it to PATH)
```
```python
from kokoro import KPipeline
import soundfile as sf

pipe = KPipeline(lang_code="a")  # 'a' = American English
for _, _, audio in pipe("Good morning. Here's what's on today.", voice="af_bella"):
    sf.write("reply.wav", audio, 24000)
```

**Lighter (ONNX, fewer deps):**
```bash
pip install kokoro-onnx soundfile
# download kokoro-v1.0.onnx and voices-v1.0.bin into your working dir
```

### 4.4 The router (the actual brains of the voice loop)
The carousel's key idea: **not every utterance needs the full model.** Route each transcribed line by cost:

1. **Regex first** — "what time is it", "stop", "next" → handle locally, instantly, free.
2. **Local model / small classifier** — categorize intent if you've got one loaded.
3. **Haiku** — cheap Claude call for anything that needs real reasoning or a skill.

```python
import re

def route(text: str):
    t = text.lower().strip()
    if re.search(r"\b(stop|cancel|never ?mind)\b", t):
        return ("local", "abort")
    if re.search(r"\bwhat('?s| is) on (today|my schedule)\b", t):
        return ("skill", "plan-today")        # fire a Claude Code skill
    return ("haiku", text)                     # default: let Claude decide
```

### 4.5 Wire the loop
```
mic → faster-whisper (CPU)  →  router  →  { regex | local | Haiku/Claude }
                                              ↓
                                       text reply / skill output
                                              ↓
                                     Kokoro → speaker
```
Push-to-talk (hold a key to record) is far more reliable than always-on wake-word detection for a v1 — skip the wake word until the rest works.

---

## 5. Step 4 — The Face: Wire It Into One HUD

> *"Skills, memory + voice meet behind a single dashboard — the V.A.U.L.T. command center."*

The HUD in the carousel ("V.A.U.L.T. — Voice-Activated Unified Logic Terminal") is **a local web page**, not a native app. It's the easiest layer to fake impressively and the least functionally important — build it last.

### 5.1 What it actually displays
Looking at the mock, three live regions:
- **METRICS (left):** numbers pulled from your sources (YT subs, IG followers, latest video views). Just API calls or scraped values written to a JSON file the page reads.
- **VOICE (center):** the animated particle sphere = a visual state indicator (idle / listening / speaking). Pure eye-candy; a `<canvas>` animation driven by the voice loop's state.
- **SKILLS / COMMAND DECK (right):** buttons that trigger your slash commands (Metrics Pull, AM Report, Trend Scan, Plan Today...). Each button shells out to `claude` or hits a tiny local API.

### 5.2 Minimal architecture
```
┌─ HUD (index.html + canvas + fetch) ─┐
│   reads:  status.json (voice state) │
│           metrics.json (numbers)    │
│   posts:  /run-command  ───────────►│ tiny local server (FastAPI/Express)
└─────────────────────────────────────┘        │
                                          spawns claude / skills
```
Keep state in flat JSON files the voice loop writes and the page polls. No database, consistent with the whole "plain files" philosophy. If you want it to look like the mock, that's a `frontend-design` job — dark terminal aesthetic, monospace, a particle sphere via three.js or a 2D canvas.

> Build order reminder: the HUD is a *window* onto layers 1–3. If those don't work, a pretty HUD is a screensaver. Get voice → skill → vault working in the terminal first.

---

## 6. Step 5 — The Handoff: Bundle, Ship, Reskin

> *"It all lives in one GitHub repo — clone, drop in keys, run. Then fork it per client."*

### 6.1 Repo structure
```
vault/
├── .claude/              # skills, agents, commands, hooks (Step 1)
├── voice/                # STT + router + TTS (Step 3)
├── hud/                  # dashboard (Step 4)
├── vault.example/        # starter Obsidian structure (Step 2)
├── .env.example         # API keys template — NEVER commit the real .env
├── setup.sh             # one-shot installer
└── README.md
```

### 6.2 `.env.example`
```
ANTHROPIC_API_KEY=
YT_API_KEY=
IG_TOKEN=
VAULT_PATH=./vault
```

### 6.3 `setup.sh` (what slide 7's terminal shows)
```bash
#!/usr/bin/env bash
set -e
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # faster-whisper, kokoro, fastapi...
cp -r vault.example ./vault            # mount the vault
ln -sf "$(pwd)/.claude" ~/.claude_link # link skills
echo "✓ skills linked · vault mounted · voice ready"
```
> On Windows, ship a `setup.ps1` PowerShell equivalent — `setup.sh` assumes bash.

### 6.4 Reskin per client
Because everything is files + env vars, "forking per client" means: clone, swap `.env`, swap the vault, swap the HUD's branding/voice (`voice="af_bella"` → another), and optionally disable branch-skills the client doesn't need. That's the productization angle the carousel is selling — one codebase, N customized instances.

---

## 7. Recommended build order (don't do it in slide order)

The carousel presents this as a polished product. Build it as an MVP that grows:

1. **Vault + 3 skills, terminal only.** Get Claude Code writing reports into your Obsidian vault and reading them back. No voice, no HUD. *This alone is genuinely useful.*
2. **Add the voice loop in the terminal.** Push-to-talk → faster-whisper (CPU) → print text → Kokoro speaks a canned reply. Prove the audio round-trip.
3. **Connect voice → router → skills.** Now speaking "trend scan" fires the real skill and speaks the result.
4. **Build the HUD** as a window onto the JSON state files.
5. **Package the repo** with `.env.example` + setup script once it works for *you*.

---

## 8. Caveats the carousel skips

- **Not truly local reasoning.** STT/TTS are local; the thinking is Claude in the cloud unless you bolt on a local LLM (Ollama etc.). Fine — just know what "100% local" actually scopes to.
- **AMD STT.** Covered above — your GPU sits idle for faster-whisper. Plan around CPU or switch to whisper.cpp.
- **Wake-word / always-on listening** is a rabbit hole. Push-to-talk first.
- **Skill sprawl.** Fifty skills with vague descriptions = Claude picking the wrong one. Descriptions are the product; invest there.
- **Secrets.** The "drop in keys, run" flow means an `.env` full of tokens. Keep it gitignored; never bake keys into skills.
- **Cost.** Routing trivial lines to regex/local instead of Haiku isn't just elegance — it's what keeps a chatty voice loop from quietly running up API calls.

---

*Built from the CHASE AI carousel (slides 2–7). The cover and final CTA slides weren't included, so any pricing/community offer on slide 8 isn't reflected here.*
