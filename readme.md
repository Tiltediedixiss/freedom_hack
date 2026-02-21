# F.I.R.E. — Freedom Intelligent Routing Engine

AI-powered ticket routing system: CSV ingestion → PII anonymization → spam filter → parallel LLM classification + sentiment analysis + geocoding → priority scoring → smart routing.

## Tech Stack

| Layer | Tech |
|-------|------|
| Backend | Python 3.12, FastAPI, SQLAlchemy async, PostgreSQL + PostGIS |
| Frontend | React 19, TypeScript, Vite 6, Tailwind CSS, shadcn/ui, Bun |
| LLM | OpenRouter API (Gemini 2.0 Flash) |
| Spam Filter | HuggingFace `mrm8488/bert-tiny-finetuned-sms-spam-detection` + structural heuristics |
| PII | spaCy `ru_core_news_sm` + regex (IIN, phone, card, email, full name) |
| Geocoding | 2GIS API with cascading fallback |
| Infra | Docker Compose (PostgreSQL, Backend, Frontend, MCP Server) |

---

## Quick Start

### 1. Clone & configure environment

```bash
git clone <repo-url> && cd freedom_hack
cp .env.example .env
```

Edit `.env` and fill in your API keys:
```dotenv
OPENROUTER_API_KEY=sk-or-v1-your-key-here
TWOGIS_API_KEY=your-2gis-key-here
```

### 2. Build & run everything

```bash
docker compose build
docker compose up -d
```

Wait for all services to become healthy:
```bash
docker compose ps
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| PostgreSQL | localhost:5432 |

### 3. First run — load data

```bash
# Upload tickets CSV
curl -F file=@tickets.csv http://localhost:8000/api/ingest/tickets

# Upload managers CSV
curl -F file=@managers.csv http://localhost:8000/api/ingest/managers

# Upload business units CSV
curl -F file=@business_units.csv http://localhost:8000/api/ingest/business-units
```

### 4. Run the processing pipeline

```bash
# Start pipeline for a batch (get batch_id from ingest response)
curl -X POST http://localhost:8000/api/processing/start/<batch_id>
```

Or use the frontend — click "Загрузить" and the pipeline starts automatically.

---

## Useful Commands

### Docker

```bash
# Build everything
docker compose build

# Build only backend (after code changes)
docker compose build backend

# Start all services
docker compose up -d

# Stop all services
docker compose down

# Restart backend only
docker compose restart backend

# View backend logs (live)
docker compose logs -f backend

# View all logs
docker compose logs -f

# Reset database (wipe all data)
docker compose down -v
docker compose up -d

# Rebuild from scratch (no cache)
docker compose build --no-cache backend
```

### API Endpoints (curl)

```bash
# === Ingestion ===
# Upload tickets
curl -F file=@tickets.csv http://localhost:8000/api/ingest/tickets

# Upload managers
curl -F file=@managers.csv http://localhost:8000/api/ingest/managers

# Upload business units
curl -F file=@business_units.csv http://localhost:8000/api/ingest/business-units

# === Processing ===
# Start pipeline for a batch
curl -X POST http://localhost:8000/api/processing/start/<batch_id>

# Check pipeline status
curl http://localhost:8000/api/processing/status/<batch_id>

# SSE stream (real-time updates)
curl -N http://localhost:8000/api/processing/stream

# === Tickets ===
# List all tickets (paginated)
curl http://localhost:8000/api/tickets?limit=50&offset=0

# Get ticket count
curl http://localhost:8000/api/tickets/count

# Get single ticket by ID
curl http://localhost:8000/api/tickets/<ticket_id>

# Lookup ticket by CSV row number
curl http://localhost:8000/api/tickets/row/<row_index>

# Get batch results
curl http://localhost:8000/api/tickets/batch/<batch_id>

# Export all tickets as CSV
curl http://localhost:8000/api/tickets/export -o results.csv

# === Dashboard ===
curl http://localhost:8000/api/dashboard/stats
curl http://localhost:8000/api/dashboard/types
curl http://localhost:8000/api/dashboard/sentiment
curl http://localhost:8000/api/dashboard/managers
```

### Database

```bash
# Connect to PostgreSQL inside Docker
docker compose exec postgres psql -U fire_user -d fire_db

