from io import BytesIO

import pytest
from pypdf import PdfWriter

from handwerk.classify import MockLLM, ProviderUnavailable, Sorter
from handwerk.pdf import MAX_BYTES, MAX_PAGES, InvalidPdf, PdfTooLarge, extract

ENGINE = Sorter(MockLLM())


def pdf_bytes(*, pages=1, encrypted=False):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    if encrypted:
        writer.encrypt("local-test-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_extracts_text_from_real_reportlab_pdf(invoice):
    assert "Rechnung" in extract(invoice)
    assert "123,45" in extract(invoice)


def test_blank_pdf_reaches_review():
    text = extract(pdf_bytes())
    assert text == ""
    result = ENGINE.classify(text)
    assert result.needs_review and result.prediction.document_type == "unbekannt"


@pytest.mark.parametrize(("data", "error", "message"), [
    (b"not a PDF", InvalidPdf, "PDF file is required"),
    (b"%PDF-1.4\nmalformed", InvalidPdf, "could not be read"),
    (b"x" * (MAX_BYTES + 1), PdfTooLarge, "2 MB"),
])
def test_invalid_or_large_pdf(data, error, message):
    with pytest.raises(error, match=message):
        extract(data)


def test_rejects_encryption_empty_pdf_and_too_many_pages():
    with pytest.raises(InvalidPdf, match="Encrypted"):
        extract(pdf_bytes(encrypted=True))
    with pytest.raises(InvalidPdf, match="no pages"):
        extract(pdf_bytes(pages=0))
    with pytest.raises(PdfTooLarge, match="page limit"):
        extract(pdf_bytes(pages=MAX_PAGES + 1))


@pytest.mark.parametrize(("heading", "kind"), [
    ("Rechnung", "rechnung"), ("LIEFERSCHEIN", "lieferschein"),
    ("  Angebot ", "angebot"), ("Mahnung", "mahnung"),
])
def test_rules_classify_exact_headings_before_backend(heading, kind):
    class NeverCall:
        def classify(self, _text):
            raise AssertionError("rules should classify before provider")

    result = Sorter(NeverCall()).classify(f"Synthetischer Test\n{heading}\nText")
    assert (result.prediction.document_type, result.prediction.confidence, result.engine) == (
        kind, 0.97, "rules",
    )
    assert not result.needs_review


@pytest.mark.parametrize(("text", "kind"), [
    ("Leistungsabrechnung und Bruttobetrag", "rechnung"),
    ("Empfangsbestätigung am Übergabeort", "lieferschein"),
    ("Kostenvoranschlag mit Bindefrist", "angebot"),
    ("Zahlungserinnerung zu offenem Posten", "mahnung"),
])
def test_mock_handles_aliases_deterministically(text, kind):
    first = ENGINE.classify(text)
    assert first == ENGINE.classify(text)
    assert first.prediction.document_type == kind and first.engine == "mock"
    assert not first.needs_review


@pytest.mark.parametrize(("text", "kind", "score"), [
    ("Neue Unterlage", "unbekannt", .15),
    ("Rechnung\nMahnung\nBindefrist und offener Posten", "unbekannt", .45),
    ("Steuerbeleg und Rechnungsbetrag, Hinweis auf Bindefrist", "rechnung", .65),
    ("Rechnungsbetragssumme", "unbekannt", .15),
])
def test_ambiguous_or_missing_text_is_flagged(text, kind, score):
    result = ENGINE.classify(text)
    assert (result.prediction.document_type, result.prediction.confidence) == (kind, score)
    assert result.needs_review


@pytest.mark.parametrize("problem", [
    ProviderUnavailable(), TimeoutError(), {"document_type": "invalid", "confidence": .4},
    {"document_type": "rechnung", "confidence": float("inf"), "reason": "Invalid score"},
])
def test_provider_failure_uses_reviewable_rules_fallback(problem):
    class BrokenAdapter:
        def classify(self, _text):
            if isinstance(problem, Exception):
                raise problem
            return problem

    result = Sorter(BrokenAdapter()).classify("Hier ist ein Hinweis zur Rechnung.")
    assert (result.prediction.document_type, result.prediction.confidence, result.engine) == (
        "rechnung", .6, "fallback",
    )
    assert result.needs_review


def test_custom_adapter_is_pluggable():
    class Adapter:
        def classify(self, _text):
            return {"document_type": "angebot", "confidence": .8, "reason": "Custom test"}

    result = Sorter(Adapter(), "test").classify("Generischer Text")
    assert result.prediction.document_type == "angebot"
    assert result.engine == "test"
    assert not result.needs_review
