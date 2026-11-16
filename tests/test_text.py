from faqbot.text import SynonymMap, normalize, stem, tokenize


def test_normalize_strips_punctuation_and_yo():
    assert normalize("  Где ЛАГЕРЬ? Тут — «Кристалл»!  ") == "где лагерь тут кристалл"
    assert normalize("Путёвка, ПУТЕВКА!") == "путевка путевка"
    assert normalize("") == ""


def test_stem_keeps_short_words():
    assert stem("дом") == "дом"
    assert stem("кот") == "кот"
    assert stem("уже") == "уже"


def test_stem_groups_russian_inflections():
    assert stem("путёвки") == stem("путёвка") == stem("путёвок") == "путев"
    assert stem("документы") == stem("документов") == "документ"


def test_tokenize_drops_stopwords_and_counts():
    tokens = tokenize("Сколько стоит путёвка и путёвки?")
    assert tokens["сколь"] == 1
    assert tokens["путев"] == 2
    assert "и" not in tokens


def test_synonyms_collapse_variants():
    synonyms = SynonymMap.from_lines(["путёвка = тур, поездка, путевка"])
    tokens = tokenize("Сколько стоит тур и поездка?", synonyms)
    assert tokens["путев"] == 2


def test_synonym_lines_are_validated():
    synonyms = SynonymMap.from_lines(["", "no equals sign", "цена = стоимость, прайс"])
    assert synonyms.canonical("стоимост") == "цен"
