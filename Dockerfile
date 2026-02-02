FROM python:3.13-slim

# Install system dependencies for PyMuPDF and Psycopg2
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app ./app

# Set Python path to find the app module
ENV PYTHONPATH=/app