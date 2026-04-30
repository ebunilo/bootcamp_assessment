# Web UI, Uvicorn & Docker

## Local dev

```bash
cd bootcamp_assessment
python3 -m uvicorn web_app:app --reload --host 0.0.0.0 --port 9100
```

See [`web_app.py`](../web_app.py) module docstring for env vars (`OPENAI_API_KEY`, `MCP_URL`, LangSmith, etc.).

## Docker

- [`Dockerfile`](../Dockerfile) — Python 3.11 slim, **`PYTHONPATH=/app`**, **`import web_app`** at build, app listens on **9100**.
- Repo root [`docker-compose.yml`](../../docker-compose.yml) — **`build.context: ${COMPOSE_BUILD_CONTEXT:-./bootcamp_assessment}`**, image **`meridian-electronics-web:latest`**, **`9100:9100`**.

```bash
docker compose build --no-cache web && docker compose up -d
```

Open **`http://<host>:9100`**. Production URL (behind Nginx): **`https://bootcamp.igwilo.com`** — see [Architecture](architecture.md).

## Server layout (`bootcamp/` + clone)

```text
bootcamp/
  docker-compose.yml      # from repo parent
  .env                    # secrets
  bootcamp_assessment/    # git clone (Dockerfile + app here)
```

Default **`./bootcamp_assessment`** matches this layout — no **`COMPOSE_BUILD_CONTEXT`** needed unless the app directory path differs.

## Troubleshooting

| Issue | What to check |
|--------|----------------|
| **`Could not import module "web_app"`** / empty **`/app`** | **`docker compose config`**: **`volumes`** must not hide **`/app`**. Remove bad bind mounts / **`docker-compose.override.yml`**. |
| Wrong build context | **`test -f ./bootcamp_assessment/web_app.py`** from compose directory; **`docker compose config`** → **`build.context`**. |
| Stale image | **`docker compose build --no-cache web`**. |
| Image OK, compose broken | **`docker run --rm meridian-electronics-web:latest ls -la /app/web_app.py`** (no Compose volumes). |

Image build runs **`python -c "import web_app"`** — failed build means sources or deps are missing.

- [Architecture](architecture.md) · [MCP](mcp.md)
