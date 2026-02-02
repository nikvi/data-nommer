import os
import psycopg2
from psycopg2.extras import execute_values

DB_URL = os.getenv("DATABASE_URL", "postgresql://user:password@db:5432/slack_db")

def get_connection():
    return psycopg2.connect(DB_URL)

def init_db():
    """Initializes the table with specific fields for Gemini-extracted metadata."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS pdf_content (
            id SERIAL PRIMARY KEY,
            title TEXT,
            publication_date TEXT,
            filename TEXT,
            extracted_text TEXT,
            slack_file_id TEXT UNIQUE,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()