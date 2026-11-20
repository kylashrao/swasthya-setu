# SwasthyaSetu

SwasthyaSetu is a ₹0 healthcare compliance compiler for India. Its Streamlit and Next.js interfaces share the same Python evaluators. VaidyaSetu reviews CT-10, CTRI, and consent evidence. Ayushman-Sarathi reviews AB PM-JAY package mapping, tariffs, and mandatory pre-operative evidence. Both show findings with rule IDs, evidence references, and a SHA-256 receipt for the ordered finding metadata.

## Run locally

Use Python 3.10 or newer. Install from a local wheelhouse or a package index. The application and tests run offline after setup.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### Streamlit

```sh
streamlit run app.py
```

Select a module and synthetic sample, then run the demo audit. The VaidyaSetu view also provides Vernacular ICF and SEC Query Simulator tabs. Streamlit usage telemetry is disabled.

### FastAPI and Next.js

Use Node.js 20.9 or newer. Start FastAPI in one terminal from the repository root with the virtual environment active.

```sh
python -m uvicorn api.index:app --host 127.0.0.1 --port 8000
```

In a second terminal, install the locked frontend dependencies, build the dashboard, and serve the generated HTML locally.

```sh
npm --prefix frontend ci --no-audit --no-fund
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000 npm --prefix frontend run build
python -m http.server 3000 --bind 127.0.0.1 --directory frontend/out
```

Open `http://127.0.0.1:3000`. Choose a module or a VaidyaSetu tool, load a synthetic sample, and submit it as-is or edit its JSON first. The dashboard includes findings, SHA-256 receipts, a time-saved estimator, and a roadmap. The estimator uses illustrative assumptions of 30 minutes of manual review and 1 minute of deterministic checks per case.

For live frontend editing, `npm --prefix frontend run dev -- --hostname 127.0.0.1` starts the Next.js development server in place of the static server. Next.js can check npm for version updates in development mode.

### HTTP API

All POST requests accept JSON. Use `GET /api/samples/{module}` for example payloads keyed by sample name. Sample modules are `vaidyasetu`, `ayushman-sarathi`, and `vernacular`. The full schema is at `GET /api/openapi.json`.

| Method and path | Payload and response |
| --- | --- |
| `POST /api/vaidyasetu` | VaidyaSetu case with explicit evaluation date. Returns evaluation and receipt. |
| `POST /api/ayushman-sarathi` | Object with `admission` and applicable SHA `schedule`. Returns evaluation and receipt. |
| `POST /api/vernacular` | Structured clauses and language. Returns clause-level translations, back-translations, review flags, and metrics. |
| `POST /api/sec` | Object with `case`, optional `population`, and optional `responses`. Returns dossier-grounded questions, evidence checklists, and response coverage. |

## Vernacular consent and SEC rehearsal

The ICF tool supports Hindi (`hi`), Kannada (`kn`), Tamil (`ta`), Telugu (`te`), and Malayalam (`ml`). Use English `source` clauses keyed by disclosure ID. Supply `localized` and, when available, independently prepared English `back_translation` objects with the same keys. Use `additional_required` for applicable conditional or dossier-specific disclosures, such as `randomization_and_treatment_schedule`. With no localized input, the tool translates exact normalized matches for three synthetic sample clauses. With localized input, it checks submitted wording as provided. Unrecognized wording and terminology differences go to review.

Optional assisted mode uses a local phrase glossary. Set `SWASTHYASETU_TRANSLATION_GLOSSARY` in the Python process environment and set `use_assisted` to `true` in the request or enable the Streamlit checkbox. The glossary is a UTF-8 JSON array whose entries have `section`, `language`, `english`, `translated`, and `reverse_english` fields. Populate the reverse wording independently to make divergence observable. This option requires no API keys and makes no network calls.

Both modes report completeness by populated disclosure and use whitespace words per sentence as a descriptive readability measure. The tool performs assisted comparison or deterministic phrase matching only. Obtain qualified language and consent review before clinical use.

The SEC simulator generates questions from the dossier and its rule findings. For the API, key `responses` first by question ID and then by checklist item ID. Each entry contains a sponsor `statement` and an `evidence_ref`. Coverage counts submitted pairs and identifies missing items. A complete checklist is ready for independent review of the underlying evidence.

## Persistence and deployment

SQLite records only finding metadata and receipts for the two core compliance audits. The default database is `data/audit.sqlite3`. Set `SWASTHYASETU_AUDIT_DB` to override it locally. Keep case and evidence references opaque. The separate consent comparison and SEC rehearsal do not write submitted content to SQLite.

The supplied [vercel.json](vercel.json) builds Next.js as static assets and routes same-origin `/api/*` requests to FastAPI. Configure the Vercel project root as the repository root with the **Other** framework preset. When `VERCEL=1`, FastAPI uses `/tmp/audit.sqlite3`. Each function instance has temporary storage, so receipts may be lost across cold starts and instances. The deployment configuration is intended for synthetic demonstrations.

## Verify

Run the complete Python suite from the repository root with the virtual environment active.

```sh
pytest -v
npm --prefix frontend run build
```

See [AGENTS.md](AGENTS.md) for the operating contract and regulatory references.
