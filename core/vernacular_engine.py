"""Structured ICF comparison with a local phrasebook and explicit review findings."""

import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from modules.vaidyasetu.evaluator import CONSENT_SOURCE, ESSENTIAL_ELEMENTS
from modules.vaidyasetu.models import Record

Language = Literal["hi", "kn", "ta", "te", "ml"]
LANGUAGES = {"hi": "Hindi", "kn": "Kannada", "ta": "Tamil", "te": "Telugu", "ml": "Malayalam"}
VERSION = "vernacular-1.0"
DISCLAIMER = ("Assisted comparison or deterministic phrase matching only. "
              "Obtain qualified language and consent review before use.")
SCRIPTS = {"hi": "DEVANAGARI", "kn": "KANNADA", "ta": "TAMIL", "te": "TELUGU", "ml": "MALAYALAM"}
SAMPLE = Path(__file__).resolve().parents[1] / "data/samples/icf_phrases.json"
Section = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Clause = Annotated[str, StringConstraints(max_length=20000)]


class VerificationRequest(Record):
    language: Language
    source: dict[Section, Clause] = Field(max_length=100)
    localized: dict[Section, Clause] | None = Field(default=None, max_length=100)
    back_translation: dict[Section, Clause] | None = Field(default=None, max_length=100)
    additional_required: frozenset[Section] = Field(default=frozenset(), max_length=100)
    use_assisted: bool = False


class Phrase(Record):
    section: Section
    language: Language
    english: Clause
    translated: Clause
    reverse_english: Clause


def sample_phrases() -> dict:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def verify(request: VerificationRequest) -> dict:
    rows = sample_phrases()
    phrases = [Phrase(section=key, language=request.language, english=row["en"],
                      translated=row[request.language], reverse_english=row["en"])
               for key, row in rows.items()]
    if request.use_assisted:
        path = os.environ.get("SWASTHYASETU_TRANSLATION_GLOSSARY")
        if not path:
            raise ValueError("Set SWASTHYASETU_TRANSLATION_GLOSSARY to a local glossary to enable assisted mode.")
        try:
            extra = [Phrase.model_validate(item) for item in json.loads(Path(path).read_text(encoding="utf-8"))]
            if any(not all(v.strip() for v in (p.english, p.translated, p.reverse_english)) for p in extra):
                raise ValueError("Empty glossary phrase")
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError("The local translation glossary could not be loaded.") from exc
        phrases.extend(p for p in extra if p.language == request.language)

    forward = {}
    reverse = {}
    for phrase in phrases:
        forward.setdefault((phrase.section, _normalize(phrase.english)), set()).add(phrase.translated)
        reverse.setdefault((phrase.section, _normalize(phrase.translated)), set()).add(phrase.reverse_english)

    required = ESSENTIAL_ELEMENTS | request.additional_required
    localized = request.localized
    findings = []
    sections = {}

    def flag(code, section, message):
        findings.append(dict(rule_id=f"icf.{code}", outcome="review", section=section,
                             message=message, source_ref=CONSENT_SOURCE, evidence_refs=[section]))

    keys = required | request.source.keys() | (localized or {}).keys() | (request.back_translation or {}).keys()
    for key in sorted(keys):
        english = request.source.get(key, "").strip()
        candidates = forward.get((key, _normalize(english)), set())
        target = (localized.get(key, "").strip() if localized is not None else
                  next(iter(candidates)) if len(candidates) == 1 else "")
        reverse_candidates = reverse.get((key, _normalize(target)), set())
        matched_reverse = next(iter(reverse_candidates)) if len(reverse_candidates) == 1 else ""
        supplied_reverse = (request.back_translation or {}).get(key, "").strip()
        back = supplied_reverse or matched_reverse
        if key in required and not english:
            flag("missing_source_disclosure", key, "The source disclosure is missing.")
        if not target and (english or key in required):
            flag("missing_localized_disclosure", key, "The localized disclosure is missing. Supply wording for review.")
        if target and not any(unicodedata.name(char, "").startswith(SCRIPTS[request.language] + " ")
                              for char in target if char.isalpha()):
            flag("language_script_review", key, "The expected language script was not detected. Verify the language.")
        if supplied_reverse and not target:
            flag("unlinked_back_translation", key, "Supply the localized wording from which this clause was back-translated.")
        if target and (not matched_reverse or supplied_reverse):
            flag("human_back_translation_review", key, "Review the localized wording and any supplied back-translation.")
        if english and any(_normalize(item) != _normalize(english) for item in (matched_reverse, supplied_reverse) if item):
            flag("terminology_drift", key, "The English source and a back-translation differ. Check terminology, amounts, and negation.")
        if target and not english and key not in required:
            flag("unmatched_localized_section", key, "This localized section has no source clause.")
        sections[key] = dict(source=english, localized=target, back_translation=back,
                             phrase_match=bool(english and target and matched_reverse and
                                               not supplied_reverse and _normalize(english) == _normalize(matched_reverse)))

    targets = [row["localized"] for row in sections.values() if row["localized"]]
    words = sum(len(value.split()) for value in targets)
    sentences = sum(bool(chunk.strip()) for value in targets for chunk in re.split(r"[.!?।]+", value))
    present = sum(bool(sections[key]["source"] and sections[key]["localized"]) for key in required)
    mode = "assisted" if request.use_assisted or request.back_translation else "deterministic"
    return dict(ruleset_version=VERSION, source_ref=CONSENT_SOURCE, language=request.language,
                mode=mode, notice=DISCLAIMER, sections=sections, findings=findings,
                metrics=dict(required_sections=len(required), populated_required_sections=present,
                             completeness_percent=round(100 * present / len(required), 2),
                             phrase_matches=sum(section["phrase_match"] for section in sections.values()),
                             whitespace_words=words, sentences=sentences,
                             words_per_sentence=round(words / sentences, 2) if sentences else None))
