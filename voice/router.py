"""Voice command router.

Routes transcribed text by cost:
  1. Regex — instant, free (local commands)
  2. Keyword skill match — maps to a Claude Code skill
  3. Haiku — cheap Claude call for anything that needs reasoning

TODO (HANDOFF): Fill in ANTHROPIC_API_KEY in .env for Haiku routing.
"""

import os
import re

REGEX_ROUTES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"\b(stop|cancel|never\s?mind|abort)\b", re.I), "local", "abort"),
    (re.compile(r"\b(thanks?|thank\s?you)\b", re.I), "local", "acknowledge"),
    (re.compile(r"\bwhat\s+time\b", re.I), "local", "time"),
    (re.compile(r"\b(hello|hi|hey)\s*(jarvis)?\b", re.I), "local", "greet"),
]

SKILL_ROUTES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(trend|trending|what'?s\s+hot|morning\s+scan)\b", re.I), "morning-trend-scan"),
    (re.compile(r"\b(weekly|week\s+in\s+review|status\s+update)\b", re.I), "weekly-status-writer"),
    (re.compile(r"\b(plan\s+today|daily\s+plan|what'?s\s+on\s+today|priorities)\b", re.I), "plan-today"),
]


def route(text: str) -> tuple[str, str]:
    """Route text to a handler. Returns (route_type, value).

    route_type is one of: "local", "skill", "haiku"
    value is the command/skill name/original text.
    """
    t = text.strip()
    if not t:
        return ("local", "empty")

    for pattern, route_type, command in REGEX_ROUTES:
        if pattern.search(t):
            return (route_type, command)

    for pattern, skill_name in SKILL_ROUTES:
        if pattern.search(t):
            return ("skill", skill_name)

    return ("haiku", t)


def handle_local(command: str) -> str:
    """Handle commands that don't need any model."""
    import datetime

    handlers = {
        "abort": "Cancelled.",
        "acknowledge": "You're welcome.",
        "time": f"It's {datetime.datetime.now().strftime('%I:%M %p')}.",
        "greet": "Hello! What can I do for you?",
        "empty": "I didn't catch that.",
    }
    return handlers.get(command, f"Unknown local command: {command}")


async def handle_haiku(text: str) -> str:
    """Send text to Claude Haiku for cheap reasoning.

    Returns the response text, or a stub message if the API key is missing.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return f"[haiku-stub] Would send to Haiku: {text}"

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": text}],
        )
        return response.content[0].text
    except Exception as e:
        return f"[haiku-error] {e}"


if __name__ == "__main__":
    tests = [
        "what's trending today",
        "stop",
        "what time is it",
        "plan today",
        "tell me about quantum computing",
        "weekly status",
        "hello jarvis",
    ]
    for t in tests:
        r = route(t)
        print(f"  {t!r:45s} → {r}")
