FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# onnxruntime (RapidOCR) needs libgomp; Pillow wheels need libgl at runtime
# for some image codecs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libgl1 libglib2.0-0 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY *.py ./
COPY web ./web
COPY resources ./resources
COPY tools ./tools
COPY v3 ./v3
COPY scripts/check_deploy.py ./scripts/check_deploy.py

RUN mkdir -p /app/data

ENV TRAINING_HOST=0.0.0.0 \
    TRAINING_PORT=8766 \
    TRAINING_DB=/app/data/training.sqlite3 \
    ANALYSIS_MATCHES=/app/data/matches \
    ANALYSIS_IMPORTS=/app/data/imports \
    ANALYSIS_OFFICIAL=/app/data/official_replays \
    ANALYSIS_BUILDS=/app/data/builds \
    KPL_RECORDINGS=/app/data/recordings \
    MIMO_OCR_CACHE=/app/data/ocr_cache \
    TRAINING_ALLOW_REMOTE=1

EXPOSE 8766
CMD ["python", "server.py"]
