# Data Nommer

A Slack bot that automatically syncs PDF files from Slack channels, extracts text and metadata using Google Gemini AI, and stores the results in PostgreSQL for search and retrieval.

## Architecture

| Service | Role |
|---------|------|
| **API** (FastAPI + Uvicorn) | REST endpoints for syncing channels and querying documents |
| **Worker** (Celery) | Background PDF processing — downloads from Slack, extracts text via PyMuPDF, gets metadata from Gemini |
| **PostgreSQL** | Stores extracted text, AI-generated metadata, and file references |
| **Redis** | Celery message broker and result backend |

## Prerequisites

- Docker and Docker Compose
- A [Slack Bot Token](https://api.slack.com/authentication/token-types) (`xoxb-...`) with file read permissions
- A [Google Gemini API key](https://ai.google.dev/)

## Setup

1. Create a `.env` file in the project root:

   ```
   SLACK_BOT_TOKEN=xoxb-your-token
   GEMINI_API_KEY=your-gemini-key
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