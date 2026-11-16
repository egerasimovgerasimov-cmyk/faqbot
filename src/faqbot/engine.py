"""Matching engine: scores a question against the knowledge base.

The algorithm is intentionally transparent:

1. Both the question and the user message are reduced to a bag of stems.
2. Each user stem gets an IDF weight: rare words matter more.
3. Coverage of the user message and coverage of the knowledge-base question
   are combined with a bonus for exact/substring matches.
4. Near-duplicate top answers trigger a clarifying question instead of a
   random guess; a weak match falls back with suggested topics.

No embeddings, no API keys and no network access are involved.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .intents import detect_intent
from .kb import KnowledgeBase, QaItem, QuickReply, Settings
from .text import normalize, tokenize

#: Below this score a match is treated as noise.
NOISE_FLOOR = 0.08


@dataclass(frozen=True)
class Match:
    item: QaItem
    score: float


@dataclass(frozen=True)
class Answer:
    intent: str
    text: str
    matched: bool
    qa_id: int = 0
    score: float = 0.0
    quick: tuple[QuickReply, ...] = ()
    related: tuple[QaItem, ...] = ()
    suggestions: tuple[QaItem, ...] = ()
    used_context: bool = False

    def to_dict(self) -> dict:
        return {
            "answer": self.text,
            "matched": self.matched,
            "intent": self.intent,
            "qa_id": self.qa_id,
            "score": round(self.score, 4),
            "quick": [chip.to_dict() for chip in self.quick],
            "related": [item.question for item in self.related],
            "suggestions": [item.question for item in self.suggestions],
            "used_context": self.used_context,
        }


@dataclass
class ChatSession:
    """Per-visitor dialogue state used for follow-up questions."""

    questions: list[str] = field(default_factory=list)
    last_qa_id: int = 0
    last_category: str = ""

    def remember(self, question: str, answer: Answer) -> None:
        self.questions.append(question)
        self.questions = self.questions[-2:]
        if answer.matched and answer.qa_id:
            self.last_qa_id = answer.qa_id
            if answer.related:
                self.last_category = answer.related[0].category
            elif answer.suggestions:
                self.last_category = answer.suggestions[0].category


@dataclass(frozen=True)
class _Target:
    item: QaItem
    normalized_question: str
    normalized_text: str
    tokens: dict[str, int]


class Bot:
    """Answers questions using one knowledge base."""

    def __init__(self, kb: KnowledgeBase):
        self.kb = kb
        self.settings: Settings = kb.settings
        self._synonyms = kb.synonyms
        self._targets: list[_Target] = [
            _Target(
                item=item,
                normalized_question=normalize(item.question),
                normalized_text=normalize(item.search_text),
                tokens=tokenize(item.search_text, self._synonyms),
            )
            for item in kb.items
        ]
        self._idf = self._build_idf()

    # -- scoring -----------------------------------------------------------
    def _build_idf(self) -> dict[str, float]:
        document_frequency: dict[str, int] = {}
        for target in self._targets:
            for token in target.tokens:
                document_frequency[token] = document_frequency.get(token, 0) + 1
        total = max(1, len(self._targets))
        return {
            token: math.log((total + 1) / (count + 1)) + 1
            for token, count in document_frequency.items()
        }

    @staticmethod
    def _fuzzy(left: str, right: str) -> float:
        """Similarity for typos: 0.3..1.0 for close words, else 0."""
        if left == right:
            return 1.0
        if len(left) < 5 or len(right) < 5 or abs(len(left) - len(right)) > 2:
            return 0.0
        percent = SequenceMatcher(None, left, right).ratio() * 100
        if percent >= 86:
            return (percent - 80) / 20
        return 0.0

    def find(
        self,
        query: str,
        limit: int = 4,
        category: str = "",
        exclude: tuple[int, ...] = (),
    ) -> list[Match]:
        query_norm = normalize(query)
        query_tokens = tokenize(query, self._synonyms)
        if not query_norm or not query_tokens:
            return []

        weights = {token: self._idf.get(token, 2.5) for token in query_tokens}
        total_weight = sum(weights.values())
        if total_weight <= 0:
            return []

        results: list[Match] = []

        for target in self._targets:
            if target.item.id in exclude:
                continue

            bonus = 0.0
            if query_norm == target.normalized_question:
                bonus = 1.0
            elif len(query_norm) >= 6 and query_norm in target.normalized_question:
                bonus = 0.85
            elif len(target.normalized_question) >= 8 and target.normalized_question in query_norm:
                bonus = 0.9
            elif len(query_norm) >= 8 and query_norm in target.normalized_text:
                bonus = 0.8

            matched_weight = 0.0
            user_hits = 0

            for token, weight in weights.items():
                if token in target.tokens:
                    matched_weight += weight
                    user_hits += 1
                    continue
                best = 0.0
                for candidate in target.tokens:
                    similarity = self._fuzzy(token, candidate)
                    if similarity > best:
                        best = similarity
                    if best >= 1.0:
                        break
                if best > 0:
                    matched_weight += weight * best * 0.85

            coverage_user = matched_weight / total_weight
            coverage_qa = user_hits / max(1, len(target.tokens))
            score = 0.62 * coverage_user + 0.23 * coverage_qa + 0.15 * bonus
            score += min(0.08, max(0, target.item.priority) * 0.008)
            if category and target.item.category == category:
                score += 0.05
            if bonus >= 1.0:
                score = 1.0

            score = max(0.0, min(1.0, score))
            if score > NOISE_FLOOR:
                results.append(Match(target.item, round(score, 4)))

        results.sort(key=lambda match: (-match.score, -match.item.priority))
        return results[:limit]

    # -- replies -----------------------------------------------------------
    def _operator_chip(self) -> QuickReply | None:
        if not self.settings.operator_url:
            return None
        return QuickReply(
            label=self.settings.operator_label,
            url=self.settings.operator_url,
        )

    @staticmethod
    def _question_chips(items, limit: int = 2) -> list[QuickReply]:
        return [
            QuickReply(label=item.question, query=item.question)
            for item in items[:limit]
        ]

    def _limit(self, chips: list[QuickReply | None], limit: int = 5) -> tuple[QuickReply, ...]:
        result: list[QuickReply] = []
        for chip in chips:
            if chip is not None and chip.label:
                result.append(chip)
            if len(result) >= limit:
                break
        return tuple(result)

    def _related(self, matches: list[Match], limit: int = 2) -> list[QaItem]:
        if not matches:
            return []
        top = matches[0]
        category = top.item.category
        related: list[QaItem] = []
        for match in matches[1:]:
            same_category = bool(category) and match.item.category == category
            if not same_category and match.score < 0.5:
                continue
            related.append(match.item)
            if len(related) >= limit:
                break
        return related

    def _intent_answer(self, intent: str) -> Answer:
        settings = self.settings
        name = settings.bot_name
        operator = settings.operator_url or "a human"

        defaults = {
            "greeting": settings.greeting,
            "thanks": "Glad to help! Ask me anything else.",
            "goodbye": "See you! Have a nice day.",
            "human": f"You can reach a human here: {operator}",
            "identity": (
                f"I am {name}, a keyword-based FAQ bot. "
                "I answer from a curated knowledge base, offline and without an LLM."
            ),
            "capabilities": (
                "I can answer questions about: "
                + (", ".join(self.kb.categories()) or "the topics in my knowledge base")
                + "."
            ),
        }

        text = settings.reply(intent, defaults.get(intent, settings.fallback))
        quick: list[QuickReply | None] = []
        if intent in {"greeting", "identity", "capabilities"}:
            quick.extend(QuickReply(label=chip.label, query=chip.query, url=chip.url) for chip in settings.quick)
            quick.extend(self._question_chips(self.kb.popular(2)))
        quick.append(self._operator_chip())

        return Answer(
            intent=intent,
            text=text,
            matched=False,
            score=1.0,
            quick=self._limit(quick),
        )

    def _should_clarify(self, matches: list[Match]) -> bool:
        if not self.settings.clarify_enabled or len(matches) < 2:
            return False
        top, second = matches[0], matches[1]
        if top.item.id == second.item.id or top.score >= 0.72:
            return False
        if second.score < self.settings.threshold - 0.03:
            return False
        return (top.score - second.score) < self.settings.clarify_gap

    def _answer_matches(self, matches: list[Match], used_context: bool) -> Answer:
        top = matches[0]
        quick: list[QuickReply | None] = []
        related = self._related(matches)
        quick.extend(self._question_chips(related))
        quick.append(self._operator_chip())
        return Answer(
            intent="answer",
            text=top.item.answer,
            matched=True,
            qa_id=top.item.id,
            score=top.score,
            quick=self._limit(quick),
            related=tuple(related),
            used_context=used_context,
        )

    def _clarify(self, matches: list[Match], used_context: bool) -> Answer:
        suggestions = [match.item for match in matches[: 3]]
        quick: list[QuickReply | None] = self._question_chips(suggestions, limit=3)
        quick.append(self._operator_chip())
        return Answer(
            intent="clarify",
            text="Could you clarify what exactly you are looking for?",
            matched=False,
            score=matches[0].score,
            quick=self._limit(quick),
            suggestions=tuple(suggestions),
            used_context=used_context,
        )

    def _fallback(self, matches: list[Match]) -> Answer:
        suggestions: list[QaItem] = []
        for match in matches:
            if match.score < 0.18:
                continue
            suggestions.append(match.item)
            if len(suggestions) >= 3:
                break
        if not suggestions:
            suggestions = self.kb.popular(3)

        quick: list[QuickReply | None] = self._question_chips(suggestions, limit=3)
        quick.append(self._operator_chip())
        return Answer(
            intent="fallback",
            text=self.settings.fallback,
            matched=False,
            score=matches[0].score if matches else 0.0,
            quick=self._limit(quick),
            suggestions=tuple(suggestions),
        )

    # -- public API --------------------------------------------------------
    def respond(self, session: ChatSession, message: str) -> Answer:
        """Answer one message, updating the session's dialogue context."""
        message = (message or "").strip()
        if not message:
            return Answer(
                intent="error",
                text="Please type a question.",
                matched=False,
            )

        intent = detect_intent(message)
        if intent:
            answer = self._intent_answer(intent)
            session.remember(message, answer)
            return answer

        category = session.last_category
        matches = self.find(message, limit=6, category=category)
        best = matches[0].score if matches else 0.0
        used_context = False

        if session.questions and best < 0.6 and is_followup(message):
            expanded = expand_query(message, session)
            more = self.find(
                expanded,
                limit=6,
                category=category,
                exclude=(session.last_qa_id,) if session.last_qa_id else (),
            )
            if (
                more
                and more[0].score >= self.settings.threshold
                and more[0].item.id != session.last_qa_id
                and (not matches or more[0].score > best + 0.03)
            ):
                matches = more
                best = more[0].score
                used_context = True

        if matches and best >= self.settings.threshold:
            answer = (
                self._clarify(matches, used_context)
                if self._should_clarify(matches)
                else self._answer_matches(matches, used_context)
            )
        else:
            answer = self._fallback(matches)

        session.remember(message, answer)
        return answer

    def ask(self, message: str) -> Answer:
        """One-off question without dialogue context."""
        return self.respond(ChatSession(), message)


def is_followup(message: str) -> bool:
    """True for short continuations like «а сколько дней?»."""
    from .text import normalize as _normalize
    from .text import tokenize as _tokenize

    text = _normalize(message)
    count = len(_tokenize(message))
    if count == 0:
        return True
    if count <= 2 and (
        text.startswith(("а ", "и ", "еще ", "ещё ", "ну ", "так ", "тогда "))
        or any(
            marker in text
            for marker in (
                "подробн",
                "расскаж",
                "сколько дней",
                "сколько лет",
                "сколько стоит",
                "а для",
                "про это",
                "об этом",
            )
        )
    ):
        return True
    return count <= 1


def expand_query(message: str, session: ChatSession) -> str:
    """Prepend the previous question(s) to a short follow-up."""
    parts: list[str] = []
    if session.questions:
        parts.append(session.questions[-1])
        if len(tokenize(message)) <= 1 and len(session.questions) > 1:
            parts.append(session.questions[-2])
    parts.append(message)

    seen: set[str] = set()
    unique: list[str] = []
    for part in parts:
        part = part.strip()
        if part and part not in seen:
            seen.add(part)
            unique.append(part)
    return " ".join(unique)
