from dataclasses import dataclass
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

DocumentType = Literal["rechnung", "lieferschein", "angebot", "mahnung", "unbekannt"]
DocumentStatus = Literal["pruefen", "sortiert", "geprueft"]
JobStatus = Literal["offen", "in_arbeit", "abgeschlossen", "storniert"]

DOCUMENT_TYPES = get_args(DocumentType)
JOB_STATUSES = get_args(JobStatus)
JOB_ID = r"^[A-Z0-9][A-Z0-9-]{0,31}$"
DOCUMENT_LABELS = {
    "rechnung": "Rechnung", "lieferschein": "Lieferschein", "angebot": "Angebot",
    "mahnung": "Mahnung", "unbekannt": "Unbekannt",
}
JOB_LABELS = {
    "offen": "Offen", "in_arbeit": "In Arbeit", "abgeschlossen": "Abgeschlossen",
    "storniert": "Storniert",
}


@dataclass(frozen=True)
class Job:
    job_id: str
    customer: str
    status: JobStatus
    amount_cents: int


class JobView(BaseModel):
    job_id: str
    customer: str
    status: JobStatus
    amount_cents: int
    documents: int


class DocumentView(BaseModel):
    id: int
    filename: str
    document_type: DocumentType
    predicted_type: DocumentType
    status: DocumentStatus
    confidence: float
    needs_review: bool
    engine: str
    reason: str
    job_id: str | None


class JobLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str | None = Field(pattern=JOB_ID)


class JobStatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: JobStatus


class DocumentReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_type: DocumentType
