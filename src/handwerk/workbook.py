import re
from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from .domain import JOB_ID, JOB_STATUSES, Job

SHEET = "Auftraege"
HEADERS = ("auftragsnr", "kunde", "status", "betrag_eur")


@dataclass(frozen=True)
class RowIssue:
    row: int
    message: str


@dataclass(frozen=True)
class WorkbookRows:
    jobs: list[Job]
    issues: list[RowIssue]


def amount_to_cents(value: object) -> int:
    try:
        if type(value) not in (int, float):
            raise InvalidOperation
        amount = Decimal(str(value))
        if not amount.is_finite() or not 0 <= amount <= 10_000_000:
            raise InvalidOperation
        cents = amount * 100
        if cents != cents.to_integral_value():
            raise InvalidOperation
        return int(cents)
    except InvalidOperation as exc:
        raise ValueError("betrag_eur must be numeric, nonnegative and use at most two decimals") from exc


def parse_job(values: list) -> Job:
    job_id, customer, status, amount = values
    if not isinstance(job_id, str) or not re.fullmatch(JOB_ID, job_id.strip()):
        raise ValueError("auftragsnr must be 1 to 32 uppercase letters, digits or hyphens")
    if not isinstance(customer, str) or not 1 <= len(customer.strip()) <= 120:
        raise ValueError("kunde must be nonempty text of at most 120 characters")
    if not isinstance(status, str) or status.strip() not in JOB_STATUSES:
        raise ValueError(f"status must be one of {', '.join(JOB_STATUSES)}")
    return Job(job_id.strip(), customer.strip(), status.strip(), amount_to_cents(amount))


def read_jobs(path: Path) -> WorkbookRows:
    try:
        with closing(load_workbook(path, read_only=True, data_only=False)) as workbook:
            if SHEET not in workbook.sheetnames:
                raise ValueError(f"expected worksheet {SHEET}")
            rows = workbook[SHEET].iter_rows()
            header = [cell.value for cell in next(rows, ())]
            if tuple(header[:len(HEADERS)]) != HEADERS or any(
                value is not None for value in header[len(HEADERS):]
            ):
                raise ValueError(f"expected columns {', '.join(HEADERS)}")
            jobs = []
            issues = []
            seen = set()
            for number, row in enumerate(rows, 2):
                values = [cell.value for cell in row]
                if all(value is None for value in values):
                    continue
                try:
                    if any(cell.data_type == "f" for cell in row):
                        raise ValueError("formula cells are unsupported; enter literal values")
                    if any(value is not None for value in values[len(HEADERS):]):
                        raise ValueError("unexpected value beyond the four job columns")
                    job = parse_job(values[:len(HEADERS)])
                    if job.job_id in seen:
                        raise ValueError(f"duplicate auftragsnr {job.job_id}")
                except ValueError as exc:
                    issues.append(RowIssue(number, str(exc)))
                    continue
                seen.add(job.job_id)
                jobs.append(job)
    except (OSError, BadZipFile, InvalidFileException, ParseError, KeyError, ValueError) as exc:
        raise ValueError(f"{path}: {exc}") from exc
    return WorkbookRows(jobs, issues)
