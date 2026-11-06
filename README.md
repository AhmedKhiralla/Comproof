# Comproof · Comp11 Labs

Comproof proves every word on a pharmaceutical pack against the approved text. It compares new artwork,
print-house proofs and printed samples with the approved master — leaflets and SmPCs, cartons, labels and
sachets, blister foil and tubes — word by word in English and Arabic, and keeps a 21 CFR Part 11 record of
every run, decision and electronic signature.

## What it does

| Area | Phase 1 (this release) |
|---|---|
| **Artwork library** | Products → packaging components → approved artwork versions. A version becomes the *effective master* only through an electronic signature; the previous master is superseded automatically. Every file is stored by SHA-256 and verified on every read. |
| **Comparison engine** | Vector PDF (text layer), scanned PDF, images and Word. Tesseract OCR (eng + ara) with optional AI reading, rotated print-house strips and carton side panels, mirrored foil, configurable phrase exclusions. |
| **Three levels** | **Level 1** audits the approved text itself (strengths, dosage form, decimals, headings, English vs Arabic). **Level 2** compares every word per language: missing, added, changed, numbers (critical), dosage-form wording (major). **Level 3** checks punctuation, spacing, capitalisation and digit style on text that otherwise matches. |
| **Interactive report** | Verdict and severity ledger, levels rail, section filter, proof-style diff (approved red struck through, new blue underlined), side-by-side screenshots with highlighted words, full-page viewer, pin map of the pack, keyboard review (j / k, /, Enter). Low-confidence readings are flagged and never raised to critical on their own. |
| **Review and approval** | Each finding is decided as *confirmed deviation* or *not a deviation* (comment required). Signed review, then signed approval or rejection, with four-eyes and all-decided rules per company. Approval is blocked while confirmed critical or major findings remain. |
| **Exports** | PDF report, Excel findings log, standalone HTML report — each export is audited. |
| **AI (optional, per company)** | Pluggable OpenAI-compatible providers: Qwen, Groq, Claude, Gemini or a company gateway. Roles: reading (transcribes tiles aligned to OCR boxes), review (looks at both screenshots), science (checks the approved text). |
| **Platform** | Multi-company, sites, roles (artwork editor, reviewer, approver, viewer), English and Arabic UI, light and dark themes. |

See [docs/PART11.md](docs/PART11.md) for the Part 11 traceability and [docs/ROADMAP.md](docs/ROADMAP.md) for
colour (ΔE), barcodes, the print-house portal and line checks.

## Deploy on Railway

1. Create a project from this repository; Railway builds the `Dockerfile` (`railway.json` sets the health check).
2. Add a **PostgreSQL** service and set `DATABASE_URL` on the app to its connection string.
3. Add a **volume** mounted at `/data` (files and results live there; `DATA_DIR=/data` is the image default).
4. Set the variables:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL 14+ connection string. Migrations run at start-up. |
| `PLATFORM_ADMIN_EMAIL`, `PLATFORM_ADMIN_PASSWORD`, `PLATFORM_ADMIN_NAME` | First platform administrator (must change the password at first sign-in). |
| `DATA_DIR` | File store (default `/data` in the image). |
| `MAX_UPLOAD_MB` | Upload limit, default 60. |
| `ENGINE_WORKERS` | Comparisons run in parallel per instance, default 1 (OCR is CPU-bound; raise with the plan's vCPUs). |
| `RUN_WORKER` | `false` on a web-only replica. |
| `QWEN_API_KEY`, `GROQ_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `CUSTOM_AI_*` | Optional AI providers. Each also accepts `*_BASE_URL`, `*_VISION_MODEL`, `*_TEXT_MODEL`. Keys stay in the environment, never in the database. |
| `SESSION_MAX_HOURS`, `DB_POOL_SIZE`, `COOKIE_SECURE` | Optional tuning; keep `COOKIE_SECURE=true` in production. |

5. Sign in as the platform administrator, create the company and its administrator, who then adds sites,
   users and roles, and sets the engine (Settings → Engine) and AI provider.

The image contains Tesseract with English and Arabic, libraqm for Arabic shaping, Noto and Amiri fonts for the
reports, and LibreOffice (Writer) for Word files.

## Run locally

```bash
# backend (Python 3.12+, PostgreSQL, tesseract-ocr with eng+ara)
cd backend
pip install -r requirements.txt
export DATABASE_URL=postgresql://postgres@127.0.0.1:5432/comproof PLATFORM_ADMIN_EMAIL=you@example.com \
       PLATFORM_ADMIN_PASSWORD='Change#Me2026' COOKIE_SECURE=false
uvicorn app.main:app --reload

# web app (Node 20+)
cd frontend
npm install
npm run build        # served by the backend from frontend/dist
```

## Tests

End-to-end tests create a fresh database, start a real server and a stand-in AI provider, then exercise the
library, signatures, the engine, the review rules, exports, tamper protection and company isolation.

```bash
cd backend
TEST_DATABASE_ADMIN_URL=postgresql://postgres@127.0.0.1:5432/postgres python -m pytest -q tests/
```

## Layout

```
backend/app/            Starlette API, auth, roles, e-signatures, file store, worker
backend/app/engine/     ingest, layout/OCR, AI reading, compare, master checks, pipeline, exports
backend/migrations/     SQL: row-level security, append-only tables, guards, hash-chained audit trail
frontend/src/           React web app (English / Arabic)
docs/                   Part 11 traceability, roadmap
```

© Comp11 Labs
