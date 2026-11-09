import os
import sqlite3
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import store
from .classify import MockLLM, Sorter
from .domain import (
    DOCUMENT_LABELS,
    JOB_LABELS,
    DocumentReview,
    DocumentStatus,
    DocumentType,
    DocumentView,
    JobLink,
    JobStatusChange,
    JobView,
)
from .pdf import MAX_BYTES, InvalidPdf, PdfTooLarge
from .synthetic import euro

PACKAGE = Path(__file__).parent


def create_app(path: Path, sorter: Sorter | None = None) -> FastAPI:
    engine = sorter if sorter is not None else Sorter(MockLLM())

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        store.initialize(path)
        yield

    app = FastAPI(title="Handwerk Beleg-Assistent", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=PACKAGE / "static"), name="static")
    templates = Jinja2Templates(directory=PACKAGE / "templates")

    def database() -> Iterator[sqlite3.Connection]:
        with store.connect(path) as db:
            yield db

    Db = Annotated[sqlite3.Connection, Depends(database)]

    @app.exception_handler(store.MissingRecord)
    async def missing(_request: Request, error: store.MissingRecord):
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/documents", response_model=DocumentView, status_code=201)
    def upload(response: Response, db: Db, file: Annotated[UploadFile, File()]):
        try:
            row, created = store.ingest(db, file.filename or "beleg.pdf",
                                        file.file.read(MAX_BYTES + 1), engine)
        except PdfTooLarge as exc:
            raise HTTPException(413, detail=str(exc)) from exc
        except InvalidPdf as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        if not created:
            response.status_code = 200
        return row

    @app.get("/documents", response_model=list[DocumentView])
    def list_documents(db: Db, status: DocumentStatus | None = None):
        return store.documents(db, status)

    @app.get("/documents/{document_id}", response_model=DocumentView)
    def get_document(document_id: int, db: Db):
        return store.document(db, document_id)

    @app.get("/documents/{document_id}/file", response_class=Response)
    def download(document_id: int, db: Db):
        filename, content = store.original(db, document_id)
        return Response(content, media_type="application/pdf", headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
            "X-Content-Type-Options": "nosniff",
        })

    @app.patch("/documents/{document_id}/job", response_model=DocumentView)
    def link_document(document_id: int, update: JobLink, db: Db):
        return store.link(db, document_id, update.job_id)

    @app.patch("/documents/{document_id}/review", response_model=DocumentView)
    def review_document(document_id: int, update: DocumentReview, db: Db):
        return store.review(db, document_id, update.document_type)

    @app.get("/jobs", response_model=list[JobView])
    def list_jobs(db: Db):
        return store.jobs(db)

    @app.patch("/jobs/{job_id}/status", response_model=JobView)
    def job_status(job_id: str, update: JobStatusChange, db: Db):
        return store.change_status(db, job_id, update.status)

    @app.get("/", response_class=HTMLResponse)
    def review_page(request: Request, db: Db):
        counts, pending = store.queue(db)
        return templates.TemplateResponse(request=request, name="review.html", context={
            "counts": counts, "pending": pending, "labels": DOCUMENT_LABELS, "active": "review",
        })

    @app.post("/review/{document_id}")
    def confirm(document_id: int, document_type: Annotated[DocumentType, Form()], db: Db):
        store.review(db, document_id, document_type)
        return RedirectResponse("/", status_code=303)

    @app.get("/auftraege", response_class=HTMLResponse)
    def jobs_page(request: Request, db: Db):
        jobs = store.jobs(db)
        return templates.TemplateResponse(request=request, name="jobs.html", context={
            "jobs": jobs, "labels": JOB_LABELS, "active": "jobs", "euro": euro,
            "total": sum(job["amount_cents"] for job in jobs),
        })

    return app


app = create_app(Path(os.environ.get("HANDWERK_DB", "handwerk.sqlite")))
