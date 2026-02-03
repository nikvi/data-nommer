import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from slack_sdk import WebClient
from redis import Redis
from .database import init_db, get_connection
from .tasks import process_pdf_task

slack_client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))
redis_client = Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    yield
    # Shutdown (nothing to do)


app = FastAPI(title="Slack PDF Data Bot", lifespan=lifespan)

@app.get("/health")
def health_check():
    """Verifies internal dependencies are active."""
    try:
        conn = get_connection()
        conn.close()
        redis_client.ping()
        return {"status": "healthy", "database": "up", "redis": "up"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Unhealthy: {str(e)}")

@app.post("/sync/{channel_id}")
def sync_channel(channel_id: str):
    """Incremental sync: Processes only new PDFs since last run."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT MAX(processed_at) FROM pdf_content")
    last_ts = cur.fetchone()[0]
    cur.close()
    conn.close()

    # Use 'oldest' to filter Slack history (incremental run)
    oldest_val = last_ts.timestamp() if last_ts else 0
    response = slack_client.conversations_history(channel=channel_id, oldest=oldest_val)

    queued_count = 0
    for msg in response.get("messages", []):
        for f in msg.get("files", []):
            if f.get("filetype") == "pdf":
                task_data = {
                    "name": f["name"],
                    "url": f["url_private_download"],
                    "file_id": f["id"],
                    "token": os.getenv("SLACK_BOT_TOKEN")
                }
                process_pdf_task.delay(task_data) # Send to Celery Queue
                queued_count += 1

    return {"status": "sync_initiated", "files_queued": queued_count}

@app.get("/documents")
def search_documents(query: str = None):
    """Query processed metadata from PostgreSQL."""
    conn = get_connection()
    cur = conn.cursor()
    if query:
        cur.execute("SELECT title, publication_date, filename FROM pdf_content WHERE title ILIKE %s", (f"%{query}%",))
    else:
        cur.execute("SELECT title, publication_date, filename FROM pdf_content ORDER BY processed_at DESC")
    results = cur.fetchall()
    cur.close()
    conn.close()
    return [{"title": r[0], "date": r[1], "file": r[2]} for r in results]