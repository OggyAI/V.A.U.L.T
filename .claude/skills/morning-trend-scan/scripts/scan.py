"""Trend scanner stub.

TODO: Replace with real data sources (YouTube trending API, Reddit, HN, X/Twitter).
Requires API keys in .env — see HANDOFF.md.

For now, returns mock data so the skill pipeline can be tested end-to-end.
"""

import json
import datetime

MOCK_TRENDS = [
    {
        "title": "Claude Code skills architecture goes viral",
        "source": "YouTube",
        "score": 95,
        "url": "",
    },
    {
        "title": "Local-first AI assistants gaining traction",
        "source": "Hacker News",
        "score": 88,
        "url": "",
    },
    {
        "title": "Kokoro TTS hits 1.0 — Apache-2.0 voice synthesis",
        "source": "GitHub",
        "score": 82,
        "url": "",
    },
    {
        "title": "Whisper.cpp adds Vulkan backend for AMD GPUs",
        "source": "Reddit",
        "score": 75,
        "url": "",
    },
    {
        "title": "Obsidian plugin ecosystem crosses 2000 plugins",
        "source": "Obsidian Forum",
        "score": 70,
        "url": "",
    },
]


def scan():
    return {
        "date": datetime.date.today().isoformat(),
        "source": "mock",
        "trends": MOCK_TRENDS,
    }


if __name__ == "__main__":
    print(json.dumps(scan(), indent=2))
