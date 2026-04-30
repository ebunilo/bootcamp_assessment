# Build context must be this directory (see repo-root docker-compose.yml).
# On a VPS: copy the whole `bootcamp_assessment/` folder, then:
#   docker build -t meridian-web .

FROM python:3.11-slim-bookworm

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY . /app/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 9100

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9100/api/health', timeout=4)"

CMD ["uvicorn", "web_app:app", "--host", "0.0.0.0", "--port", "9100"]