# Quick queries inside psql:
SELECT count(*) FROM tickets;
SELECT id, ticket_type, sentiment, is_spam, priority_score FROM tickets LIMIT 20;
SELECT stage, status, count(*) FROM processing_states GROUP BY stage, status;
TABLE business_units;
TABLE managers;

# Dump database
docker compose exec postgres pg_dump -U fire_user fire_db > backup.sql

# Reset just the tickets (keep managers/BUs)
docker compose exec postgres psql -U fire_user -d fire_db -c "TRUNCATE tickets, processing_states CASCADE;"
```

### Frontend (local dev)

```bash
cd frontend
bun install
bun dev          # http://localhost:5173
bun run build    # production build → dist/
bun run lint
```

### Backend (local dev, outside Docker)

```bash
cd backend
pip install -r requirements.txt
pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m spacy download ru_core_news_sm

# Run with auto-reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Pipeline Stages

```
CSV Upload → T1 Ingestion → T4 Spam Filter → T3 PII Anonymization
                                                      ↓
                                          ┌───────────┼───────────┐
                                          ↓           ↓           ↓
                                     T5 LLM      T6 Sentiment  T7 Geocoding
                                     Analysis    Analysis       (2GIS)
                                          ↓           ↓           ↓
                                          └───────────┼───────────┘
                                                      ↓
                                            T8 Feature Engineering
                                                      ↓
                                            T9 Priority Scoring
                                                      ↓
                                            T10 Smart Routing
```

- **T4 Spam Filter** — Pre-trained BERT model + structural heuristics (URLs, invisible chars, promo keywords)
- **T3 PII** — Regex (IIN, phone, card, email, full name) + spaCy NER (person names, orgs)
- **T5 LLM** — Gemini Flash via OpenRouter: classifies ticket type + extracts topic + summary
- **T6 Sentiment** — Gemini Flash: 3-class sentiment (positive/neutral/negative)
- **T7 Geocoding** — 2GIS API with Kazakhstan-focused fallback cascade
- **T5–T7 run in parallel** for speed

---

## Project Structure

```
freedom_hack/
├── .env.example          # Environment template (copy to .env)
├── docker-compose.yml    # All services
├── tickets.csv           # Sample ticket data
├── managers.csv          # Manager roster
├── business_units.csv    # Office/BU data
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py              # FastAPI app entry point
│       ├── api/
│       │   ├── ingest.py        # CSV upload endpoints
│       │   ├── tickets.py       # Ticket CRUD + export
│       │   ├── processing.py    # Pipeline control + SSE
│       │   └── dashboard.py     # Analytics endpoints
│       ├── core/
│       │   ├── config.py        # Settings (pydantic-settings)
│       │   ├── database.py      # Async SQLAlchemy engine
│       │   └── sse_manager.py   # Server-Sent Events
│       ├── models/
│       │   ├── models.py        # SQLAlchemy ORM models
│       │   └── schemas.py       # Pydantic request/response
│       └── services/
│           ├── pipeline.py          # Orchestrator (parallel stages)
│           ├── csv_parser.py        # CSV parsing + birth date edge cases
│           ├── spam_filter.py       # HuggingFace BERT spam + structural
│           ├── pii_anonymizer.py    # PII detection & masking
│           ├── llm_analyzer.py      # OpenRouter LLM classification
│           ├── sentiment_analyzer.py # Sentiment via LLM
│           ├── geocoder.py          # 2GIS geocoding + fallbacks
│           └── ...
├── frontend/
│   ├── Dockerfile           # Bun build → Nginx
│   └── src/                 # React + TS + Tailwind
└── docker/
    └── init.sql             # Database schema + enums
```

---

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENROUTER_API_KEY` | OpenRouter API key for LLM calls | **Yes** |
| `TWOGIS_API_KEY` | 2GIS geocoding API key | **Yes** |
| `POSTGRES_USER` | DB username | No (default: `fire_user`) |
| `POSTGRES_PASSWORD` | DB password | No (default: `fire_secret_password`) |
| `POSTGRES_DB` | DB name | No (default: `fire_db`) |
| `DATABASE_URL` | Full async DB URL | No (auto-composed) |
| `OPENROUTER_MODEL` | LLM model ID | No (default: `google/gemini-2.0-flash-001`) |