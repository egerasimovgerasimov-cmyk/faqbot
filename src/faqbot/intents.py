"""Small-talk intents that are handled before the knowledge base search.

A greeting, a thank-you or a request for a human should not be scored against
FAQ entries: "привет" has nothing in common with "сколько стоит путёвка".
Patterns are deliberately short and bounded by text length, so a real question
that happens to start with «привет» still reaches the matcher.
"""

from __future__ import annotations

import re

from .text import normalize

#: (intent, pattern, max normalised length). Length is in characters, not words:
#: «здравствуйте, а сколько стоит путёвка» must not be treated as a greeting.
_PATTERNS: tuple[tuple[str, re.Pattern[str], int], ...] = (
    (
        "human",
        re.compile(
            r"оператор|живо(й|го)\s+человек|позов(и|ите)\s+(живого\s+)?человек|"
            r"связаться\s+с\s+человеком|нужен\s+человек|менеджер|специалист|"
            r"хочу\s+к\s+человеку|поговорить\s+с\s+человеком|пообщаться\s+с\s+человеком|"
            r"talk\s+to\s+a\s+human|real\s+person|human\s+support"
        ),
        90,
    ),
    (
        "greeting",
        re.compile(
            r"^(привет|приветик|здравствуй(те)?|добрый\s+(день|вечер)|доброе\s+утро|хай|ку|"
            r"hi|hello|hey)\b"
        ),
        40,
    ),
    (
        "thanks",
        re.compile(r"^(спасибо|благодарю|спс|благодарствую|спасибо\s+большое|thanks|thank\s+you)\b"),
        45,
    ),
    (
        "goodbye",
        re.compile(r"^(пока|до\s+свидания|до\s+встречи|всего\s+доброго|бай|bye|goodbye)\b"),
        40,
    ),
    (
        "identity",
        re.compile(
            r"кто\s+ты|как\s+тебя\s+зовут|ты\s+бот|ты\s+человек|расскажи\s+о\s+себе|"
            r"who\s+are\s+you|are\s+you\s+a\s+bot"
        ),
        120,
    ),
    (
        "capabilities",
        re.compile(
            r"что\s+(ты\s+)?умеешь|чем\s+(ты\s+)?можешь\s+помочь|как\s+(тобой\s+)?"
            r"пользоваться|твои\s+возможности|какие\s+вопросы|what\s+can\s+you\s+do"
        ),
        120,
    ),
)


def detect_intent(message: str) -> str | None:
    """Return an intent name or ``None`` when the message needs a search."""
    text = normalize(message)
    if not text:
        return None
    for intent, pattern, max_length in _PATTERNS:
        if len(text) <= max_length and pattern.search(text):
            return intent
    return None
