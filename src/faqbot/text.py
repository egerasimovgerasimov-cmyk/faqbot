"""Text utilities: normalisation, light stemming and synonyms.

The matcher does not need a heavy NLP stack. For short questions ("сколько
стоит путёвка?") a normalised bag of stems plus IDF weights works well and
runs anywhere, offline and without a model download.

The stemmer is deliberately naive: it strips the most common Russian and
English inflectional suffixes. It is not linguistically perfect, but it keeps
"путёвка", "путёвки" and "путёвок" in the same bucket, which is all the
matcher needs.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)

#: Words that carry no meaning for matching. Kept small on purpose.
STOPWORDS: frozenset[str] = frozenset(
    ["и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как", "а", "то", "все", "она", "так", "его", "но", "да", "ты", "к", "у", "же", "вы", "за", "бы", "по", "только", "ее", "мне", "было", "вот", "от", "меня", "еще", "нет", "о", "из", "ему", "теперь", "когда", "даже", "ну", "вдруг", "ли", "если", "уже", "или", "ни", "быть", "был", "него", "до", "вас", "нибудь", "опять", "уж", "вам", "ведь", "там", "потом", "себя", "ничего", "ей", "может", "они", "тут", "где", "есть", "надо", "ней", "для", "мы", "тебя", "их", "чем", "была", "сам", "чтоб", "без", "будто", "чего", "раз", "тоже", "себе", "под", "будет", "тогда", "кто", "это", "этот", "того", "потому", "этого", "какой", "совсем", "ним", "здесь", "этом", "один", "почти", "мой", "тем", "чтобы", "нее", "сейчас", "были", "куда", "зачем", "всех", "никогда", "можно", "при", "наконец", "два", "об", "другой", "хоть", "после", "над", "больше", "тот", "через", "эти", "нас", "про", "всего", "них", "какая", "много", "разве", "три", "эту", "моя", "впрочем", "хорошо", "свою", "этой", "перед", "иногда", "лучше", "чуть", "том", "нельзя", "такой", "им", "более", "всегда", "конечно", "всю", "между", "пожалуйста", "подскажите", "подскажи", "скажите", "скажи", "расскажите", "расскажи", "покажите", "покажи", "дайте", "дай", "хочу", "хотел", "хотела", "узнать", "вопрос", "ответ", "привет", "здравствуйте", "добрый", "день", "вечер", "спасибо", "нужно", "нужен", "нужна", "интересует", "интересно", "вообще", "просто", "такое", "вроде", "точно", "a", "an", "the", "is", "are", "was", "were", "be", "been", "to", "of", "in", "on", "at", "for", "with", "and", "or", "but", "i", "you", "he", "she", "it", "we", "they", "me", "my", "your", "our", "this", "that", "these", "those", "do", "does", "did", "can", "could", "would", "should", "please", "hi", "hello", "thanks", "thank", "have", "has", "had", "how", "what", "when", "where", "which", "who", "why"]
)

#: Inflectional suffixes, longest first. A suffix is only stripped when at
#: least four characters remain, so "цена" stays "цена", not "ц".
SUFFIXES: tuple[str, ...] = tuple(
    sorted(
        ["иями", "ями", "ами", "ыми", "ими", "его", "ого", "ему", "ому", "ешь", "ишь", "ите", "ться", "тся", "ять", "ать", "ить", "еть", "ует", "ают", "яют", "ов", "ев", "ей", "ой", "ый", "ий", "ая", "яя", "ое", "ее", "ые", "ие", "ии", "ия", "ью", "ья", "ам", "ям", "ах", "ях", "ом", "ем", "ую", "юю", "ок", "ing", "ed", "es", "s", "а", "я", "о", "е", "ы", "и", "у", "ю", "ь"],
        key=len,
        reverse=True,
    )
)


def normalize(text: str) -> str:
    """Lowercase, replace ё with е and keep only letters and digits.

    >>> normalize("  Где ЛАГЕРЬ? Тут — «Кристалл»!  ")
    'где лагерь тут кристалл'
    """
    text = (text or "").lower().replace("ё", "е").replace("Ё", "Е")
    return " ".join(_WORD_RE.findall(text))


def stem(word: str) -> str:
    """Strip one common suffix from a word (see module docstring)."""
    word = normalize(word).split(" ")[0]
    if len(word) <= 3:
        return word
    for suffix in SUFFIXES:
        # A single letter may be dropped while three letters remain ("цена" ->
        # "цен"), longer endings need four ("день" stays "день").
        remaining = len(word) - len(suffix)
        if word.endswith(suffix) and remaining >= (3 if len(suffix) == 1 else 4):
            stripped = word[:remaining]
            # Russian has a к/ø alternation in this position: «путёвка» ->
            # «путёвк», «путёвок» -> «путёв». Drop the к so both meet.
            if len(stripped) > 4 and stripped.endswith("к"):
                stripped = stripped[:-1]
            return stripped
    return word


@dataclass(frozen=True)
class SynonymMap:
    """Maps word stems to a canonical stem, e.g. тур/поездка -> путевк."""

    mapping: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_lines(cls, lines: Iterable[str]) -> SynonymMap:
        """Parse lines like ``путёвка = тур, поездка, путевка``."""
        mapping: dict[str, str] = {}
        for raw in lines:
            line = (raw or "").strip()
            if not line or "=" not in line:
                continue
            canonical, variants = line.split("=", 1)
            canonical_stem = stem(normalize(canonical))
            if not canonical_stem:
                continue
            mapping[canonical_stem] = canonical_stem
            for variant in variants.split(","):
                variant_stem = stem(normalize(variant))
                if variant_stem:
                    mapping[variant_stem] = canonical_stem
        return cls(mapping)

    def canonical(self, word_stem: str) -> str:
        return self.mapping.get(word_stem, word_stem)


def tokenize(text: str, synonyms: SynonymMap | None = None) -> dict[str, int]:
    """Split text into meaningful stems with their frequency.

    >>> tokenize("Сколько стоит путёвка и путёвки?")
    {'сколь': 1, 'стоит': 1, 'путев': 2}
    """
    counts: dict[str, int] = {}
    for word in normalize(text).split():
        if len(word) < 2 or word in STOPWORDS:
            continue
        word_stem = stem(word)
        if len(word_stem) < 2:
            continue
        if synonyms is not None:
            word_stem = synonyms.canonical(word_stem)
        counts[word_stem] = counts.get(word_stem, 0) + 1
    return counts
