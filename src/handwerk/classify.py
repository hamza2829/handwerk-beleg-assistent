import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field, ValidationError

from .domain import DOCUMENT_LABELS, DocumentType

REVIEW_THRESHOLD = 0.80
HEADINGS = {label.casefold(): kind for kind, label in DOCUMENT_LABELS.items()
            if kind != "unbekannt"}
MOCK_CLUES: dict[DocumentType, tuple[str, ...]] = {
    "rechnung": ("steuerbeleg", "leistungsabrechnung", "rechnungsbetrag", "bruttobetrag"),
    "lieferschein": ("warenbegleitschein", "empfangsbestätigung", "gelieferte menge",
                     "übergabeort"),
    "angebot": ("kostenvoranschlag", "preisvorschlag", "bindefrist", "leistungsumfang"),
    "mahnung": ("zahlungserinnerung", "offener posten", "überfällig", "mahnbetrag"),
}
FALLBACK_CLUES: dict[DocumentType, tuple[str, ...]] = {
    "rechnung": ("rechnung", "steuerbeleg", "rechnungsbetrag"),
    "lieferschein": ("lieferschein", "warenbegleitschein", "gelieferte menge"),
    "angebot": ("angebot", "kostenvoranschlag", "preisvorschlag"),
    "mahnung": ("mahnung", "zahlungserinnerung", "überfällig"),
}


class Prediction(BaseModel):
    document_type: DocumentType
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    reason: str = Field(min_length=1, max_length=240)


@dataclass(frozen=True)
class Classification:
    prediction: Prediction
    engine: str

    @property
    def needs_review(self) -> bool:
        return (self.prediction.document_type == "unbekannt"
                or self.prediction.confidence < REVIEW_THRESHOLD)


class ProviderUnavailable(Exception):
    """An adapter can signal a recoverable provider error."""


class LLM(Protocol):
    def classify(self, text: str) -> Prediction | Mapping[str, object]: ...


def match_clues(text: str, vocabulary: dict[DocumentType, tuple[str, ...]]) -> Prediction:
    normalized = " ".join(text.casefold().split())
    ranked = sorted(
        ((sum(bool(re.search(r"(?<!\w)" + re.escape(clue) + r"(?!\w)", normalized))
              for clue in clues), kind) for kind, clues in vocabulary.items()),
        key=lambda match: -match[0],
    )
    (best, kind), (second, _), *_ = ranked
    if not best:
        return Prediction(document_type="unbekannt", confidence=0.15,
                          reason="Keine eindeutigen Texthinweise.")
    if best == second:
        return Prediction(document_type="unbekannt", confidence=0.45,
                          reason="Gleich starke Hinweise auf mehrere Belegarten.")
    if second:
        return Prediction(document_type=kind, confidence=0.65,
                          reason="Widersprüchliche Hinweise im Beleg.")
    return Prediction(document_type=kind, confidence=0.88,
                      reason="Passende Begriffe im Belegtext.")


class MockLLM:
    """A deterministic phrase matcher with the same interface as a provider."""

    def classify(self, text: str) -> Prediction:
        return match_clues(text, MOCK_CLUES)


class Sorter:
    def __init__(self, provider: LLM | None, name: str = "mock") -> None:
        self.provider = provider
        self.name = name

    def classify(self, text: str) -> Classification:
        lines = [line.strip().casefold() for line in text.splitlines() if line.strip()]
        headings = {HEADINGS[line] for line in lines[:6] if line in HEADINGS}
        if len(headings) == 1:
            kind = headings.pop()
            return Classification(Prediction(
                document_type=kind, confidence=0.97, reason="Eindeutige Überschrift im Belegkopf.",
            ), "rules")
        if self.provider is not None:
            try:
                return Classification(Prediction.model_validate(self.provider.classify(text)),
                                      self.name)
            except (ProviderUnavailable, TimeoutError, ValidationError):
                pass
        baseline = match_clues(text, FALLBACK_CLUES)
        return Classification(baseline.model_copy(
            update={"confidence": min(baseline.confidence, 0.60)},
        ), "fallback")
