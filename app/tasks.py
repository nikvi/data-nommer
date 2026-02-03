import os
import json
import fitz  # PyMuPDF
import requests
from celery import Celery
from pydantic import BaseModel
from openai import OpenAI
from .database import get_connection

# Setup
celery_app = Celery('pdf_tasks', broker=os.getenv("REDIS_URL"))
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Structured Output Schema
class DocumentMetadata(BaseModel):
    title: str
    pub_date: str

@celery_app.task(bind=True, name="process_pdf_task",
                 autoretry_for=(Exception,),
                 retry_backoff=True,         
                 retry_kwargs={'max_retries': 5},
                 rate_limit='10/m')

def process_pdf_task(self, file_data):
    name = file_data['name']
    url = file_data['url']
    file_id = file_data['file_id']
    token = file_data['token']

    try:
        # 1. Download File from Slack
        res = requests.get(url, headers={"Authorization": f"Bearer {token}"})
        pdf_bytes = res.content

        # 2. Optimized Text Extraction (First 2 Pages Only)
        text_for_ai = f"FILENAME: {name}\n\n"
        full_text = ""
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            # Extract full text for DB storage
            for i, page in enumerate(doc):
                page_text = page.get_text()
                full_text += page_text
                # Only keep first 2 pages for the AI prompt to save tokens
                if i < 2:
                    text_for_ai += page_text

        # 3. OpenAI Structured Call using Text String
        completion = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "You are a document analyzer. Extract the title and publication date/creation date. "
                        "Note: The date or title might be found within the provided 'FILENAME' "
                        "or within the first few lines of the document text. If a formal date "
                        "is missing, look for year/month patterns in the title or headers."
                    )
                },
                {
                    "role": "user", 
                    "content": text_for_ai
                },
            ],
            response_format=DocumentMetadata,
        )
        
        metadata = completion.choices[0].message.parsed

        # Log token usage
        usage = completion.usage
        print(f"[{name}] Tokens - input: {usage.prompt_tokens}, output: {usage.completion_tokens}, total: {usage.total_tokens}")

        # 4. Save to PostgreSQL
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO pdf_content (title, publication_date, filename, extracted_text, slack_file_id) 
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT (slack_file_id) DO NOTHING""",
            (metadata.title, metadata.pub_date, name, full_text, file_id)
        )
        conn.commit()
        cur.close()
        conn.close()

        return {"status": "success", "file": name}
    except Exception as e:
        return {"status": "failed", "error": str(e)}