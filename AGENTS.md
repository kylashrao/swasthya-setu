# SwasthyaSetu operating contract

SwasthyaSetu is a ₹0 deterministic healthcare compliance compiler for India. Deliver one local application with a FastAPI backend and a Streamlit interface. Both modules share the same Python core for PDF extraction, Pydantic v2 validation, and SQLite auditing. Keep regulatory checks in module code so the interface and API produce the same findings.

## Local execution and evidence

- Use Python, FastAPI, Streamlit, PyMuPDF for local PDF text extraction, Pydantic v2 for schemas, standard-library SQLite for persistence, and pytest for verification. These are the approved direct dependencies. Run locally with zero required spend. Keep runtime and tests offline and free of paid services, hosted storage, external APIs, LLMs, and telemetry. Set Streamlit's `browser.gatherUsageStats` to false when adding the UI.
- Use versioned, explicit rules and local reference inputs. Same normalized inputs, ruleset, and evaluation date must yield the same findings in the same order. Pass dates and calendars explicitly and calculate currency with Decimal or integer paise using the applicable rounding policy.
- Record stable rule IDs, source citations, ruleset versions, outcomes, and evidence references. Route missing or ambiguous evidence to review. Flag textless PDF pages for review where text is required.
- Keep synthetic offline fixtures in `data/samples/`. Never commit real trial or patient records, claimant identifiers, or runtime audit databases. Store minimal metadata and opaque case references in the local audit log.

## vaidyasetu

- Check CDSCO and ICMR requirements under the NDCT Rules 2019 and the January 2026 amendment. Apply effective dates explicitly. For CT-10 manufacture applications, distinguish the Rule 53 prior-permission route with its 45-working-day timeline under the amended rule from the Rule 52 prior-intimation route for eligible analytical and non-clinical testing. Require the submission acknowledgement for prior intimation. Exclude sex hormones, cytotoxic drugs, beta-lactams, biologics with live microorganisms, and narcotic or psychotropic drugs from that route. Track the date and applicable working-day calendar supporting any deadline. [NDCT Rules 2019](https://cdsco.gov.in/opencms/resources/UploadCDSCOWeb/2018/UploadGazette_NotificationsFiles/gsr227e.pdf) · [G.S.R. 46(E), 20 January 2026](https://cdsco.gov.in/opencms/resources/UploadCDSCOWeb/2018/UploadGazette_NotificationsFiles/2026.01.20_%20G.S.R.%2046%28E%29_Notification%20about%20changes%20to%20requirements%20of%20Test%20license%20under%20NDCT%20Rules%202019.pdf) · [CDSCO implementation circular](https://cdsco.gov.in/opencms/resources/UploadCDSCOWeb/2018/UploadCircularFile/SKM_558e26030618270.pdf)
- Compare a local CTRI record against the approved protocol and supplied trial documents. Check identifiers, protocol version where available, sites, sponsor, study design and enrolment timing, including registration before first enrolment where required. Report field-level mismatches and missing evidence. [CTRI FAQ](https://www.ctri.nic.in/Clinicaltrials/faq.php)
- Verify Ethics Committee approval and version alignment for participant information sheets and informed consent forms in languages participants understand. Flag missing vernacular versions, missing required elements, and cases where translation quality or participant comprehension requires human review. [ICMR National Ethical Guidelines](https://ethics.ncdirindia.org/asset/pdf/ICMR_National_Ethical_Guidelines.pdf)

## ayushman_sarathi

- Audit rural hospital pre-authorizations and claims under AB PM-JAY. Map documented procedures to versioned Health Benefit Package (HBP) codes, using the applicable State Health Agency (SHA) package schedule and tariff. Flag ambiguous or unsupported mappings.
- For eligible multiple surgical packages in the same admission, apply 100% of the highest package rate and 50% of the second. Apply the applicable schedule for further procedures and overrides. For example, HBP 2.2 specifies 25% for the third package unless otherwise defined. [NHA HBP 2.2 manual, section 4.1](https://nha.gov.in/img/resources/HBP-2.2-manual.pdf)
- Check every mandatory pre-operative attachment against the applicable package checklist before marking the evidence complete. Verify presence, readability, case linkage, and timing where required. Flag missing, unreadable, mismatched, or late evidence for review. [NHA HBP 2.2 manual, sections 4.1–4.2](https://nha.gov.in/img/resources/HBP-2.2-manual.pdf)

## Required verification

Run `pytest -v` from the repository root before finishing every task. Resolve failures introduced by the task and report the actual result. Keep the suite runnable offline using synthetic fixtures.
