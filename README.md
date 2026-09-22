# sso-webhook-service

A production-ready hybrid **Single Sign-On (SSO)** and **Asynchronous Webhook Dispatcher** service built with a zero-trust security posture. Designed for high availability, cryptographic integrity, and operational observability.

---

## Executive Summary

`sso-webhook-service` combines two critical backend capabilities into a single, containerized deployment:

- **Centralized Authentication (SSO)**: Issues and validates JWT tokens with full OAuth2 flows — including `client_credentials` for machine-to-machine communication — token rotation, and Redis-backed revocation lists.
- **Reliable Webhook Dispatcher**: Asynchronous outbound delivery worker with HMAC-SHA256 signatures, exponential backoff retries, idempotency guarantees, and a Dead-Letter Queue (DLQ) for failed deliveries after exhaustion.

Built for teams that need a secure, auditable, and horizontally scalable event notification backbone alongside identity management — without the overhead of managed SaaS.

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Language** | Python 3.12 |
| **Web Framework** | FastAPI (async, OpenAPI-native) |
| **ORM / Data** | SQLModel (SQLAlchemy + Pydantic) |
| **Database** | PostgreSQL 16 (async via psycopg3) |
| **Cache / Queue / Rate-Limit** | Redis 7 |
| **Migrations** | Alembic |
| **Containerization** | Docker / Docker Compose |
| **Testing** | pytest + httpx (AsyncClient) |
| **Security** | Argon2id (passwords), PyJWT (HS256), HMAC-SHA256 (webhooks) |

---

## Architecture & Key Features

### Authentication (SSO)
- **OAuth2 Flows**: `password` (user login), `client_credentials` (M2M), `refresh_token` rotation
- **JWT Policy**: Access tokens 15 min, Refresh tokens 7 days with rotation + blacklist (JTI in Redis with TTL)
- **Password Hashing**: Argon2id via `argon2-cffi` (memory-hard, side-channel resistant)
- **Rate Limiting**: Fixed-window per IP (configurable per endpoint) with fail-open on Redis unavailability
- **Admin Seeding**: Optional bootstrap via `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD`

### Webhook Dispatcher
- **Async Worker**: Independent Docker service (`worker`) consuming from Redis list `webhook:queue`
- **Cryptographic Signatures**: Every delivery includes `X-Signature: HMAC-SHA256(payload, secret)` + `X-Event-Type` + `X-Idempotency-Key`
- **Retry Policy**: 5 attempts with exponential backoff + jitter (`2s → 4s → 8s → 16s → 32s`)
- **Timeouts**: 10 s per HTTP request (configurable)
- **Dead-Letter Queue**: Exhausted deliveries marked `status=dlq`; manual retry via `POST /webhooks/deliveries/{id}/retry`
- **Idempotency**: `Idempotency-Key` header required on event publish; duplicate keys return existing event

### Data Integrity & Observability
- **Auditing**: Structured `audit_logs` table capturing security-relevant events (failed logins, token issuance, password changes, webhook lifecycle) with IP, user context, and JSON metadata
- **Migrations**: Alembic baseline (6 core tables) + additive migrations; no destructive changes in CI
- **Health Checks**: `/health` (liveness), `/ready` (readiness with DB + Redis probes)

---

## Quick Start

### Prerequisites
- Docker 24+ / Docker Compose v2
- Git

### 1. Clone & Configure
```bash
git clone https://github.com/your-org/sso-webhook-service.git
cd sso-webhook-service

cp .env.example .env
# Edit .env: set a strong JWT_SECRET (>=32 chars), optionally configure seeds
```

### 2. Launch Stack
```bash
docker compose up -d --build
# Services: api (8000), worker, db (5432), redis (6379)
```

### 3. Run Migrations
```bash
docker compose exec api alembic upgrade head
```

### 4. Verify & Test
```bash
# Health checks
curl http://localhost:8000/health    # {"status": "ok"}
curl http://localhost:8000/ready     # {"status": "ready", "db": "ok", "redis": "ok"}

# Run test suite (16 integration + unit tests)
docker compose exec api pytest -q
```

### 4. API Documentation
OpenAPI/Swagger UI: **http://localhost:8000/docs**

---

## API Reference (v1)

All endpoints prefixed with `/api/v1`. Auth endpoints are public; webhook endpoints require a valid Bearer token.

