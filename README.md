# Data Nommer

A Slack bot that automatically syncs PDF files from Slack channels, extracts text and metadata using an LLM, and stores the results in PostgreSQL for search and retrieval.

## Architecture

```
┌──────────────┐        POST /sync/{channel_id}        ┌──────────────┐
│              │ ─────────────────────────────────────▶ │              │
│    Client    │                                        │   API        │
│              │ ◀───────────────────────────────────── │   (FastAPI)  │
└──────────────┘        GET /documents?query=...        └──────┬───────┘
                                                               │
                                                               │ 1. Query Slack API
                                                               │    for new PDFs
                                                               │
                                                               │ 2. Enqueue task
                                                               ▼
┌──────────────┐                                        ┌──────────────┐
│              │          task dispatch / results        │              │
│    Redis     │ ◀────────────────────────────────────▶ │   Worker     │
│   (Broker)   │                                        │   (Celery)   │
└──────────────┘                                        └──────┬───────┘
                                                               │
                                                               │ For each PDF:
                                                               │  a. Download from Slack
                                                               │  b. Extract metadata (LLM call)
                                                               │  c. Extract full text (PyMuPDF)
                                                               │  d. Store results
                                                               ▼
┌──────────────┐                                        ┌──────────────┐
│  PostgreSQL  │ ◀───────────────────────────────────── │  LLM call   │
│  (Storage)   │          INSERT extracted data          │  (Metadata)  │
└──────────────┘                                        └──────────────┘
```

### Services

| Service | Image / Framework | Role |
|---------|-------------------|------|
| **API** | FastAPI + Uvicorn | REST endpoints for triggering syncs and querying documents. Connects to the Slack API to fetch channel history and dispatches PDF processing tasks to the Celery queue. |
| **Worker** | Celery (×4 concurrency) | Consumes tasks from Redis. For each PDF: downloads the file from Slack, sends the raw bytes to an LLM for metadata extraction (title, publication date), extracts full text with PyMuPDF, and writes everything to PostgreSQL. |
| **PostgreSQL** | postgres:15 | Stores the `pdf_content` table — extracted text, LLM-generated metadata, filenames, and Slack file IDs (deduplicated via `UNIQUE` constraint). Data persisted to a Docker volume. |
| **Redis** | redis:7-alpine | Celery message broker and result backend. |

### Data Flow

1. Client calls `POST /sync/{channel_id}`.
2. API queries the `pdf_content` table for the most recent `processed_at` timestamp and uses it as the `oldest` parameter to the Slack `conversations.history` API, fetching only new messages (incremental sync).
3. For each PDF file attachment found, a task is enqueued to Redis via `process_pdf_task.delay()`.
4. A Celery worker picks up the task and:
   - Downloads the PDF from Slack using the bot token.
   - Sends the raw PDF bytes to an **LLM** with a structured JSON prompt to extract `title` and `pub_date`.
   - Extracts full text page-by-page using **PyMuPDF**.
   - Inserts the results into PostgreSQL (`ON CONFLICT DO NOTHING` to skip duplicates).
5. Client can later query `GET /documents?query=...` to search processed documents by title.

### Database Schema

```sql
pdf_content
├── id               SERIAL PRIMARY KEY
├── title            TEXT            -- LLM-extracted title
├── publication_date TEXT            -- LLM-extracted date
├── filename         TEXT            -- Original Slack filename
├── extracted_text   TEXT            -- Full text via PyMuPDF
├── slack_file_id    TEXT UNIQUE     -- Deduplication key
└── processed_at     TIMESTAMP       -- Auto-set on insert
```

## Prerequisites

- Docker and Docker Compose
- A [Slack Bot Token](https://api.slack.com/authentication/token-types) (`xoxb-...`) with file read permissions
- An LLM API key (currently uses [Google Gemini](https://ai.google.dev/))

## Setup

1. Create a `.env` file in the project root:

   ```
   SLACK_BOT_TOKEN=xoxb-your-token
   GEMINI_API_KEY=your-llm-api-key
   ```

2. Start all services:

   ```bash
   docker compose up --build
   ```

   The API will be available at `http://localhost:8000`.

## API Endpoints

### `GET /health`

Returns the health status of the database and Redis connections.

### `POST /sync/{channel_id}`

Triggers an incremental sync of PDF files from a Slack channel. Only processes files uploaded after the last sync. PDFs are queued for background processing by the Celery worker.

### `GET /documents?query={search_term}`

Searches processed documents by title. Returns all documents if no query is provided.

## Project Structure

```
app/
  main.py       — FastAPI application and API routes
  tasks.py      — Celery worker task for PDF processing
  database.py   — PostgreSQL connection and schema setup
```