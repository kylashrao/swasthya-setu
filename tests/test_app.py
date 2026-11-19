import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


def _check_receipt(ui, database, receipt_id, module):
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        receipt = connection.execute("SELECT * FROM audit_receipts WHERE id = ?", (receipt_id,)).fetchone()
        rows = connection.execute(
            """
            SELECT case_ref, module, rule_id, ruleset_version, source_ref, outcome, evidence_ref
            FROM audit_events WHERE id BETWEEN ? AND ? ORDER BY id
            """,
            (receipt["first_event_id"], receipt["last_event_id"]),
        ).fetchall()
    assert len(rows) == receipt["event_count"]
    assert {row["module"] for row in rows} == {module}
    payload = json.dumps([dict(row) for row in rows], sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    assert ui.code[0].value == receipt["sha256"] == hashlib.sha256(payload).hexdigest()


def test_demo_navigation_findings_and_persisted_receipts(tmp_path, monkeypatch):
    database = tmp_path / "audit.sqlite3"
    monkeypatch.setenv("SWASTHYASETU_AUDIT_DB", str(database))
    ui = AppTest.from_file(str(APP)).run()
    assert not ui.exception
    assert ui.header[0].value == "VaidyaSetu"
    assert ui.selectbox[0].label == "Load Demo Sample"
    assert not database.exists()

    ui.selectbox[0].select("synthetic-wardha-fail").run()
    ui.button[0].click().run()
    assert not ui.exception
    assert not ui.error
    assert {item.label for item in ui.metric} == {"Fail", "Pass", "Review"}
    assert any("ctri.prospective_registration" in item.value for item in ui.markdown)
    assert any("CTRI FAQ" in item.value for item in ui.caption)
    _check_receipt(ui, database, 1, "vaidyasetu")

    ui.sidebar.radio[0].set_value("Ayushman-Sarathi").run()
    assert ui.header[0].value == "Ayushman-Sarathi"
    assert not ui.expander
    ui.selectbox[0].select("passing_claim").run()
    ui.button[0].click().run()
    assert not ui.exception
    assert not ui.error
    assert len(ui.expander) == 1
    assert ui.expander[0].label.startswith("Pass (")
    assert any("₹31,000.00" in item.value for item in ui.markdown)
    _check_receipt(ui, database, 2, "ayushman_sarathi")

    ui.run()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT count(*) FROM audit_receipts").fetchone() == (2,)


def test_empty_or_malformed_demo_disables_audit(tmp_path, monkeypatch):
    import app

    samples = tmp_path / "samples"
    samples.mkdir()
    fixture = samples / "vaidyasetu.json"
    monkeypatch.setattr(app, "DATA", tmp_path)
    for body, message in [("[]", "no demo scenarios"), ("[null]", "Invalid local demo data")]:
        fixture.write_text(body, encoding="utf-8")
        # AppTest executes its script in __main__, so import the entry point in
        # a wrapper to share the monkeypatched fixture directory.
        ui = AppTest.from_string("from app import main\nmain()").run()
        assert not ui.exception
        assert message in ui.error[0].value
        assert not ui.button
        assert not (tmp_path / "audit.sqlite3").exists()


def test_editing_selected_fixture_hides_stale_receipt(tmp_path, monkeypatch):
    import app

    original = app.DATA / "samples" / "vaidyasetu.json"
    samples = tmp_path / "samples"
    samples.mkdir()
    fixture = samples / original.name
    cases = json.loads(original.read_text(encoding="utf-8"))
    fixture.write_text(json.dumps(cases), encoding="utf-8")
    monkeypatch.setattr(app, "DATA", tmp_path)
    monkeypatch.setenv("SWASTHYASETU_AUDIT_DB", str(tmp_path / "audit.sqlite3"))
    ui = AppTest.from_string("from app import main\nmain()").run()
    ui.button[0].click().run()
    assert ui.code
    cases[0]["as_of"] = "2026-06-02"
    fixture.write_text(json.dumps(cases), encoding="utf-8")
    ui.run()
    assert not ui.exception
    assert not ui.code
