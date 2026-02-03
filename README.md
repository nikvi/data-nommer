# Data Nommer

A Slack bot that automatically syncs PDF files from Slack channels, extracts text and metadata using OpenAI, and stores the results in PostgreSQL for search and retrieval.

## Architecture

```
┌──────────────┐        POST /sync/{channel_id}         ┌──────────────┐
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
│              │          task dispatch / results       │              │
│    Redis     │ ◀────────────────────────────────────▶ │   Worker     │
│   (Broker)   │                                        │   (Celery)   │
└──────────────┘                                        └──────┬───────┘
                                                              │
                                                              │ For each PDF:
                                                              │  a. Download from Slack
                                                              │  b. Extract text (PyMuPDF)
                                                              │  c. Extract metadata (OpenAI)
                                                              │  d. Store results
                                                              ▼
┌──────────────┐                                        ┌──────────────┐
│  PostgreSQL  │ ◀───────────────────────────────────── │   OpenAI     │
│  (Storage)   │          INSERT extracted data         │  (Metadata)  │
└──────────────┘                                        └──────────────┘

┌──────────────┐
│   Flower     │  Real-time task monitoring (http://localhost:5555)
│  (Monitor)   │
└──────────────┘
```

### Services

| Service | Image / Framework | Role |
|---------|-------------------|------|
| **API** | FastAPI + Uvicorn | REST endpoints for triggering syncs and querying documents. Connects to the Slack API to fetch channel history and dispatches PDF processing tasks to the Celery queue. |
| **Worker** | Celery (×4 concurrency) | Consumes tasks from Redis. For each PDF: downloads the file from Slack, extracts text with PyMuPDF (first 2 pages for AI, full text for storage), sends to OpenAI for metadata extraction (title, publication date), and writes everything to PostgreSQL. Includes auto-retry with exponential backoff and rate limiting. |
| **PostgreSQL** | postgres:15 | Stores the `pdf_content` table — extracted text, OpenAI-generated metadata, filenames, and Slack file IDs (deduplicated via `UNIQUE` constraint). Data persisted to a Docker volume. |
| **Redis** | redis:7-alpine | Celery message broker and result backend. |
| **Flower** | mher/flower | Real-time Celery task monitoring dashboard. |

### Data Flow

1. Client calls `POST /sync/{channel_id}`.
2. API queries the `pdf_content` table for the most recent `processed_at` timestamp and uses it as the `oldest` parameter to the Slack `conversations.history` API, fetching only new messages (incremental sync).
3. For each PDF file attachment found, a task is enqueued to Redis via `process_pdf_task.delay()`.
4. A Celery worker picks up the task and:
   - Downloads the PDF from Slack using the bot token.
   - Extracts full text page-by-page using **PyMuPDF** (first 2 pages sent to AI to save tokens).
   - Sends the text to **OpenAI** (`gpt-4o-mini`) with structured output to extract `title` and `pub_date`.
   - Inserts the results into PostgreSQL (`ON CONFLICT DO NOTHING` to skip duplicates).
5. Client can later query `GET /documents?query=...` to search processed documents by title.

### Database Schema

```sql
pdf_content
├── id               SERIAL PRIMARY KEY
├── title            TEXT            -- OpenAI-extracted title
├── publication_date TEXT            -- OpenAI-extracted date
├── filename         TEXT            -- Original Slack filename
├── extracted_text   TEXT            -- Full text via PyMuPDF
├── slack_file_id    TEXT UNIQUE     -- Deduplication key
└── processed_at     TIMESTAMP       -- Auto-set on insert
```

## Prerequisites

