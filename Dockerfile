# Used by docker-compose locally and by Hugging Face Spaces (Docker) as the fallback host.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-ron tesseract-ocr-eng poppler-utils libglib2.0-0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Hugging Face Spaces sets PORT=7860; locally it defaults to 8501
ENV PORT=8501 PYTHONUNBUFFERED=1
EXPOSE 8501
CMD streamlit run app/Home.py --server.port=${PORT} --server.address=0.0.0.0 --server.headless=true
