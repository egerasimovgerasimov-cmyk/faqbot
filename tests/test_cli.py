from pathlib import Path

from faqbot.cli import main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
KB = str(EXAMPLES / "camp" / "kb.yaml")


def test_ask_prints_answer(capsys):
    assert main(["--kb", KB, "ask", "сколько стоит путёвка"]) == 0
    out = capsys.readouterr().out
    assert "Стоимость зависит от смены" in out
    assert "score=1.00" in out


def test_ask_json(capsys):
    assert main(["--kb", KB, "ask", "есть ли бассейн", "--json"]) == 0
    out = capsys.readouterr().out
    assert '"qa_id": 17' in out
    assert '"intent": "answer"' in out


def test_search_prints_scores(capsys):
    assert main(["--kb", KB, "search", "документы", "-n", "2"]) == 0
    out = capsys.readouterr().out
    assert "#10" in out


def test_validate_ok(capsys):
    assert main(["--kb", KB, "validate", "--strict"]) == 0
    out = capsys.readouterr().out
    assert "OK: 25 QA entries" in out


def test_missing_kb_returns_error(tmp_path, capsys):
    assert main(["--kb", str(tmp_path / "nope.yaml"), "ask", "hello"]) == 2
    assert "cannot read" in capsys.readouterr().err
