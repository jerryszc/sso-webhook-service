# SSO Auth Service & Webhook Dispatcher

**[Versión en español →](README.md)**

Identity service with OAuth2, token rotation and a Redis-backed blacklist, plus a webhook
dispatcher signed with HMAC, exponential backoff retries, a dead-letter queue (DLQ) and
mandatory idempotency.

[![CI](https://github.com/jerryszc/sso-webhook-service/actions/workflows/ci.yml/badge.svg)](https://github.com/jerryszc/sso-webhook-service/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688.svg)](https://fastapi.tiangolo.com/)
[![Tests](https://img.shields.io/badge/tests-16%20passing%20%7C%20real%20PG%20%2B%20Redis-brightgreen.svg)](tests)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED.svg)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Stack:** Python 3.12 · FastAPI (async) · SQLAlchemy async · psycopg 3 · PostgreSQL 16 · Redis 7 · Argon2id · PyJWT (HS256) · Alembic · Pytest · httpx · Docker

---

## The business problem

This service solves two problems that always show up together in any platform integrating
third parties, and that are expensive to ignore.

### 1. Integrations break when the receiver is unavailable

A system that notifies a partner (a marketplace, a payment gateway, a logistics system)
discovers that **HTTP does not guarantee delivery**. The receiver may be down, may return a
500, or the network may drop mid-request. A naive design produces two opposite failures, and
both are expensive:

| Naive behaviour | Consequence |
| :--- | :--- |
| If delivery fails, drop the event | The partner never finds out. A charge that was collected never produces a shipment. The customer paid and nobody knows. |
| If delivery fails, retry forever | The downed receiver gets millions of requests. The outage spreads, resources are exhausted on both sides, and the original event still never lands. |

**What this service does**

| Mechanism | How it solves the problem |
| :--- | :--- |
| **Exponential backoff retries** | 5 attempts with waits of 2s, 4s, 8s, 16s and 32s. This gives a receiver with a momentary problem time to recover without hammering it |
| **Dead-letter queue (DLQ)** | After 5 attempts the delivery moves to `status = "dlq"` instead of vanishing. No event is ever silently lost, and it stays queryable through the API |
| **Manual retry** | `POST /webhooks/deliveries/{id}/retry` pulls a delivery out of the DLQ. An operator fixes the root cause and reactivates the event without reprocessing anything |
| **Mandatory idempotency key** | `Idempotency-Key` is required on publish. If the client resends the same event, the service detects it and does not dispatch it twice, so the receiver never processes a charge twice |
| **HMAC-SHA256 signature** | Every delivery carries the payload signature. The receiver verifies the message is authentic and untampered in transit, rather than trusting the channel alone |

The idempotency chain is what closes the problem. Without it, a retry after a timed-out
request produces a **double charge** at the receiver: the original request did arrive, only
the response was lost. With the key, the second attempt is recognised and discarded.

### 2. Authentication spreads and degrades

Every integration that builds its own login duplicates credentials, multiplies the attack
surface and produces inconsistencies: one uses bcrypt, another SHA-256, a third never
expires sessions. When one of them leaks, the damage is not contained.

| Problem | How this service addresses it |
| :--- | :--- |
| Credentials duplicated per integration | A single source of token issuance. Services authenticate against it, not against the user database |
| Passwords hashed with a weak algorithm or no salt | **Argon2id** via `argon2-cffi`, the winner of the Password Hashing Competition. Verified in `test_password_hash_roundtrip` |
| Session theft via refresh token | **Rotation** on every use: the refresh issues a new token and the old one becomes invalid. If an attacker reuses a stolen token, the rotation exposes them |
| No way to revoke a specific session | **Redis blacklist** keyed by `jti` with a TTL. Logout invalidates that specific token, which then expires on its own |
| Brute force against login | Rate limiting per IP and per scope: 10 req/min on register, login and password reset; 20 req/min on the token endpoint |
| "Who accessed what, and from where?" | An `audit_log` table with configurable retention (90 days by default), with **dedicated tests** on the three critical events |

---

## Use case: two services that always travel together

This repository combines authentication and webhook dispatch because they show up together in
the same kind of company: a platform with **its own users** that also **notifies third-party
systems**. Companies that grow quickly get there by duplication, with one login per service
and a loose script per integration. This is the case it is designed for.

**Where it fits inside a real organisation**

| Context | How it is used | Why this design |
| :--- | :--- | :--- |
| **Internal SSO for a company running several services** | Every service validates the same token instead of implementing its own login | One entry point and one revocation point. Signing out in one place signs out everywhere, and `audit_log` answers who accessed what |
| **Event notification to external partners** | The system publishes changes to a marketplace, a payment gateway or a carrier | Exponential backoff and the DLQ stop a downed receiver from being hammered and stop an event disappearing silently |
| **Multi-tenant B2B platform** | Each customer holds its own machine credentials (`client_credentials`) | The `client_credentials` flow lets a backend call the API with no human user behind it |
| **A system that must answer "who did this?"** | `audit_log` retains 90 days by default, configurable | Serves internal review and answers an audit without instrumenting every endpoint by hand |

**Why one service and not two**

This is a debatable decision, and it is worth being able to justify:

- **For combining them:** identity and webhooks share a need for *auditing, cryptographic
  signing and event traceability*. The `audit_log` table serves both, and the HMAC protecting
  an outbound webhook is the same discipline that protects a token.
- **For splitting them:** it couples two domains that evolve at different rates, and forces
  two services that need not fail together to be deployed together. In a larger organisation
  this separation would be the sensible choice.

They are combined because it makes the reasoning easier to show: the same principle applied
to both halves.

**What this adds over "a login and a `requests.post()`"**

- **Delivery is neither lost nor duplicated.** The mandatory idempotency key and the DLQ cover
  the two expensive failures: losing a shipping order because the carrier was down, or
  charging twice because the client resent after not getting a response.
- **A thief who steals a refresh token exposes themselves.** Each use issues a new token and
  marks the previous one as rotated. If anyone reuses the old one, the rotation makes it
  visible.
- **A session can genuinely be revoked.** The Redis blacklist keyed on `jti` invalidates one
  specific session without waiting for it to expire, with its TTL matched to the token's own
  lifetime.
- **Brute force has a brake.** 10 req/min on register, login and password reset; 20 on the
  token endpoint. Limits are per scope and per IP, not one global value.

**What would be needed before production**

- **The rate limiter is deliberately fail-open.** If Redis does not respond the limit is not
  applied: the system prefers being available over being protected. That is a conscious
  decision, and its cost is that a Redis outage removes the brute-force defence. Compensate at
  the load balancer or CDN.
- **The signing secret is shared.** HMAC requires the sender and receiver to share a key. With
  several receivers each needs its own, and rotation and revocation have to be decided. There
  is a single global secret today.
- **Split the two services** as soon as one of them grows traffic independently, or when
  identity has to serve organisations that do not use the dispatcher.
- **A key per receiver and planned rotation**, instead of one global secret.
- **Alerting on the DLQ.** The queue exists and is queryable through the API, but without
  monitoring an event can sit in `status = "dlq"` for weeks unnoticed.

**Which role this work maps to**

Backend Developer in identity, payment gateways or integration platforms. It is trust-boundary
work: deciding what gets verified, where, and which error is returned without revealing
whether a user exists.

---

## Verifiable impact

**16 tests** across 3 modules. CI runs them against **real PostgreSQL 16 and Redis 7**
(service containers, not SQLite or mocks), because token rotation, blacklisting and rate
limiting all depend on Redis behaving properly.

| Behaviour | Test that proves it |
| :--- | :--- |
| The full register → login → me → refresh → logout cycle works | `test_register_login_me_refresh_logout` |
| The `client_credentials` flow (machine-to-machine) issues tokens | `test_client_credentials_flow` |
| Publishing the same event twice with the same key dispatches once | `test_webhook_publish_idempotent` |
| Backoff growth is exponential, not linear | `test_backoff_growth` |
| The HMAC signature verifies and changes when the payload changes | `test_hmac_signature` |
| The password hash round-trips and never stores plaintext | `test_password_hash_roundtrip` |
| Rate limiting blocks once the limit is exceeded | `test_rate_limit_blocks` |
| Rate limiting is scoped: login and register do not share a counter | `test_rate_limit_blocks` |
| A failed login is recorded in the audit trail | `test_audit_logs_on_login_failed` |
| Issuing a machine-to-machine token is audited | `test_audit_logs_on_m2m_token` |
| Creating a webhook endpoint is audited | `test_audit_logs_on_webhook_created` |
| The password reset flow works end to end | `test_password_reset_flow` |
| A non-existent email in reset does not leak whether the account exists | `test_password_reset_nonexistent_email` |
| The admin seed is idempotent | `test_seed_admin_idempotent` |
| `/ready` distinguishes "alive" from "able to serve traffic" | `test_ready_ok` |

---

## Architecture

```
app/
├── main.py                     # Routers, /api/v1 prefix, lifespan
├── api/
│   ├── auth.py                 # register, login, token, refresh, logout,
│   │                           # password/reset, password/reset/confirm, me
│   ├── webhooks.py             # endpoints, events, deliveries, retry
│   └── health.py               # /health and /ready (unprefixed)
├── core/
│   ├── config.py               # Pydantic Settings
│   ├── db.py                   # Async engine + per-request session
│   ├── redis.py                # Redis client (TTL, blacklists)
│   ├── security.py             # Argon2id + JWT (HS256) with jti
│   ├── ratelimit.py            # Fixed window over Redis
│   ├── deps.py                 # Auth dependencies
│   └── seed.py                 # Idempotent initial admin
├── models/                     # User, RefreshToken, ServiceClient,
│                               # PasswordResetToken, WebhookEndpoint,
│                               # WebhookEvent, WebhookDelivery, AuditLog
├── schemas/                    # Request/response contracts
├── services/
│   ├── auth_service.py         # Issue, rotate, revoke, audit
│   ├── webhook_service.py      # Endpoint registration and publishing
│   ├── dispatcher.py           # HMAC signing and backoff calculation
│   └── audit_service.py        # Audit writes
└── workers/
    └── dispatch_worker.py      # HTTP send, retries, DLQ
```

**The backoff calculation** (`app/services/dispatcher.py`) is the simplest and most
important piece of the dispatcher:

```python
def compute_backoff(attempt: int) -> timedelta:
    # attempt 1-based: 2s, 4s, 8s, 16s, 32s (base configurable)
    base = settings.webhook_backoff_base_seconds
    return timedelta(seconds=base * (2 ** (attempt - 1)))
```

And the signature uses **canonical JSON** — sorted keys, no whitespace — so the same logic
always produces the same HMAC, regardless of how the receiver reconstructs the payload:

```python
def sign_payload(payload: dict[str, Any], secret: str) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
```

---

## Data model

**8 tables.**

| Table | Purpose | Key fields |
| :--- | :--- | :--- |
| `user` | Human users | email, `password_hash` (Argon2id), `is_active` |
| `service_client` | Machine-to-machine services | `client_id`, `client_secret` (hashed), `scopes` |
| `refresh_token` | Issued refresh tokens | `jti` (unique), `user_id`, `service_client_id`, `expires_at`, `rotated_from_jti` |
| `password_reset_token` | Single-use reset tokens | `expires_at`, `used` |
| `webhook_endpoint` | Notification targets | `url`, `secret` (for the HMAC), `max_attempts` (overrides the global) |
| `webhook_event` | Published events | `type`, `payload`, `idempotency_key` (unique), `source` |
| `webhook_delivery` | One event against one endpoint | `attempt`, `status` (`success`/`dlq`/...), `http_status`, `error`, `next_retry_at` |
| `audit_log` | Security trail | actor, action, result, timestamp; 90-day retention |

**Rotation leaves a trail:** `rotated_from_jti` chains each refresh to its predecessor. A
reused refresh is detectable because its `jti` has already been rotated and no longer
matches the live chain.

---

## API

`/api/v1` prefix on auth and webhooks. The health routes are **deliberately unprefixed**: a
load balancer should not have to know the API's versioning.

### Authentication
| Method | Path | Description | Rate limit |
| :--- | :--- | :--- | :--- |
| POST | `/api/v1/auth/register` | Create account (201) | 10/min per IP |
| POST | `/api/v1/auth/login` | Login, returns access + refresh | 10/min per IP |
| POST | `/api/v1/auth/token` | `client_credentials` (M2M) | 20/min per IP |
| POST | `/api/v1/auth/refresh` | Rotates the refresh token | — |
| POST | `/api/v1/auth/logout` | Revokes and blacklists (204) | — |
| POST | `/api/v1/auth/password/reset` | Request a reset | 10/min per IP |
| POST | `/api/v1/auth/password/reset/confirm` | Confirm the reset | 10/min per IP |
| GET | `/api/v1/auth/me` | Authenticated user | — |

### Webhooks
| Method | Path | Description |
| :--- | :--- | :--- |
| POST | `/api/v1/webhooks/endpoints` | Register a target (201) |
| GET | `/api/v1/webhooks/endpoints` | List targets |
| POST | `/api/v1/webhooks/events` | Publish an event. **Requires `Idempotency-Key`** |
| GET | `/api/v1/webhooks/deliveries` | Query deliveries and their status |
| POST | `/api/v1/webhooks/deliveries/{id}/retry` | Retry a DLQ delivery |

### Health
| Method | Path | Description |
| :--- | :--- | :--- |
| GET | `/health` | The process is alive |
| GET | `/ready` | The database responds: it can take traffic |

The split between `/health` and `/ready` is intentional: during a deployment, restarting
the instance when Redis is already unreachable only produces more failed traffic, not less.

### Idempotency on publish

```bash
curl -X POST http://localhost:8000/api/v1/webhooks/events \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: order-paid-8841" \
  -H "Content-Type: application/json" \
  -d '{"type":"order.paid","payload":{"order_id":8841,"amount":129.90},"source":"checkout"}'
```

Without the header the response is **422** with `"Idempotency-Key required"`. With it,
repeating the same call does not create a second event: this is exactly the scenario where
a client retry would cause a double charge at the receiver.

---

## Security

**Passwords:** Argon2id (`argon2-cffi`), the winner of the Password Hashing Competition,
resistant both to GPU attacks and to large-memory attacks.

**Access tokens:** 15 minutes, JWT HS256, with a unique `jti` per token.

**Refresh tokens:** 7 days, rotated on every use, with `rotated_from_jti` recording the
chain.

**Revocation:** Redis blacklist keyed `blacklist:refresh:{jti}` with a TTL equal to the
token's remaining lifetime, so the list self-cleans instead of growing unbounded.

**Rate limiting:** fixed window over Redis, keyed by real IP — it reads `X-Forwarded-For`
to detect the client behind a proxy. Separate scopes per endpoint.

> **Documented tradeoff: rate limiting is *fail-open*.** If Redis does not respond, the
> function catches the exception and allows the request through instead of rejecting it.
> The choice is deliberate — a downed Redis should not make the whole platform's
> authentication unreachable — but it carries an explicit cost: **if Redis falls, the
> brute-force defence disappears**, and it has to be compensated with a WAF or edge rate
> limiting. It is a conscious decision, not an oversight, which is why it is written down.

**Webhook signing:** HMAC-SHA256 over canonical JSON, in the `X-Signature` header (name
configurable via `WEBHOOK_HMAC_HEADER`). Every delivery also carries `X-Event-Type` and
`X-Idempotency-Key`.

**Sensitive setting:** `jwt_secret` defaults to `change-me-in-env` and **must** be changed
before deploying.

---

## Tests

**16 tests** across 3 modules.

| Module | Tests | Covers |
| :--- | :--- | :--- |
| `test_integration.py` | 8 | Full auth cycle, `client_credentials`, webhook idempotency, password reset flow, non-existent email, and three dedicated audit tests |
| `test_baseline.py` | 5 | Health, registration validation, Argon2id round-trip, HMAC signature, backoff growth |
| `test_hardening.py` | 3 | `/ready`, rate limiting, seed idempotency |

```bash
# Requires PostgreSQL and Redis running
docker compose up -d db redis
docker compose exec api alembic upgrade head

pytest -q
pytest --cov=app --cov-report=term-missing
```

---

## Continuous integration

This repository's CI is the most demanding of the four projects, because the tests depend
on real infrastructure.

| Job | What it does |
| :--- | :--- |
| **Lint** | `ruff check .` and `ruff format --check .` |
| **Typecheck** | `mypy app` in strict mode |
| **Tests** | Pytest against **PostgreSQL 16 and Redis 7 service containers** |
| **Docker Build & Smoke Test** | Builds the image and verifies boot with compose |
| **Notify on Failure** | Aggregator with `needs` across the four above |

**Details that make this CI reliable rather than decorative:**

- **Tests run against the real database.** SQLite or mocks would let the tests pass even if
  token rotation or rate limiting were broken, because the behaviour depends on Redis and
  PostgreSQL for real.
- **Pure-Python readiness wait.** The runner does not ship `pg_isready` or `redis-cli`, so
  the workflow waits with a loop that opens TCP sockets against both ports instead of
  assuming a `sleep` is enough.
- **Migrations run before the tests**, with the same environment variables the tests use, so
  the schema always matches the code under test.
- **Coverage is uploaded** as an artifact.

---

## Quick start

**Requirements:** Docker Desktop running.

```bash
# 1. Clone and enter
git clone https://github.com/jerryszc/sso-webhook-service.git
cd sso-webhook-service

# 2. Configure
cp .env.example .env
#   First thing: change JWT_SECRET

# 3. Bring up API + PostgreSQL 16 + Redis 7
docker compose up --build -d

# 4. Verify
curl http://localhost:8000/health
curl http://localhost:8000/ready

# 5. Docs
#    http://localhost:8000/docs
```

```bash
# Tear down
docker compose down
docker compose down -v
```

### Local development without Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

### Migrations

```bash
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic current
```

---

## Environment variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `APP_ENV` | `dev` | Runtime environment |
| `API_V1_PREFIX` | `/api/v1` | Prefix for versioned routes |
| `DATABASE_URL` | `postgresql+psycopg://sso:sso@localhost:5432/sso` | Async connection |
| `SYNC_DATABASE_URL` | `postgresql+psycopg://sso:sso@localhost:5432/sso` | Sync connection (Alembic) |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for blacklist and rate limiting |
| `JWT_SECRET` | `change-me-in-env` | **Change in production** |
| `JWT_ALG` | `HS256` | Signing algorithm |
| `ACCESS_TOKEN_MINUTES` | `15` | Access token lifetime |
| `REFRESH_TOKEN_DAYS` | `7` | Refresh token lifetime |
| `WEBHOOK_TIMEOUT_SECONDS` | `10` | Per-delivery timeout |
| `WEBHOOK_MAX_ATTEMPTS` | `5` | Attempts before DLQ |
| `WEBHOOK_BACKOFF_BASE_SECONDS` | `2` | Backoff base (2, 4, 8, 16, 32) |
| `WEBHOOK_HMAC_HEADER` | `X-Signature` | Signature header name |
| `RATE_LIMIT_AUTH_PER_MINUTE` | `10` | Limit for register, login, reset |
| `RATE_LIMIT_TOKEN_PER_MINUTE` | `20` | Limit for the token endpoint |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Window size |
| `PASSWORD_RESET_TOKEN_MINUTES` | `15` | Reset token lifetime |
| `AUDIT_LOG_RETENTION_DAYS` | `90` | Audit retention |

---

## License

MIT — free for commercial and educational use. See [LICENSE](LICENSE).
