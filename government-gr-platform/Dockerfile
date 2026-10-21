FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# OCR stack: Tesseract with Marathi, Hindi, Odia, English packs; OCRmyPDF dependencies (ghostscript, qpdf).
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-eng tesseract-ocr-mar tesseract-ocr-hin tesseract-ocr-ori \
        ghostscript qpdf unpaper pngquant fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 app
WORKDIR /app

COPY requirements.lock pyproject.toml ./
RUN pip install -r requirements.lock && pip install "ocrmypdf>=16.10,<17"

COPY --chown=app:app . .
RUN pip install --no-deps -e .

USER app
EXPOSE 8000
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
