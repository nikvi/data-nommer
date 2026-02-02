import os
import json
import fitz  # PyMuPDF
import requests
from celery import Celery
import google.generativeai as genai
from .database import get_connection

# Celery Setup
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
celery_app = Celery('pdf_tasks', broker=REDIS_URL, backend=REDIS_URL)

# Gemini Setup
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

@celery_app.task(bind=True, name="process_pdf_task")
def process_pdf_task(self, file_data):
    """
    Worker task: Bypasses GIL by running in a separate process.
    file_data contains: name, url, file_id, token
    """
    name = file_data['name']
    url = file_data['url']
    token = file_data['token']
    file_id = file_data['file_id']

    try:
        # 1. Download from Slack
        res = requests.get(url, headers={"Authorization": f"Bearer {token}"})
        pdf_bytes = res.content

        # 2. Gemini AI Metadata Extraction (Structured JSON)
        prompt = "Return JSON: { \"title\": \"str\", \"pub_date\": \"str\" } for this document."
        ai_res = model.generate_content([
            prompt, 
            {"mime_type": "application/pdf", "data": pdf_bytes}
        ])
        metadata = json.loads(ai_res.text)

        # 3. Full Text Extraction (PyMuPDF)
        text = ""
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page in doc:
                text += page.get_text()

        # 4. Save to PostgreSQL
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO pdf_content (title, publication_date, filename, extracted_text, slack_file_id) 
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT (slack_file_id) DO NOTHING""",
            (metadata.get('title'), metadata.get('pub_date'), name, text, file_id)
        )
        conn.commit()
        cur.close()
        conn.close()

        return {"status": "completed", "file": name}
    except Exception as e:
        return {"status": "failed", "error": str(e)}