# HANDOFF — Manual Steps Checklist

Everything the code **cannot** do for you. Work through in order.

---

## 1. Python environment

**Requires:** Python 3.11 or 3.12 (not 3.13 — voice deps don't build cleanly).

```powershell
# Verify version
python --version

# Run the setup script (creates venv, installs deps, copies vault, creates .env)
.\setup.ps1
```

**If you're in CMD rather than PowerShell**, `.ps1` scripts won't run. Do it manually:

```
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

Notes:
- `kokoro-onnx` requires `numpy>=2.0.2` (it pulls in `librosa` + `numba`, ~500 MB of wheels).
  Don't pin `numpy<2` — that conflicts and the install will fail to resolve.
- If you hit build errors on `faster-whisper` or `numpy`, confirm you're on 3.11/3.12.

---

## 2. GPU acceleration for STT — ✅ DONE

**Status:** Working. `voice/stt.py` reports `cuda` on the RTX 3050.

**You do NOT need the CUDA Toolkit or a manual cuDNN install.** faster-whisper
only needs cuBLAS + cuDNN, both available as pip wheels:

```powershell
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```

~1.3 GB of wheels, installed into the venv. Requires only an up-to-date NVIDIA
driver (check with `nvidia-smi`), which you already have.

These are deliberately **not** in `requirements.txt` — they're GPU-only and
large, so CPU-only machines shouldn't be forced to download them.

**Verify — transcribe something, don't just check the device:**
```powershell
python -c "from voice import tts, stt; p = tts.speak('testing one two three', 'check.wav'); print(stt.transcribe(p))"
```

`get_device()` alone is **not** a sufficient check. CTranslate2 loads cuBLAS
lazily at the first encode, so a model can construct successfully on CUDA and
then fail mid-transcription with `cublas64_12.dll is not found`. Only an actual
transcription exercises that path.

> **Note:** `voice/stt.py` calls `_register_cuda_dlls()` at model-load time,
> which registers the pip-installed DLL directories via `os.add_dll_directory`.
> That's why GPU mode works from any terminal without setting PATH. If you ever
> move the venv or install the nvidia wheels globally instead, that helper
> looks under `sys.prefix/Lib/site-packages/nvidia/*/bin` — adjust if needed.

---

## 3. espeak-ng (for Kokoro TTS phoneme generation)

**Direct download** (v1.52.0, released 2024-12-12):
https://github.com/espeak-ng/espeak-ng/releases/download/1.52.0/espeak-ng.msi

The file is named exactly `espeak-ng.msi`. On the releases page it's hidden
behind the collapsed **"Assets"** dropdown at the bottom of the release notes —
GitHub shows only the source archives until you expand it.

**Do not download "Source code (zip)"** — that's the C source, not an installer.

- Run the `.msi`
- It should add `C:\Program Files\eSpeak NG\` to PATH automatically

**Verify** (in a *new* terminal — PATH changes don't apply to open windows):
```powershell
espeak-ng --version
```

If "not recognized", add `C:\Program Files\eSpeak NG\` to PATH manually:
Settings → System → About → Advanced system settings → Environment Variables
→ select `Path` under System variables → Edit → New → paste the path → OK.

---

## 4. Kokoro TTS model files

Download these two files and drop them in the **project root** — the same folder
as `requirements.txt`, i.e. the repository root. No renaming needed.
(Alternatively, put them anywhere and set `KOKORO_MODEL_PATH` / `KOKORO_VOICES_PATH` in `.env`.)

| File | Size | URL |
|------|------|-----|
| `kokoro-v1.0.onnx` | ~310 MB | https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx |
| `voices-v1.0.bin` | ~27 MB | https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin |

> Windows hides known extensions, so `voices-v1.0.bin` may display as just
> `voices-v1.0` with Type "BIN File". That's correct — don't add `.bin` again.

Both are gitignored (`*.onnx`, `*.bin`), so they won't bloat the repo.

```powershell
# Or download with curl:
curl -L -o kokoro-v1.0.onnx "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
curl -L -o voices-v1.0.bin "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
```

> **faster-whisper models auto-download** on first run (base model, ~150 MB). No manual step needed.

---

## 5. API keys

Edit `.env` and fill in:

```
ANTHROPIC_API_KEY=sk-ant-...       # Required for Haiku routing + Claude Code skills
YT_API_KEY=...                     # Optional — for real YouTube metrics in HUD
IG_TOKEN=...                       # Optional — for Instagram metrics in HUD
```

**Get your Anthropic key:** https://console.anthropic.com/settings/keys

The YouTube and Instagram keys are only needed when you replace the mock data in `scan.py` and `metrics.json` with real API calls. Skip them for now.

---

## 6. Obsidian (optional but recommended)

- Download from: https://obsidian.md
- Open vault → point it at the `vault/` directory (created by setup script)
- This just gives you a nice graph viewer — Claude reads/writes the same markdown files directly

---

## 7. Audio hardware test

```powershell
.\.venv\Scripts\Activate.ps1

# List audio devices — find your mic's index
python -c "import sounddevice; print(sounddevice.query_devices())"

# Test recording (3 seconds)
python -m voice.capture

# Test TTS (only works after step 4 — model files)
python -c "from voice.tts import play; play('Hello from VAULT')"
```

If your mic isn't the system default, edit `DEVICE_INDEX` in `voice/capture.py` to match the index from the device list.

---

## 8. First real run

```powershell
.\.venv\Scripts\Activate.ps1

# ── Test voice pipeline in text mode (no mic/speaker needed) ──
python -m voice.loop --text
# Type "what's trending" → should route to morning-trend-scan skill
# Type "what time is it"  → should respond with the time
# Type "quit" to exit

# ── Test the router standalone ──
python -m voice.router

# ── Start the HUD ──
uvicorn hud.server:app --port 8550
# Open http://127.0.0.1:8550 in your browser

# ── Full voice loop (after audio is working) ──
python -m voice.loop --timed 3     # 3s recording per turn
python -m voice.loop --ptt         # hold SPACE to talk (needs 'pip install keyboard')
```

---

## 10. Gmail access for the subscription tracker

**Everything except this step already works.** The tracker runs today against
sample emails — try it before doing any of this:

```powershell
python -m subs.cli sync --source fixtures
python -m subs.cli list
```

To point it at your real inbox you need a Google Cloud OAuth client. It's free,
takes about ten minutes, and requires no verification for personal use.

### 10a. Create the OAuth client

Google's newer **Google Auth Platform** UI renames the old panels. Mapping:
Branding = consent-screen basics, Audience = user type + test users,
Data access = scopes, Clients = credentials.

1. Go to https://console.cloud.google.com/ and select or create a project.

2. **Enable the Gmail API** — https://console.cloud.google.com/apis/library/gmail.googleapis.com
   → *Enable*. Easy to skip; without it, auth succeeds and every call 403s.

3. **Audience** → user type **External**, publishing status **Testing**
   (do *not* publish). Under **Test users**, add your own Gmail address.
   Testing mode needs no Google verification and works indefinitely.

4. **Data access** → *Add or remove scopes* → paste
   `https://www.googleapis.com/auth/gmail.readonly` into the manual box →
   *Add to table* → tick → *Update* → *Save*. Add nothing else. Google flags
   it as a **restricted scope**; that's expected and needs no verification
   while in Testing.

5. **Clients** → *Create OAuth client* → Application type **Desktop app**
   (Web application will fail the local redirect) → *Create* → **Download JSON**.

6. Rename the download (e.g. `client_secret_....json`) to exactly
   **`credentials.json`** and move it to the project root, next to
   `requirements.txt`.

> `credentials.json` and `token.json` are both gitignored. Do not paste the
> contents of either into a chat, an issue, or a commit.

### 10b. Install the Google libraries

```powershell
pip install google-api-python-client google-auth-oauthlib
```

### 10c. Authorize and run the first sync

```powershell
python -m subs.gmail                              # readiness check, no browser
python -m subs.cli sync --source gmail --dry-run  # what it would scan + cost estimate
python -m subs.cli sync --source gmail            # the real backfill
```

The first real run opens a browser for consent. Google will warn that the app
isn't verified — expected for a personal Testing-mode app; choose *Advanced →
Go to (your app)*. **You approve the grant; the token is written to
`token.json` locally and no password is ever seen by this code.**

The backfill scans 12 months by default (`--months N` to change it) and uses
the Batch API — half price, usually done within the hour. Later syncs use
Gmail's `historyId` and only fetch what arrived since.

### 10d. Review and report

```powershell
python -m subs.cli review          # low-confidence extractions
python -m subs.cli confirm 3       # keep one
python -m subs.cli reject 4        # drop one
python -m subs.cli report          # writes vault/30-Reports/subscriptions-<date>.md
```

The HUD's **SUBS** tab shows the same data, with keep/drop buttons for the
review queue.

### What this can and cannot do

| | |
|---|---|
| Scope requested | `gmail.readonly` — read only |
| Can it send/delete/modify mail? | No. The scope does not permit it. |
| Can it cancel a subscription? | **No.** It tells you what to cancel and when it renews; you cancel it. |
| Where do secrets live? | `credentials.json` + `token.json`, both gitignored |
| Cost of a 12-month backfill | ~$11 one-time via Batch API, then pennies/month |

---

## 11. Sign in to the Claude CLI (needed for the HUD command deck)

The CLI is installed and the HUD is wired to it, but it isn't signed in — the
command deck buttons currently return "Claude CLI is not signed in".

**One command, once:**

```powershell
claude
```

That opens an interactive session; type `/login` and follow the browser flow.
The credential is stored on disk, so the HUD picks it up from then on and you
never repeat this. **This uses your Claude subscription — no per-run API cost.**

**Alternative — bill API credits instead.** If you'd rather use the
`ANTHROPIC_API_KEY` already in `.env`, set this before starting the HUD:

```powershell
$env:VAULT_CLI_USE_API_KEY = "1"
uvicorn hud.server:app --port 8550
```

Each button press then costs API credits. The subscription route is cheaper for
regular use; the key route is better for unattended/scheduled runs.

**Verify:**

```powershell
claude -p "reply with exactly: cli ok"
```

Then press a command-deck button in the HUD — it shows elapsed seconds while
running and the result when done.

### How the command deck is wired

`hud/runner.py` spawns the CLI as a background job; the browser polls
`/api/run-command/{job_id}` because a skill can take minutes. Controls worth
knowing about:

- **Fixed allowlist** — `runner.COMMANDS` maps a button key to a hardcoded
  prompt. Nothing the browser sends reaches the command line.
- **No shell** — arguments are passed as a list, never interpolated.
- **Scoped tools** — `--allowedTools` grants Read/Write/Edit/Glob/Grep/WebSearch
  plus Bash narrowed to `python *`. Anything else is denied rather than
  prompting, since a prompt in headless mode would hang forever.
- **10-minute timeout**, then the process is killed.
- **Localhost only** — do not bind the HUD to `0.0.0.0` with this enabled; it
  starts a process with write access to the project.

To add a button: add an entry to `runner.COMMANDS` and a `<button class="cmd-btn"
data-cmd="...">` in `hud/static/index.html`.

---

## 12. Claude Code skills test

```powershell
# From a terminal (works independently of the HUD):
claude "/morning"
# Should fire the morning routine: trend scan → inbox check → plan today
```

---

## Summary — current status

| Feature | Status |
|---------|--------|
| Voice loop (text mode) | ✅ Verified — routes commands, returns local responses |
| Router (regex + skill matching) | ✅ Verified — all three paths classify correctly |
| HUD dashboard | ✅ Verified — serves mock data, orb animates, buttons fire stubs |
| STT on GPU | ✅ Verified — `cuda` / float16 on the RTX 3050 |
| Skills (SKILL.md files) | ✅ Present — Claude Code reads them on demand |
| Trend scan script | ✅ Works — returns mock data (step: wire real APIs) |
| TTS (text-to-speech) | ⬜ Needs model files (step 4) + espeak-ng (step 3) |
| Haiku routing | ⬜ Needs `ANTHROPIC_API_KEY` in `.env` (step 5) |
| Mic input | ⬜ Needs audio test (step 7); `pip install keyboard` for push-to-talk |
| Real metrics | ⬜ Needs YouTube/IG API keys (step 5, optional) |
| Claude CLI wiring | ✅ Verified — background jobs, polling, allowlist, timeout |
| Claude CLI sign-in | ⬜ Run `claude` then `/login` once (step 11) |
| Subscription tracker (fixtures) | ✅ Verified — 7/7 extracted correctly, dedupe + overlap working |
| Subscription tracker (real Gmail) | ⬜ Needs Google Cloud OAuth client (step 10) |