### Authentication (`/auth`)

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/auth/register` | Register new user (open) | — |
| `POST` | `/auth/login` | Email/password → access + refresh tokens | — |
| `POST` | `/auth/refresh` | Rotate refresh token → new access + refresh | — |
| `POST` | `/auth/logout` | Revoke refresh token (blacklist JTI) | — |
| `POST` | `/auth/token` | `client_credentials` → M2M access token | — |
| `GET`  | `/auth/me` | Current user profile | Bearer (user) |
| `POST` | `/auth/password/reset` | Request reset token (returns plain token for dev) | — |
| `POST` | `/auth/password/reset/confirm` | Confirm reset with token + new password | — |

**Example: Login**
```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "supersecret123"}'
```

**Example: M2M Token**
```bash
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"client_id": "dev-worker", "client_secret": "dev-secret-change-me-12345678"}'
```

---

### Webhooks (`/webhooks`)

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/webhooks/endpoints` | Create webhook endpoint (url, secret, event_types) | Bearer (user) |
| `GET`  | `/webhooks/endpoints` | List owned endpoints | Bearer (user) |
| `POST` | `/webhooks/events` | Publish event (requires `Idempotency-Key` header) | Bearer (user) |
| `GET`  | `/webhooks/deliveries` | Query deliveries (filter by event_id, endpoint_id, status) | Bearer (user) |
| `POST` | `/webhooks/deliveries/{id}/retry` | Manual retry of failed/DLQ delivery | Bearer (user) |

**Example: Create Endpoint**
```bash
curl -X POST http://localhost:8000/api/v1/webhooks/endpoints \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://my-service.example.com/webhook",
    "secret": "shared-secret-min-16-chars",
    "event_types": ["user.created", "password.changed"],
    "max_attempts": 5
  }'
```

**Example: Publish Event (Idempotent)**
```bash
curl -X POST http://localhost:8000/api/v1/webhooks/events \
  -H "Authorization: Bearer <access_token>" \
  -H "Idempotency-Key: unique-key-per-business-event" \
  -H "Content-Type: application/json" \
  -d '{"type": "user.created", "payload": {"email": "user@example.com"}}'
```

**Delivery Payload Sent to Your Endpoint**
```json
{
  "type": "user.created",
  "payload": { "email": "user@example.com" }
}
```
Headers:
- `X-Signature: <hmac-sha256-hex>`
- `X-Event-Type: user.created`
- `X-Idempotency-Key: unique-key-per-business-event`

---

## Configuration (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `JWT_SECRET` | **required** | HS256 signing key (≥32 chars) |
| `JWT_ALG` | `HS256` | JWT algorithm |
| `ACCESS_TOKEN_MINUTES` | `15` | Access token TTL |
| `REFRESH_TOKEN_DAYS` | `7` | Refresh token TTL |
| `PASSWORD_RESET_TOKEN_MINUTES` | `15` | Reset token TTL |
| `WEBHOOK_TIMEOUT_SECONDS` | `10` | HTTP timeout for deliveries |
| `WEBHOOK_MAX_ATTEMPTS` | `5` | Max delivery attempts |
| `WEBHOOK_BACKOFF_BASE_SECONDS` | `2` | Base for exponential backoff |
| `WEBHOOK_HMAC_HEADER` | `X-Signature` | Signature header name |
| `RATE_LIMIT_AUTH_PER_MINUTE` | `10` | Login/register rate limit |
| `RATE_LIMIT_TOKEN_PER_MINUTE` | `20` | M2M token rate limit |
| `SEED_CLIENT_ID` | — | Optional M2M client bootstrap |
| `SEED_CLIENT_SECRET` | — | Optional M2M secret |
| `SEED_ADMIN_EMAIL` | — | Optional admin user bootstrap |
| `SEED_ADMIN_PASSWORD` | — | Optional admin password |

---

## Project Structure

```
.
├── alembic/                 # Migrations (baseline + additive)
├── app/
│   ├── api/                 # FastAPI routers (auth, webhooks, health)
│   ├── core/                # Config, DB, Redis, security, deps, rate-limit
│   ├── models/              # SQLModel definitions (User, ServiceClient, RefreshToken, PasswordResetToken, AuditLog, Webhook*)
│   ├── schemas/             # Pydantic request/response models
│   ├── services/            # Business logic (auth, webhook, audit, dispatcher)
│   └── workers/             # Background worker (dispatch_worker)
├── tests/                   # pytest + httpx (unit + integration)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## Testing

```bash
# All tests (runs inside container with real DB/Redis)
docker compose exec api pytest -q

# Specific suites
docker compose exec api pytest tests/test_baseline.py -q      # Unit / contract
docker compose exec api pytest tests/test_integration.py -q   # Real DB/Redis
docker compose exec api pytest tests/test_hardening.py -q     # Rate-limit, /ready, seed
```

Coverage targets: ≥80% on auth + dispatcher paths.

---

## Security Considerations

- **No hardcoded secrets**: All via `.env` / `pydantic-settings`
- **Argon2id** for password hashing (OWASP-recommended)
- **JWT blacklist** in Redis with TTL matching token lifetime
- **HMAC-SHA256** on every webhook delivery (verify on receiver side)
- **Rate limiting** on all auth endpoints (per-IP, fixed window)
- **Fail-open** rate limiting: if Redis unavailable, requests proceed
- **Idempotency keys** prevent duplicate event processing
- **Separate audit sessions** avoid FK rollback on auth failures

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Contributing

1. Fork → feature branch → PR with tests
2. `pytest -q` must pass locally
3. Follow existing code style (type hints, async/await, PEP 8)

---

**Built with discipline. Ready for production.**