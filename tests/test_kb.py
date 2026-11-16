import json
from pathlib import Path

import pytest

from faqbot.kb import KnowledgeBaseError, load_kb, parse_kb

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_load_camp_example():
    kb = load_kb(EXAMPLES / "camp" / "kb.yaml")
    assert len(kb.items) >= 20
    assert kb.settings.bot_name == "Солнышко"
    assert "Путёвки" in kb.categories()
    assert kb.by_id(1).question == "Сколько стоит путёвка?"


def test_load_english_example():
    kb = load_kb(EXAMPLES / "support" / "kb.en.yaml")
    assert kb.settings.bot_name == "Acme Helper"
    assert len(kb.items) == 10


def test_ids_are_assigned_automatically():
    kb = parse_kb({"qa": [{"question": "A?", "answer": "a"}, {"question": "B?", "answer": "b"}]})
    assert [item.id for item in kb.items] == [1, 2]


def test_duplicate_warnings():
    kb = parse_kb(
        {
            "qa": [
                {"id": 1, "question": "A?", "answer": "a"},
                {"id": 1, "question": "A?", "answer": "a"},
            ]
        }
    )
    warnings = kb.validate()
    assert any("duplicate QA id" in warning for warning in warnings)
    assert any("duplicate question" in warning for warning in warnings)


def test_missing_answer_is_an_error():
    with pytest.raises(KnowledgeBaseError, match="missing 'answer'"):
        parse_kb({"qa": [{"question": "A?"}]})


def test_empty_knowledge_base_is_an_error():
    with pytest.raises(KnowledgeBaseError, match="no QA entries"):
        parse_kb({"qa": []})


def test_json_knowledge_base(tmp_path):
    path = tmp_path / "kb.json"
    path.write_text(
        json.dumps({"qa": [{"question": "Q?", "answer": "A"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    kb = load_kb(path)
    assert kb.items[0].answer == "A"


def test_invalid_yaml_reports_path(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("qa: [", encoding="utf-8")
    with pytest.raises(KnowledgeBaseError, match="invalid YAML"):
        load_kb(path)
