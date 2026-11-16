"""Knowledge base model and loader.

A knowledge base is a single YAML (or JSON) file:

.. code-block:: yaml

    bot:
      name: Sunny
      greeting: Hi! Ask me anything about the camp.
      fallback: I could not find an answer. Please contact a human.
      threshold: 0.45

    synonyms:
      - "путёвка = тур, поездка"

    quick:
      - label: Prices
        query: How much does a ticket cost?

    qa:
      - question: How much does a ticket cost?
        answer: Tickets cost ...
        keywords: price, cost
        category: Prices
        priority: 5
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .text import SynonymMap


class KnowledgeBaseError(ValueError):
    """Raised when a knowledge base cannot be loaded or is invalid."""


@dataclass(frozen=True)
class QaItem:
    id: int
    question: str
    answer: str
    keywords: str = ""
    category: str = ""
    priority: int = 0

    @property
    def search_text(self) -> str:
        return f"{self.question} {self.keywords}".strip()

    @classmethod
    def from_dict(cls, data: dict[str, Any], fallback_id: int) -> QaItem:
        if not isinstance(data, dict):
            raise KnowledgeBaseError("Each QA entry must be a mapping")
        question = str(data.get("question") or data.get("q") or "").strip()
        answer = str(data.get("answer") or data.get("a") or "").strip()
        if not question:
            raise KnowledgeBaseError("QA entry is missing 'question'")
        if not answer:
            raise KnowledgeBaseError(f"QA entry {question!r} is missing 'answer'")
        return cls(
            id=int(data.get("id", fallback_id)),
            question=question,
            answer=answer,
            keywords=str(data.get("keywords", data.get("k", "")) or ""),
            category=str(data.get("category") or data.get("c", "") or ""),
            priority=int(data.get("priority", data.get("p", 0)) or 0),
        )


@dataclass(frozen=True)
class QuickReply:
    label: str
    query: str = ""
    url: str = ""

    def to_dict(self) -> dict[str, str]:
        data = {"label": self.label}
        if self.query:
            data["query"] = self.query
        if self.url:
            data["url"] = self.url
        return data


@dataclass(frozen=True)
class Settings:
    bot_name: str = "FAQ bot"
    greeting: str = "Hi! Ask me a question and I will look it up in the knowledge base."
    fallback: str = (
        "I could not find an answer to that. Try rephrasing the question "
        "or contact a human."
    )
    threshold: float = 0.45
    clarify_gap: float = 0.06
    clarify_enabled: bool = True
    operator_label: str = "Talk to a human"
    operator_url: str = ""
    help_text: str = ""
    quick: tuple[QuickReply, ...] = ()
    replies: dict[str, str] = field(default_factory=dict)

    def reply(self, intent: str, default: str) -> str:
        return self.replies.get(intent) or default


@dataclass(frozen=True)
class KnowledgeBase:
    items: tuple[QaItem, ...]
    settings: Settings
    synonyms: SynonymMap
    source: Path | None = None

    def by_id(self, qa_id: int) -> QaItem | None:
        for item in self.items:
            if item.id == qa_id:
                return item
        return None

    def categories(self) -> list[str]:
        return sorted({item.category for item in self.items if item.category})

    def popular(self, limit: int = 3) -> list[QaItem]:
        ranked = sorted(self.items, key=lambda item: (-item.priority, item.id))
        return ranked[:limit]

    def validate(self) -> list[str]:
        """Return human-readable warnings (not fatal errors)."""
        warnings: list[str] = []
        seen_ids: set[int] = set()
        seen_questions: dict[str, int] = {}

        for item in self.items:
            if item.id in seen_ids:
                warnings.append(f"duplicate QA id: {item.id}")
            seen_ids.add(item.id)

            key = item.question.strip().lower()
            if key in seen_questions:
                warnings.append(
                    f"duplicate question {item.question!r} "
                    f"(ids {seen_questions[key]} and {item.id})"
                )
            seen_questions[key] = item.id

            if len(item.answer) > 4000:
                warnings.append(f"QA {item.id}: answer is longer than 4000 characters")

        if not 0.0 <= self.settings.threshold <= 1.0:
            warnings.append("threshold must be between 0 and 1")

        return warnings


def _settings_from_dict(data: dict[str, Any], quick: Sequence[QuickReply]) -> Settings:
    defaults = Settings()
    return Settings(
        bot_name=str(data.get("name", defaults.bot_name)),
        greeting=str(data.get("greeting", defaults.greeting)),
        fallback=str(data.get("fallback", defaults.fallback)),
        threshold=float(data.get("threshold", defaults.threshold)),
        clarify_gap=float(data.get("clarify_gap", defaults.clarify_gap)),
        clarify_enabled=bool(data.get("clarify_enabled", defaults.clarify_enabled)),
        operator_label=str(data.get("operator_label", defaults.operator_label)),
        operator_url=str(data.get("operator_url", defaults.operator_url)),
        help_text=str(data.get("help_text", defaults.help_text)),
        quick=tuple(quick),
        replies={
            str(key): str(value)
            for key, value in dict(data.get("replies") or {}).items()
        },
    )


def _quick_from_list(raw: Iterable[Any] | None) -> list[QuickReply]:
    quick: list[QuickReply] = []
    for entry in raw or ():
        if isinstance(entry, str):
            quick.append(QuickReply(label=entry, query=entry))
        elif isinstance(entry, dict) and entry.get("label"):
            quick.append(
                QuickReply(
                    label=str(entry["label"]),
                    query=str(entry.get("query", "") or ""),
                    url=str(entry.get("url", "") or ""),
                )
            )
    return quick


def parse_kb(data: dict[str, Any], source: Path | None = None) -> KnowledgeBase:
    if not isinstance(data, dict):
        raise KnowledgeBaseError("Knowledge base root must be a mapping")

    raw_items = data.get("qa") or data.get("items") or []
    if not isinstance(raw_items, list):
        raise KnowledgeBaseError("'qa' must be a list")

    items: list[QaItem] = []
    next_id = 1
    for entry in raw_items:
        item = QaItem.from_dict(entry, fallback_id=next_id)
        items.append(item)
        next_id = max(next_id, item.id) + 1

    if not items:
        raise KnowledgeBaseError("Knowledge base has no QA entries")

    synonyms_raw = data.get("synonyms") or []
    if isinstance(synonyms_raw, dict):
        lines = [f"{key} = {value}" for key, value in synonyms_raw.items()]
    else:
        lines = [str(line) for line in synonyms_raw]

    return KnowledgeBase(
        items=tuple(items),
        settings=_settings_from_dict(dict(data.get("bot") or {}), _quick_from_list(data.get("quick"))),
        synonyms=SynonymMap.from_lines(lines),
        source=source,
    )


def load_kb(path: str | Path) -> KnowledgeBase:
    """Load a knowledge base from YAML or JSON, using the file suffix."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise KnowledgeBaseError(f"cannot read {path}: {exc}") from exc

    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise KnowledgeBaseError(f"{path}: invalid JSON: {exc}") from exc
    else:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise KnowledgeBaseError(
                "PyYAML is required to read YAML knowledge bases: pip install pyyaml"
            ) from exc
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise KnowledgeBaseError(f"{path}: invalid YAML: {exc}") from exc

    kb = parse_kb(data, source=path)
    return kb
