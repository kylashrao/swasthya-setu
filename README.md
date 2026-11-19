# SwasthyaSetu

SwasthyaSetu is a ₹0, offline healthcare compliance compiler for India. One Streamlit app runs deterministic checks on synthetic clinical trial dossiers and rural hospital pre-authorizations and claims. The demo shows **Pass**, **Fail**, and **Review** findings with rule IDs, citations, and evidence references.

## Run locally

Use Python 3.10 or newer. The initial dependency installation can use a package index or a local wheelhouse. The app and tests run offline after installation.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

Choose **VaidyaSetu** or **Ayushman-Sarathi**, select a fixture under **Load Demo Sample**, and click **Run demo audit**. From the repository root, run the full verification suite with the virtual environment active.

```sh
pytest -v
```

## Offline architecture

- **Streamlit** provides the local interface. Usage telemetry is disabled in `.streamlit/config.toml`.
- **Python and Pydantic v2** validate local JSON fixtures under `data/samples/` and run versioned rules. Evaluations use supplied dates, calendars, and tariff schedules. Missing or ambiguous evidence goes to Review. The shared **PyMuPDF** parser extracts local PDF text and flags textless pages for review.
- **SQLite** stores finding metadata and SHA-256 audit receipts in `data/audit.sqlite3` by default. Set `SWASTHYASETU_AUDIT_DB` to use another local database path. Each receipt hashes the ordered finding metadata.
- **pytest** verifies the shared core, both evaluators, and the Streamlit demo. The local runtime requires no paid services, network APIs, or model calls.

## Shipped today

| Module | Checks |
| --- | --- |
| **VaidyaSetu** | NDCT 2019 and January 2026 CT-10 pathways and timelines, CTRI and protocol consistency, and vernacular consent coverage, Ethics Committee approval, and required disclosures |
| **Ayushman-Sarathi** | AB PM-JAY package mapping, applicable multi-procedure rates and overrides, mandatory pre-op attachments, and documented pre-authorization |

Both views show SHA-256 SQLite audit receipts. The verification suite includes 70 pytest tests. The demo package codes and rates are synthetic. Real claims need the applicable State Health Agency schedule, and consent language checks use documented human assessments.

## Manual Time-Saved Estimator

Set **Cases in batch** to compare illustrative manual review hours with deterministic check hours. The estimator assumes **30 minutes of manual review** and **1 minute of deterministic checks** per case. A batch of 10 cases shows **5.00 h** of manual review, **0.17 h** of deterministic checks, and **4.83 h** of estimated time saved.

These figures come from fixed assumptions. No performance measurements were taken. The estimate excludes evidence preparation and follow-up review.

## Roadmap & Next Milestones

The following milestones are planned.

1. Automated CT-04, CT-01, and CTRI drafting with XML and JSON output.
2. Parallel four-worker dossier orchestration.
3. Schedule M CMC checks and risk synthesis from PubMed and ICMR sources.
4. Automated Hindi, Kannada, Tamil, Bengali, and Marathi informed consent form translation and back-translation.
5. Interactive Subject Expert Committee (SEC) query simulation.

See [AGENTS.md](AGENTS.md) for the operating contract and regulatory references.