- Docker and Docker Compose
- A Slack Bot Token (`xoxb-...`) — see [Slack Bot Setup](#slack-bot-setup) below
- An [OpenAI API key](https://platform.openai.com/api-keys)

## Slack Bot Setup

### 1. Create the Slack App

1. Go to the [Slack API: Your Apps](https://api.slack.com/apps) page
2. Click **Create New App** and select **From scratch**
3. Name your app (e.g., "Data Nommer") and select your workspace
4. Click **Create App**

### 2. Configure Bot Token Scopes

1. Navigate to **OAuth & Permissions** in the sidebar
2. Scroll to **Bot Token Scopes**
3. Add the following scopes:

| Scope | Permission Granted |
|-------|-------------------|
| `channels:read` | View basic info about public channels (names, topics) |
| `channels:history` | View messages and events in public channels |
| `groups:read` | View basic info about private channels the bot is in |
| `groups:history` | View messages and events in private channels |
| `files:read` | Access file content and download URLs |
| `users:read` | View list of users and their profile info |
| `users:read.email` | View email addresses of people in the workspace |
| `team:read` | View the workspace name, domain, and icon |
| `im:history` | View messages in direct messages with the bot |
| `app_mentions:read` | View messages that directly mention the bot |
| `remote_files:read` | *(Optional)* Access files hosted outside Slack (e.g., Google Drive links) |

### 3. Install and Get Token

1. Click **Install to Workspace** at the top of the OAuth & Permissions page
2. Authorize the app
3. Copy the **Bot User OAuth Token** (`xoxb-...`)
4. Add it to your `.env` file as `SLACK_BOT_TOKEN`

### 4. Invite Bot to Channels

The bot can only access channels it's been invited to:

```
/invite @YourBotName
```

## Setup

1. Create a `.env` file in the project root:

   ```
   SLACK_BOT_TOKEN=xoxb-your-token
   OPENAI_API_KEY=sk-your-openai-key
   ```

2. Start all services:

   ```bash
   docker compose up --build
   ```

   The API will be available at `http://localhost:8000`.

   Flower monitoring dashboard will be available at `http://localhost:5555`.

## API Endpoints

### `GET /health`

Returns the health status of the database and Redis connections.

### `POST /sync/{channel_id}`

Triggers an incremental sync of PDF files from a Slack channel. Only processes files uploaded after the last sync. PDFs are queued for background processing by the Celery worker.The channel ID is present in the slack channel description.
Example call/: http://localhost:8000/sync/C09JL0DMFFE
### `GET /documents?query={search_term}`

Searches processed documents by title. Returns all documents if no query is provided.

## Project Structure

```
app/
  main.py       — FastAPI application and API routes
  tasks.py      — Celery worker task for PDF processing
  database.py   — PostgreSQL connection and schema setup
tests/
  conftest.py      — Pytest fixtures and environment setup
  test_main.py     — API endpoint tests
  test_tasks.py    — Celery task tests
  test_database.py — Database function tests
```

## Running Tests

```bash
docker compose exec api pytest tests/ -v
```

## Worker Configuration

The Celery worker includes:
- **Auto-retry**: Retries failed tasks with exponential backoff (up to 5 retries)
- **Rate limiting**: 10 tasks per minute to avoid hitting API limits
- **Concurrency**: 4 parallel workers
- **Non-root execution**: Runs as `nobody` user for security

---

## Design Decisions

### Database Schema Rationale

| Column | Type | Why |
|--------|------|-----|
| `id` | SERIAL | Auto-incrementing primary key for internal references |
| `title` | TEXT | LLM-extracted; TEXT over VARCHAR for flexibility with long titles |
| `publication_date` | TEXT | Stored as TEXT (not DATE) because LLM output varies ("2024", "January 2024", "Q1 2024") — parsing can happen at query time |
| `filename` | TEXT | Original Slack filename preserved for traceability |
| `extracted_text` | TEXT | Full document text enables future full-text search without re-processing |
| `slack_file_id` | TEXT UNIQUE | **Deduplication key** — prevents reprocessing the same file; `ON CONFLICT DO NOTHING` makes syncs idempotent |
| `processed_at` | TIMESTAMP DEFAULT | Auto-set on insert; used for incremental sync (`oldest` parameter to Slack API) |

**Why no indexes?** For the current scale (hundreds to low thousands of documents), sequential scans are fast enough. Add indexes on `title` or `slack_file_id` if query performance degrades.

### Multiprocessing Strategy

**Why Celery with separate worker processes?**

1. **Bypasses Python's GIL**: PDF text extraction (PyMuPDF) and network I/O (Slack download, OpenAI API) are CPU and I/O bound. Running in separate processes allows true parallelism.

2. **Decouples API from processing**: The FastAPI server returns immediately after enqueuing tasks. Long-running PDF processing doesn't block API responses.

3. **Fault isolation**: A crashed worker doesn't affect the API or other workers. Celery automatically restarts failed tasks.

4. **Scalability**: Can scale workers independently by increasing `--concurrency` or adding more worker containers.

**Why 4 workers?** Balanced for typical workloads — enough parallelism for batch syncs without overwhelming OpenAI rate limits (10 requests/minute configured).

### Error Handling Approach

| Error Type | Handling | Rationale |
|------------|----------|-----------|
| **Network errors** (Slack download, OpenAI timeout) | Auto-retry with exponential backoff | Transient failures often resolve on retry |
| **Rate limits** (OpenAI 429) | Auto-retry + rate limiting (10/min) | Prevents hammering the API; backoff allows quota reset |
| **Invalid PDF** (corrupt file) | Fail task, log error | No point retrying; requires manual intervention |
| **Database errors** | Fail task, log error | Typically configuration issues; auto-retry unlikely to help |
| **Duplicate file** | `ON CONFLICT DO NOTHING` | Silently skip — idempotent by design |

**Why `autoretry_for=(Exception,)`?** Broad retry coverage for unexpected errors. Max 5 retries with exponential backoff prevents infinite loops while handling transient issues.

### Trade-offs

| Decision | Trade-off | Why We Chose This |
|----------|-----------|-------------------|
| **First 2 pages to AI only** | May miss metadata in later pages | 80%+ of documents have title/date on first pages; saves ~60% tokens |
| **No PDF storage** | Can't retrieve original files | Reduces storage costs; Slack is the source of truth; can re-download if needed |
| **TEXT for dates** | Requires parsing for date queries | LLM output is inconsistent; storing raw preserves information |
| **Pull model (polling)** vs webhooks | Requires manual sync trigger | Simpler setup; no public endpoint needed; works behind firewalls |
| **Single table** | No normalization | Simpler queries; documents are independent entities; no complex relationships |
| **gpt-4o-mini** | Less capable than gpt-4o | 10x cheaper; metadata extraction is simple enough for mini |
| **Sync locking** | No concurrent sync protection | Deduplication via `ON CONFLICT` makes this safe; added complexity not worth it |

### Token Usage

Each PDF processing call uses approximately:
- **Input**: ~70 tokens (system prompt) + 500-3000 tokens (first 2 pages)
- **Output**: ~20-50 tokens (structured JSON)
- **Cost**: ~$0.0003 per PDF with gpt-4o-mini

Token usage is logged to worker output for monitoring.

---

## Future Improvements

### RAG (Retrieval-Augmented Generation)

Add vector embeddings for semantic search and Q&A over documents:

- **pgvector**: PostgreSQL extension to store embeddings alongside existing data
- **Chunking**: Split documents into ~500 token chunks for better retrieval
- **Q&A endpoint**: `POST /ask` to answer questions using retrieved context

```sql
-- Future schema addition
ALTER TABLE pdf_content ADD COLUMN embedding vector(1536);
CREATE INDEX ON pdf_content USING ivfflat (embedding vector_cosine_ops);
```

### Real-time Slack Events

Replace pull model with push:
- Use Slack Events API to process PDFs immediately on upload
- Requires public endpoint or ngrok for development

### Full-Text Search

Leverage PostgreSQL's built-in FTS for better search:

```sql
ALTER TABLE pdf_content ADD COLUMN search_vector tsvector;
CREATE INDEX idx_fts ON pdf_content USING GIN(search_vector);
```

### Additional Enhancements

| Feature | Description |
|---------|-------------|
| **Content-based deduplication** | Hash PDF bytes to detect same file uploaded with different Slack IDs |
| **Multi-channel scheduled sync** | Celery Beat to sync all channels on a schedule |
| **Better metadata extraction** | Author, page count, document type, language detection |
| **Table extraction** | Parse tables into structured JSON |
| **Image OCR** | Extract text from scanned PDFs using OCR  |
| **Observability** | Prometheus metrics, OpenTelemetry tracing |
| **Authentication** | API key auth, role-based access, audit logging |
