# SSO Centralizado + Webhook Dispatcher (MVP)

Stack: Python 3.12, FastAPI, SQLModel, PostgreSQL 16, Redis 7, Alembic, Docker Compose.
Modelo aprobado: 6 tablas, sin `oauth_accounts`, con `service_clients`. JWT `HS256`, `access 15m` + `refresh 7d` rotado. `POST /auth/register` open.

## Quickstart (Git Bash)

```bash
cp .env.example .env
# Editar .env: cambiar JWT_SECRET
docker compose up -d --build
docker compose exec api alembic upgrade head
docker compose exec api pytest -q
```

API: `http://localhost:8000`, docs `http://localhost:8000/docs`, health `GET /health`.

## Endpoints MVP

Auth (`/api/v1/auth`):
- `POST /register` open, `POST /login`, `POST /refresh`, `POST /logout`, `POST /token` (client_credentials), `GET /me`

Webhooks (`/api/v1/webhooks`):
- `POST /endpoints`, `GET /endpoints`
- `POST /events` (requiere header `Idempotency-Key`)
- `GET /deliveries?event_id=&endpoint_id=&status=`
- `POST /deliveries/{id}/retry`

## Dispatcher

Worker `python -m app.workers.dispatch_worker` (servicio `worker` en compose).
Firma `HMAC-SHA256` en header `X-Signature`, 5 intentos, backoff `2/4/8/16/32s`, `timeout 10s`, DLQ `status=dlq`.
Cola Redis `webhook:queue`. Blacklist JWT `blacklist:access:{jti}`, `blacklist:refresh:{jti}`.

## Migraciones

Baseline `alembic/versions/0001_baseline.py` (6 tablas). Desde cero:

```bash
docker compose exec api alembic upgrade head
docker compose exec api alembic revision --autogenerate -m "descripcion"
```

## Tests

```bash
docker compose exec api pytest -q
# local Windows (psycopg3, sin compilación):
pip install --user -r requirements.txt
python -m pytest tests/ -q
```
