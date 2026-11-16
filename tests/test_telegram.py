from pathlib import Path

from faqbot import Bot, load_kb
from faqbot.telegram import ChatStore, _chunk, handle

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def make():
    return Bot(load_kb(EXAMPLES / "camp" / "kb.yaml")), ChatStore()


def test_question_reply_has_text_and_buttons():
    bot, store = make()
    replies = handle(bot, store, 1, "сколько стоит путёвка")
    assert len(replies) == 1
    assert "Стоимость" in replies[0].text
    assert 0 < len(replies[0].buttons) <= 5
    assert store.button(1, 0) is not None


def test_help_command():
    bot, store = make()
    replies = handle(bot, store, 2, "/help")
    assert "Commands" in replies[0].text
    assert replies[0].buttons


def test_reset_command_clears_context():
    bot, store = make()
    handle(bot, store, 3, "Какие смены есть в 2026 году?")
    handle(bot, store, 3, "/reset")
    assert store.session(3).questions == []


def test_unknown_command_is_treated_as_question():
    bot, store = make()
    replies = handle(bot, store, 4, "/unknown")
    assert replies[0].text


def test_long_answers_are_split():
    chunks = _chunk("x" * 9000)
    assert len(chunks) == 3
    assert "".join(chunks) == "x" * 9000
