"""The bundle's declared language (profile 1.12): ``x_geo.language`` on
the root index, read by lexical retrieval for its stop words, by question
generation for the language it writes in, and by lint for its shape. A
localized view's language is its tag; an undeclared bundle keeps the
English defaults, so nothing that ranked before ranks differently."""

from okf_web import evaluator
from okf_web.linter import lint_bundle
from okf_web.model import language_primary, language_tag, load_bundle, localized_view

_INDEX = (
    "---\n"
    'okf_version: "0.2"\n'
    "title: Tienda de Montaña\n"
    "x_geo:\n"
    "  profile: ecommerce-geo/1.12\n"
    "  site: https://tienda.example\n"
    "{language}"
    "---\n\n# Tienda de Montaña\n\n* [Envíos](/faq/envios.md)\n"
)

_FAQ = (
    "---\n"
    "type: FAQ\n"
    "title: Preguntas de envío\n"
    "description: Respuestas sobre el envío de los pedidos a la península.\n"
    "tags: [faq, envios]\n"
    "status: stable\n"
    "x_geo:\n"
    "  risk: b\n"
    "---\n\n# ¿Cuánto tarda el envío?\n\nEnviamos a toda la península en dos días laborables.\n"
)


def _bundle(tmp_path, language=None):
    root = tmp_path / "bundle"
    (root / "faq").mkdir(parents=True)
    line = f"  language: {language}\n" if language is not None else ""
    (root / "index.md").write_text(_INDEX.format(language=line), encoding="utf-8")
    (root / "faq" / "envios.md").write_text(_FAQ, encoding="utf-8")
    return load_bundle(root)


def test_language_tag_normalization():
    assert language_tag("en") == "en"
    assert language_tag(" PT_BR ") == "pt-br"
    assert language_tag("zh-Hans") == "zh-hans"
    assert language_primary("pt-BR") == "pt"
    for bad in ("english", "e", "", None, "en US", "12"):
        assert language_tag(bad) == "", bad


def test_bundle_language_declared_undeclared_and_in_a_view(tmp_path):
    assert _bundle(tmp_path).language == ""
    declared = _bundle(tmp_path / "d", language="es")
    assert declared.declared_language == "es" and declared.language == "es"
    assert localized_view(declared, "pt-BR").language == "pt-br"
    assert localized_view(declared, "fr").language == "fr"


def test_lint_w043_for_a_malformed_tag_only(tmp_path):
    _, findings = lint_bundle(_bundle(tmp_path, language="Spanish").root)
    assert [(f.code, f.rel_path) for f in findings if f.code == "W043"] == [("W043", "index.md")]
    _, findings = lint_bundle(_bundle(tmp_path / "ok", language="es").root)
    assert not [f for f in findings if f.code == "W043"]
    _, findings = lint_bundle(_bundle(tmp_path / "none").root)
    assert not [f for f in findings if f.code == "W043"]


def test_stop_words_follow_the_language():
    # Undeclared: the historical English list, byte for byte.
    assert evaluator.stopwords_for("") is evaluator.STOPWORDS["en"]
    assert evaluator._tokens("tents for two people") == ["tents", "two", "people"]
    # Declared: the language's own list, in the tokenizer's folded spelling.
    assert evaluator._tokens("tienda de campaña para dos personas", "es") == [
        "tienda", "campana", "dos", "personas"]
    assert evaluator._tokens("ein Zelt für zwei Personen", "de-AT") == ["zelt", "zwei", "personen"]
    assert evaluator._tokens("l'adresse de la boutique", "fr") == ["adresse", "boutique"]
    # A declared language without a list drops nothing — never English noise.
    assert evaluator.stopwords_for("ja") == frozenset()
    assert evaluator._tokens("二人用のテント", "ja") == evaluator._tokens("二人用のテント")


def test_retrieval_uses_the_declared_language(tmp_path):
    undeclared = _bundle(tmp_path / "u")
    declared = _bundle(tmp_path / "d", language="es")
    # Spanish function words alone: nothing to match in a Spanish bundle...
    assert evaluator.retrieve(declared, "de la para con sobre") == []
    # ...but an undeclared bundle still treats them as informative words.
    assert evaluator.retrieve(undeclared, "de la para con sobre") != []
    # Content words retrieve either way.
    assert [c.rel_path for c in evaluator.retrieve(declared, "envío a la península")] == ["faq/envios.md"]


def test_question_generation_names_the_language(tmp_path):
    captured = {}

    class LLM:
        def complete(self, system, user, max_tokens=0):
            captured["system"], captured["user"] = system, user
            return "questions:\n  - {id: q1, archetype: discovery, question: '¿Envían a Canarias?'}\n"

    questions = evaluator.generate_questions(_bundle(tmp_path, language="es"), LLM())
    assert "LANGUAGE: es" in captured["user"] and "`LANGUAGE`" in captured["system"]
    assert [q.question for q in questions] == ["¿Envían a Canarias?"]
    evaluator.generate_questions(_bundle(tmp_path / "u"), LLM())
    assert "LANGUAGE: undeclared" in captured["user"]
