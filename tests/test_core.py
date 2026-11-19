import sqlite3
from contextlib import closing
from pathlib import Path

import pymupdf
import pytest

from core.audit_logger import AuditEvent, append_audit_event
from core.pdf_parser import PDFParseError, parse_pdf

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"


def test_parse_pdf_preserves_page_numbers_and_flags_textless_pages():
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), "Synthetic trial protocol")
        document.new_page()
        pdf = document.tobytes()

    first, second = parse_pdf(pdf)
    assert (first.page_number, first.text.strip()) == (1, "Synthetic trial protocol")
    assert not first.needs_review
    assert second.page_number == 2
    assert second.needs_review


@pytest.mark.parametrize("data", [b"", b"invalid", b"<html>Not a PDF</html>"])
def test_parse_pdf_rejects_invalid_input(data):
    with pytest.raises(PDFParseError):
        parse_pdf(data)


def test_audit_log_appends_and_persists_metadata(tmp_path):
    database = tmp_path / "audit.sqlite3"
    event = AuditEvent.model_validate_json((SAMPLES / "audit_event.json").read_bytes())
    second_event = AuditEvent.model_validate({**event.model_dump(), "outcome": "pass"})

    first_id = append_audit_event(database, event)
    second_id = append_audit_event(database, second_event)

    with closing(sqlite3.connect(database)) as connection:
        rows = connection.execute(
            """
            SELECT id, case_ref, module, rule_id, ruleset_version, source_ref,
                   outcome, evidence_ref
            FROM audit_events
            ORDER BY id
            """
        ).fetchall()

    assert rows == [
        (first_id, *event.model_dump().values()),
        (second_id, *second_event.model_dump().values()),
    ]
    assert second_id > first_id


@pytest.mark.parametrize("data", [None, 123, "not bytes"])
def test_malformed_input_cannot_open_an_empty_document(data):
    with pytest.raises(PDFParseError):
        parse_pdf(data)


def test_pdf_with_empty_user_password_is_still_encrypted():
    with pymupdf.open() as document:
        document.new_page()
        pdf = document.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="")
    with pytest.raises(PDFParseError, match="unencrypted"):
        parse_pdf(pdf)


def test_invisible_characters_do_not_count_as_readable_text():
    from core.pdf_parser import PDFPage

    assert PDFPage(page_number=1, text=" \u200b\ufeff\ufffd").needs_review


def test_audit_receipt_insert_failure_rolls_back_findings(tmp_path):
    from core.audit_logger import append_audit_batch

    database = tmp_path / "audit.sqlite3"
    event = AuditEvent.model_validate_json((SAMPLES / "audit_event.json").read_bytes())
    append_audit_batch(database, (event,))
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("""
            CREATE TRIGGER ignore_receipt BEFORE INSERT ON audit_receipts
            BEGIN SELECT RAISE(IGNORE); END
        """)

    with pytest.raises(sqlite3.IntegrityError, match="receipt"):
        append_audit_batch(database, (event, event))

    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT count(*) FROM audit_events").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM audit_receipts").fetchone() == (1,)


def test_audit_batch_rejects_mixed_case_references(tmp_path):
    from core.audit_logger import append_audit_batch

    database = tmp_path / "audit.sqlite3"
    event = AuditEvent.model_validate_json((SAMPLES / "audit_event.json").read_bytes())
    another_case = event.model_copy(update={"case_ref": "another-synthetic-case"})
    with pytest.raises(ValueError, match="single case"):
        append_audit_batch(database, (event, another_case))
    assert not database.exists()
