import json

import pytest

from core.vernacular_engine import LANGUAGES, VerificationRequest, sample_phrases, verify


@pytest.mark.parametrize("language", LANGUAGES)
def test_round_trip_and_metrics(language, monkeypatch):
    monkeypatch.setenv("SWASTHYASETU_TRANSLATION_GLOSSARY", "/does-not-exist")
    rows = sample_phrases()
    request = VerificationRequest(language=language, source={key: row["en"] for key, row in rows.items()})
    result = verify(request)
    assert result == verify(request)
    assert result["mode"] == "deterministic"
    assert result["metrics"]["phrase_matches"] == len(rows)
    assert result["metrics"]["sentences"] == len(rows)
    assert result["metrics"]["words_per_sentence"] > 0
    assert 0 < result["metrics"]["completeness_percent"] < 100
    for key, row in rows.items():
        assert result["sections"][key]["localized"] == row[language]
        assert result["sections"][key]["back_translation"] == row["en"]
    assert any(item["rule_id"] == "icf.missing_source_disclosure" for item in result["findings"])


def test_missing_disclosure_and_manual_drift():
    key = "free_medical_management"
    result = verify(VerificationRequest(
        language="hi", source={key: sample_phrases()[key]["en"], "risks": "Trial risks"},
        localized={key: "उपचार के लिए शुल्क देना होगा।"},
        back_translation={key: "You must pay for medical care."}, additional_required={"prorated_payment"},
    ))
    findings = {(item["rule_id"], item["section"]) for item in result["findings"]}
    assert ("icf.terminology_drift", key) in findings
    assert ("icf.human_back_translation_review", key) in findings
    assert ("icf.missing_localized_disclosure", "risks") in findings
    assert ("icf.missing_source_disclosure", "prorated_payment") in findings
    assert result["mode"] == "assisted"
    assert result["metrics"]["phrase_matches"] == 0


def test_glossary_forward_and_reverse_are_independently_supplied(tmp_path, monkeypatch):
    glossary = tmp_path / "local.json"
    glossary.write_text(json.dumps([{
        "section": "participation_duration", "language": "hi", "english": "Three days.",
        "translated": "चार दिन।", "reverse_english": "Four days.",
    }]), encoding="utf-8")
    monkeypatch.setenv("SWASTHYASETU_TRANSLATION_GLOSSARY", str(glossary))
    request = VerificationRequest(language="hi", source={"participation_duration": "Three days."}, use_assisted=True)
    result = verify(request)
    assert result["sections"]["participation_duration"]["back_translation"] == "Four days."
    assert any(item["rule_id"] == "icf.terminology_drift" for item in result["findings"])
    assert result["mode"] == "assisted"
    monkeypatch.delenv("SWASTHYASETU_TRANSLATION_GLOSSARY")
    with pytest.raises(ValueError, match="local glossary"):
        verify(request)


def test_unfamiliar_source_is_routed_to_review():
    result = verify(VerificationRequest(language="ml", source={"risks": "You may experience dizziness."}))
    assert result["sections"]["risks"]["localized"] == ""
    assert result["metrics"]["words_per_sentence"] is None
