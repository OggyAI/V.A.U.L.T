# V.A.U.L.T.

Voice-Activated Unified Logic Terminal — a voice-driven, local-first AI command center built on Claude Code.

## Architecture

Five layers: Brain (skills) → Memory (Obsidian vault) → Voice (local STT/TTS) → Face (HUD dashboard) → Handoff (repo packaging).

## Stack

- **Python 3.11/3.12** — voice pipeline, HUD server, scripts
- **faster-whisper** — STT (CUDA on RTX 3050, auto-falls back to CPU)
- **Kokoro-ONNX** — TTS (CPU, Apache-2.0, ~327 MB model)
- **FastAPI + Uvicorn** — HUD backend
- **Claude Code** — skill orchestration, reasoning
- **Obsidian / plain markdown** — long-term memory

## Key paths

| What | Path |
|------|------|
| Skills | `.claude/skills/<name>/SKILL.md` |
| Agents | `.claude/agents/` |
| Commands | `.claude/commands/` |
| Voice pipeline | `voice/` |
| HUD dashboard | `hud/` (server.py + static/) |
| Vault template | `vault.example/` |
| Live vault | `vault/` (gitignored, user-local) |
| Architecture doc | `docs/PLAN.md` |

## Conventions

- Skill folders must contain exactly `SKILL.md`. The `description` frontmatter drives selection — pack it with trigger words.
- Skills write output to `vault/30-Reports/` with `[[wikilinks]]`.
- Voice routes by cost: regex → local → Haiku.
- Secrets live in `.env` (gitignored). Never hardcode keys in skills.
- HUD reads `hud/status.json` and `hud/metrics.json` (gitignored, written at runtime).
