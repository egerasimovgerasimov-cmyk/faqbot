"""faqbot — a small, offline FAQ chatbot.

The package has no mandatory dependencies beyond PyYAML: matching runs in
pure Python, and the API/Telegram adapters are optional extras.
"""

from .engine import Answer, Bot, ChatSession, Match
from .kb import KnowledgeBase, QaItem, QuickReply, Settings, load_kb
from .text import normalize, stem, tokenize

__version__ = "0.3.0"

__all__ = [
    "Answer",
    "Bot",
    "ChatSession",
    "KnowledgeBase",
    "Match",
    "QaItem",
    "QuickReply",
    "Settings",
    "load_kb",
    "normalize",
    "stem",
    "tokenize",
    "__version__",
]
