from pathlib import Path

from faqbot import Bot, ChatSession, load_kb
from faqbot.engine import expand_query, is_followup
from faqbot.kb import parse_kb

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def camp_bot() -> Bot:
    return Bot(load_kb(EXAMPLES / "camp" / "kb.yaml"))


def test_exact_question_scores_one():
    answer = camp_bot().ask("Сколько стоит путёвка?")
    assert answer.intent == "answer"
    assert answer.matched
    assert answer.qa_id == 1
    assert answer.score == 1.0


def test_paraphrase_finds_the_right_entry():
    answer = camp_bot().ask("стоимость путёвки")
    assert answer.qa_id == 1


def test_typo_is_tolerated():
    answer = camp_bot().ask("путёка сколько стоит")
    assert answer.qa_id == 1
    assert answer.score > 0.5


def test_unrelated_question_falls_back():
    answer = camp_bot().ask("какая погода на Марсе")
    assert answer.intent == "fallback"
    assert not answer.matched
    assert answer.text


def test_small_talk_intents():
    bot = camp_bot()
    assert bot.ask("привет").intent == "greeting"
    assert bot.ask("спасибо").intent == "thanks"
    assert bot.ask("хочу поговорить с человеком").intent == "human"
    assert bot.ask("что ты умеешь").intent == "capabilities"


def test_followup_reaches_the_shorter_answer():
    bot = camp_bot()
    session = ChatSession()

    first = bot.respond(session, "Какие смены есть в 2026 году?")
    assert first.qa_id == 5

    second = bot.respond(session, "а сколько дней?")
    assert second.qa_id == 6
    assert second.intent == "answer"


def test_short_continuation_is_detected():
    assert is_followup("а сколько дней?")
    assert is_followup("подробнее")
    assert not is_followup("какие документы нужны для заезда")


def test_expand_query_prepends_the_previous_question():
    session = ChatSession()
    session.questions.append("Сколько стоит путёвка?")
    assert expand_query("а для второго ребёнка?", session).startswith(
        "Сколько стоит путёвка?"
    )


def test_clarification_when_two_answers_are_close():
    kb = parse_kb(
        {
            "bot": {"threshold": 0.45, "clarify_gap": 0.06},
            "qa": [
                {"id": 1, "question": "Как оплатить картой или наличными?", "answer": "Картой"},
                {"id": 2, "question": "Как оплатить переводом на счёт?", "answer": "Переводом"},
            ],
        }
    )
    answer = Bot(kb).ask("оплата")
    assert answer.intent == "clarify"
    assert len(answer.suggestions) == 2
    assert {item.id for item in answer.suggestions} == {1, 2}


def test_priority_breaks_score_ties():
    kb = parse_kb(
        {
            "qa": [
                {"id": 1, "question": "Где парковка?", "answer": "Слева", "priority": 0},
                {"id": 2, "question": "Где парковка?", "answer": "Справа", "priority": 9},
            ]
        }
    )
    answer = Bot(kb).ask("где парковка")
    assert answer.qa_id == 2


def test_empty_message_returns_error():
    answer = camp_bot().ask("   ")
    assert answer.intent == "error"
    assert not answer.matched


def test_exclude_skips_items():
    bot = camp_bot()
    matches = bot.find("путёвка", exclude=(1,))
    assert all(match.item.id != 1 for match in matches)


def test_english_knowledge_base():
    bot = Bot(load_kb(EXAMPLES / "support" / "kb.en.yaml"))
    assert bot.ask("how much does it cost").qa_id == 1
    assert bot.ask("cancel my plan").qa_id == 3
    assert bot.ask("what is the weather on Mars").intent == "fallback"
