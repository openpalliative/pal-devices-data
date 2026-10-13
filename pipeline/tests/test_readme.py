from pipeline import readme


def test_readme_numbers_follow_data(root, monkeypatch):
    monkeypatch.delenv("OP_FIXTURES", raising=False)
    text = (root / "README.md").read_text(encoding="utf-8")
    assert readme.render(root, text) == text, "числа в README.md разошлись с данными: uv run python -m pipeline.readme"


def test_plural():
    assert readme.plural(1, "документ", "документа", "документов") == "1 документ"
    assert readme.plural(4, "документ", "документа", "документов") == "4 документа"
    assert readme.plural(11, "документ", "документа", "документов") == "11 документов"
    assert readme.plural(22, "документ", "документа", "документов") == "22 документа"
