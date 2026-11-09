from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PyPdfError

MAX_BYTES = 2_000_000
MAX_PAGES = 12
MAX_TEXT = 60_000


class InvalidPdf(ValueError):
    """The upload cannot be processed as a supported PDF."""


class PdfTooLarge(InvalidPdf):
    """The upload exceeds a supported size or page limit."""


def extract(data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise PdfTooLarge("PDF exceeds the 2 MB limit")
    if not data.startswith(b"%PDF-"):
        raise InvalidPdf("A PDF file is required")
    try:
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise InvalidPdf("Encrypted PDFs are unsupported")
        count = len(reader.pages)
        if count < 1:
            raise InvalidPdf("PDF contains no pages")
        if count > MAX_PAGES:
            raise PdfTooLarge(f"PDF exceeds the {MAX_PAGES}-page limit")
        parts = [page.extract_text() or "" for page in reader.pages]
    except InvalidPdf:
        raise
    except (PyPdfError, OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        raise InvalidPdf("PDF could not be read") from exc
    return "\n".join(parts).strip()[:MAX_TEXT]
