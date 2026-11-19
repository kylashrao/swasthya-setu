"""Extract local PDF text while retaining page-level evidence."""

from unicodedata import category

import pymupdf
from pydantic import BaseModel, ConfigDict, PositiveInt


class PDFParseError(ValueError):
    """The input could not be read as an unencrypted PDF."""


class PDFPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    page_number: PositiveInt
    text: str

    @property
    def needs_review(self) -> bool:
        return not any(
            not char.isspace() and category(char) not in {"Cc", "Cf"} and char != "\ufffd"
            for char in self.text
        )


def parse_pdf(data: bytes) -> tuple[PDFPage, ...]:
    """Extract text in page and reading order from in-memory PDF bytes."""
    if not isinstance(data, (bytes, bytearray, memoryview)) or not data:
        raise PDFParseError("Expected non-empty PDF bytes.")
    try:
        with pymupdf.open(stream=bytes(data), filetype="pdf") as document:
            if not document.is_pdf or document.needs_pass or document.metadata.get("encryption"):
                raise PDFParseError("Expected an unencrypted PDF.")
            if not document.page_count:
                raise PDFParseError("Expected a PDF with at least one page.")
            return tuple(
                PDFPage(page_number=index, text=page.get_text(sort=True))
                for index, page in enumerate(document, start=1)
            )
    except PDFParseError:
        raise
    except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
        raise PDFParseError("Could not read the PDF.") from exc
