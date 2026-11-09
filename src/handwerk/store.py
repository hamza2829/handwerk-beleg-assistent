import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

from .classify import Sorter
from .domain import DocumentType, JobStatus
from .pdf import extract
from .workbook import RowIssue, WorkbookRows

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    customer TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('offen', 'in_arbeit', 'abgeschlossen', 'storniert')),
    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0)
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    pdf BLOB NOT NULL,
    extracted_text TEXT NOT NULL,
    predicted_type TEXT NOT NULL,
    document_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pruefen', 'sortiert', 'geprueft')),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    engine TEXT NOT NULL,
    reason TEXT NOT NULL,
    job_id TEXT REFERENCES jobs(job_id)
);
CREATE INDEX IF NOT EXISTS documents_job ON documents(job_id);
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source TEXT NOT NULL,
    inserted INTEGER NOT NULL,
    updated INTEGER NOT NULL,
    issues TEXT NOT NULL
);
"""

DOC_COLUMNS = """
    id, filename, document_type, predicted_type, status, confidence,
    status = 'pruefen' AS needs_review, engine, reason, job_id
"""


class MissingRecord(LookupError):
    """A requested document or job was not found."""


@dataclass(frozen=True)
class ImportResult:
    inserted: int
    updated: int
    issues: list[RowIssue]


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path, check_same_thread=False)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection
    finally:
        connection.close()


def initialize(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as connection:
        connection.executescript(SCHEMA)


def import_jobs(db: sqlite3.Connection, rows: WorkbookRows, source: str) -> ImportResult:
    inserted = updated = 0
    with db:
        for job in rows.jobs:
            cursor = db.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?) ON CONFLICT(job_id) DO NOTHING",
                (job.job_id, job.customer, job.status, job.amount_cents),
            )
            if cursor.rowcount:
                inserted += 1
            else:
                db.execute(
                    "UPDATE jobs SET customer = ?, amount_cents = ? WHERE job_id = ?",
                    (job.customer, job.amount_cents, job.job_id),
                )
                updated += 1
        db.execute(
            "INSERT INTO imports (source, inserted, updated, issues) VALUES (?, ?, ?, ?)",
            (source, inserted, updated, json.dumps([asdict(issue) for issue in rows.issues])),
        )
    return ImportResult(inserted, updated, rows.issues)


def jobs(db: sqlite3.Connection) -> list[dict]:
    return [dict(row) for row in db.execute("""
        SELECT jobs.*, COUNT(documents.id) AS documents FROM jobs
        LEFT JOIN documents USING (job_id) GROUP BY jobs.job_id ORDER BY jobs.job_id
    """)]


def change_status(db: sqlite3.Connection, job_id: str, status: JobStatus) -> dict:
    with db:
        cursor = db.execute("UPDATE jobs SET status = ? WHERE job_id = ?", (status, job_id))
        if not cursor.rowcount:
            raise MissingRecord("Job not found")
        row = db.execute("""
            SELECT jobs.*, (SELECT COUNT(*) FROM documents WHERE job_id = jobs.job_id) AS documents
            FROM jobs WHERE job_id = ?
        """, (job_id,)).fetchone()
    return dict(row)


def document(db: sqlite3.Connection, document_id: int) -> dict:
    row = db.execute(f"SELECT {DOC_COLUMNS} FROM documents WHERE id = ?", (document_id,)).fetchone()
    if row is None:
        raise MissingRecord("Document not found")
    return dict(row)


def documents(db: sqlite3.Connection, status: str | None = None) -> list[dict]:
    query = f"SELECT {DOC_COLUMNS} FROM documents"
    if status is None:
        rows = db.execute(query + " ORDER BY id")
    else:
        rows = db.execute(query + " WHERE status = ? ORDER BY id", (status,))
    return [dict(row) for row in rows]


def original(db: sqlite3.Connection, document_id: int) -> tuple[str, bytes]:
    row = db.execute("SELECT filename, pdf FROM documents WHERE id = ?", (document_id,)).fetchone()
    if row is None:
        raise MissingRecord("Document not found")
    return row["filename"], row["pdf"]


def queue(db: sqlite3.Connection) -> tuple[dict, list[dict]]:
    counts = db.execute("""
        SELECT COUNT(*) AS total, COUNT(CASE WHEN status = 'pruefen' THEN 1 END) AS pending,
        COUNT(job_id) AS linked FROM documents
    """).fetchone()
    rows = db.execute(f"""
        SELECT {DOC_COLUMNS}, substr(extracted_text, 1, 420) AS preview FROM documents
        WHERE status = 'pruefen' ORDER BY id LIMIT 50
    """)
    return dict(counts), [dict(row) for row in rows]


def ingest(db: sqlite3.Connection, filename: str, data: bytes, sorter: Sorter) -> tuple[dict, bool]:
    digest = sha256(data).hexdigest()
    known = db.execute("SELECT id FROM documents WHERE sha256 = ?", (digest,)).fetchone()
    if known is not None:
        return document(db, known["id"]), False
    text = extract(data)
    classification = sorter.classify(text)
    prediction = classification.prediction
    filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    filename = "".join(char for char in filename if char.isprintable()).strip()[:180] or "beleg.pdf"
    with db:
        cursor = db.execute("""
            INSERT INTO documents (sha256, filename, pdf, extracted_text, predicted_type,
                                   document_type, status, confidence, engine, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(sha256) DO NOTHING
        """, (
            digest, filename, data, text, prediction.document_type, prediction.document_type,
            "pruefen" if classification.needs_review else "sortiert", prediction.confidence,
            classification.engine, prediction.reason,
        ))
        row = db.execute("SELECT id FROM documents WHERE sha256 = ?", (digest,)).fetchone()
    return document(db, row["id"]), bool(cursor.rowcount)


def link(db: sqlite3.Connection, document_id: int, job_id: str | None) -> dict:
    with db:
        try:
            cursor = db.execute("UPDATE documents SET job_id = ? WHERE id = ?", (job_id, document_id))
        except sqlite3.IntegrityError as exc:
            raise MissingRecord("Job not found") from exc
        if not cursor.rowcount:
            raise MissingRecord("Document not found")
        return document(db, document_id)


def review(db: sqlite3.Connection, document_id: int, kind: DocumentType) -> dict:
    with db:
        cursor = db.execute(
            "UPDATE documents SET document_type = ?, status = 'geprueft' WHERE id = ?",
            (kind, document_id),
        )
        if not cursor.rowcount:
            raise MissingRecord("Document not found")
        return document(db, document_id)
