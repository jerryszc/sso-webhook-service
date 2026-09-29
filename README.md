# SSO Auth Service & Webhook Dispatcher

**[English version ÔåÆ](README.en.md)**

Servicio de identidad con OAuth2, rotaci├│n de tokens y lista negra en Redis, m├ís un
dispatcher de webhooks firmado con HMAC, reintentos con backoff exponencial, cola de
muertos (DLQ) e idempotencia obligatoria.

[![CI](https://github.com/jerryszc/sso-webhook-service/actions/workflows/ci.yml/badge.svg)](https://github.com/jerryszc/sso-webhook-service/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688.svg)](https://fastapi.tiangolo.com/)
[![Tests](https://img.shields.io/badge/tests-16%20passing%20%7C%20real%20PG%20%2B%20Redis-brightgreen.svg)](tests)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED.svg)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Stack:** Python 3.12 ┬À FastAPI (async) ┬À SQLAlchemy async ┬À psycopg 3 ┬À PostgreSQL 16 ┬À Redis 7 ┬À Argon2id ┬À PyJWT (HS256) ┬À Alembic ┬À Pytest ┬À httpx ┬À Docker

---

## El problema empresarial

Este servicio resuelve dos problemas que aparecen juntos en cualquier plataforma que
integra terceros, y que se pagan caros cuando se ignoran.

### 1. La integraci├│n se rompe cuando el receptor no est├í disponible

Un sistema que notifica a un socio (un marketplace, una pasarela de pago, un sistema
log├¡stico) descubre que **HTTP no garantiza entrega**. El receptor puede estar ca├¡do,
puede devolver un 500, o la red puede cortarse en medio de la petici├│n. Un dise├▒o ingenuo
produce dos fallos opuestos y ambos son caros:

| Comportamiento ingenuo | Consecuencia |
| :--- | :--- |
| Si la entrega falla, se descarta el evento | El socio nunca se entera. Un pago que s├¡ se cobr├│ no genera la orden de env├¡o. El cliente pag├│ y nadie lo sabe. |
| Si la entrega falla, se reintenta en bucle infinito | El receptor ca├¡do recibe millones de peticiones. La ca├¡da se extiende, se agotan los recursos de ambos lados y el evento original sigue sin entregarse. |

**Lo que hace este servicio**

| Mecanismo | C├│mo resuelve el problema |
| :--- | :--- |
| **Reintentos con backoff exponencial** | 5 intentos con esperas de 2s, 4s, 8s, 16s y 32s. Da tiempo a que un receptor con un problema moment├íneo se recupere, sin martillearlo |
| **Cola de muertos (DLQ)** | Agotados los 5 intentos, la entrega pasa a `status = "dlq"` en lugar de desaparecer. Un evento nunca se pierde en silencio y queda consultable por API |
| **Reintento manual** | `POST /webhooks/deliveries/{id}/retry` saca una entrega de la DLQ. Un operador resuelve la causa ra├¡z y reactiva el evento sin reprocesar nada |
| **Clave de idempotencia obligatoria** | `Idempotency-Key` es obligatoria al publicar. Si el cliente reenv├¡a el mismo evento, el servicio lo detecta y no lo despacha dos veces, as├¡ que el receptor nunca procesa dos veces un cobro |
| **Firma HMAC-SHA256** | Cada entrega lleva la firma del payload. El receptor verifica que el mensaje sea aut├®ntico y no fue alterado en tr├ínsito, y no conf├¡a solo en el canal HTTPS |

La cadena de idempotencia es lo que cierra el problema. Sin ella, un reintento tras un
tiempo de espera agotado produce un **doble cobro** en el receptor: la petici├│n original s├¡
lleg├│, solo que la respuesta se perdi├│. Con la clave, el segundo intento es reconocido y
descartado.

### 2. La autenticaci├│n se replica y se degrada

Cada integraci├│n que construye su propio login duplica credenciales, multiplica la
superficie de ataque y produce inconsistencias: una usa bcrypt, otra SHA-256, una tercera
no expira las sesiones. Cuando una de ellas filtra, el da├▒o no queda contenido.

| Problema | C├│mo lo resuelve el servicio |
| :--- | :--- |
| Credenciales duplicadas por integraci├│n | Un solo punto de emisi├│n de tokens. Los servicios se autentican contra esta fuente, no contra la base de datos de usuarios |
| Contrase├▒as con algoritmo d├®bil o sin sal | **Argon2id** v├¡a `argon2-cffi`, el ganador de la Password Hashing Competition. Verificado en `test_password_hash_roundtrip` |
| Robos de sesi├│n v├¡a refresh token | **Rotaci├│n** en cada uso: el refresh emite un token nuevo y el anterior queda invalido. Si un atacante reutiliza uno robado, la rotaci├│n lo delata |
| Imposible revocar una sesi├│n concreta | **Lista negra en Redis** por `jti` con TTL. El logout invalida ese token concreto y luego expira solo |
| Fuerza bruta contra login | Rate limiting por IP y por ├ímbito: 10 req/min en register, login y password reset; 20 req/min en el endpoint de token |
| "┬┐Qui├®n accedi├│ a qu├® y desde d├│nde?" | Tabla `audit_log` con retenci├│n configurable (90 d├¡as por defecto), con **tests dedicados** a los tres eventos cr├¡ticos |

---

## Contexto de uso: dos servicios que siempre viajan juntos

Este repositorio combina autenticación y despacho de webhooks porque aparecen juntos en el
mismo tipo de empresa: una plataforma que tiene **usuarios propios** y además **notifica a
sistemas de terceros**. Quien crece rápido llega a esa situación por duplicación, con un login
por servicio y un script suelto por integración. Este es el caso para el que está diseñado.

**Dónde encaja dentro de una organización real**

| Contexto | Cómo se usa | Por qué este diseño |
| :--- | :--- | :--- |
| **SSO interno de una empresa con varios servicios** | Todos los servicios validan el mismo token en lugar de implementar su propio login | Un solo punto de entrada y de revocación. Cerrar sesión en un sitio cierra en todos, y el `audit_log` responde quién accedió a qué |
| **Notificación de eventos hacia socios externos** | El sistema publica cambios hacia un marketplace, una pasarela de pago o un transportista | El backoff exponencial y la DLQ evitan que un receptor caído se martillee y que un evento se pierda en silencio |
| **Plataforma B2B multi-tenant** | Cada cliente tiene sus propias credenciales de máquina (`client_credentials`) | El flujo `client_credentials` permite a un backend llamar a la API sin que exista un usuario humano detrás |
| **Sistema que debe responder "¿quién hizo esto?"** | El `audit_log` retiene 90 días por defecto, configurable | Sirve para revisión interna y para responder a una auditoría sin instrumentar cada endpoint a mano |

**Por qué un mismo servicio y no dos**

Es una decisión discutible, y conviene poder justificarla:

- **A favor de juntos:** la identidad y los webhooks comparten necesidad de *auditoría, firma
  criptográfica y trazabilidad de eventos*. La tabla `audit_log` sirve a ambos, y el HMAC que
  protege un webhook saliente es la misma disciplina que la que protege un token.
- **A favor de separados:** acopla dos dominios que evolucionan a ritmos distintos, y obliga
  a desplegar juntos dos servicios que no tienen por qué fallar juntos. En una organización
  más grande, esta separación sería lo razonable.

Está unido porque así es más fácil mostrar el criterio: el mismo principio aplicado a las dos
mitades.

**Qué aporta frente a "un login y un `requests.post()`"**

- **La entrega no se pierde ni se duplica.** La clave de idempotencia obligatoria y el DLQ
  cubren los dos fallos caros: perder una orden de envío porque el transportista estaba caído,
  o cobrar dos veces porque el cliente reenvió por no recibir respuesta.
- **El atacante que roba un refresh token se delata solo.** Cada uso emite un token nuevo y
  marca el anterior como rotado. Si alguien reutiliza el viejo, la rotación lo hace visible.
- **La sesión se puede revocar de verdad.** La lista negra en Redis por `jti` invalida una
  sesión concreta sin esperar a que expire, con su TTL alineado a la duración del token.
- **La fuerza bruta tiene freno.** 10 req/min en registro, login y reset de contraseña; 20 en
  el endpoint de token. Los límites son por ámbito e IP, no un único valor global.

**Qué tendría que añadirse antes de ponerlo en producción**

- **El rate limiter es *fail-open* a propósito.** Si Redis no responde, el límite no se
  aplica: el sistema prefiere estar disponible antes que protegido. Es una decisión
  consciente, y su coste es que una caída de Redis elimina la defensa contra fuerza bruta.
  Compensar con un límite en el balanceador o en la CDN.
- **El secreto de firma es compartido.** HMAC exige que emisor y receptor compartan la misma
  clave. Con varios receptores, cada uno necesita la suya y hay que decidir rotación y
  revocación. Hoy hay un solo secreto.
- **Separar los dos servicios** en cuanto el tráfico de uno crezca de forma independiente, o
  cuando la identidad deba servir a organizaciones que no usan el dispatcher.
- **Clave por receptor y rotación planificada**, en lugar de un secreto global.
- **Alertas sobre la DLQ.** La cola existe y es consultable por API, pero sin monitoring un
  evento puede quedarse semanas en `status = "dlq"` sin que nadie lo note.

**A qué puesto corresponde este trabajo**

Backend Developer en identidad, pasarelas de pago o plataformas de integración. Es el trabajo
de la frontera de confianza: decidir qué se verifica, dónde, y qué error se devuelve sin
revelar si un usuario existe.

---

## Impacto verificable

**16 tests** en 3 m├│dulos. La CI los ejecuta contra **PostgreSQL 16 y Redis 7 reales**
(contenedores de servicio, no SQLite ni mocks), porque el comportamiento de rotaci├│n de
tokens, blacklist y rate limiting depende de Redis de verdad.

| Comportamiento | Test que lo demuestra |
| :--- | :--- |
| El ciclo completo registrar ÔåÆ login ÔåÆ me ÔåÆ refresh ÔåÆ logout funciona | `test_register_login_me_refresh_logout` |
| El flujo `client_credentials` (machine-to-machine) emite tokens | `test_client_credentials_flow` |
| Publicar dos veces el mismo evento con la misma clave no despacha dos veces | `test_webhook_publish_idempotent` |
| El crecimiento del backoff es exponencial, no lineal | `test_backoff_growth` |
| La firma HMAC es verificable y cambia si el payload cambia | `test_hmac_signature` |
| El hash de contrase├▒a hace round-trip y no guarda el texto plano | `test_password_hash_roundtrip` |
| El rate limiting bloquea al superar el l├¡mite | `test_rate_limit_blocks` |
| El rate limiting respeta el ├ímbito: login y register no comparten contador | `test_rate_limit_blocks` |
| Un login fallido queda registrado en la auditor├¡a | `test_audit_logs_on_login_failed` |
| La emisi├│n de un token machine-to-machine queda auditada | `test_audit_logs_on_m2m_token` |
| La creaci├│n de un endpoint de webhook queda auditada | `test_audit_logs_on_webhook_created` |
| El flujo de reset de contrase├▒a funciona de punta a punta | `test_password_reset_flow` |
| Un email inexistente en el reset no filtra si la cuenta existe | `test_password_reset_nonexistent_email` |
| El seed del admin es idempotente | `test_seed_admin_idempotent` |
| `/ready` distingue "vivo" de "puede recibir tr├ífico" | `test_ready_ok` |

---

## Arquitectura

```
app/
Ôö£ÔöÇÔöÇ main.py                     # Routers, prefijo /api/v1, lifecycle
Ôö£ÔöÇÔöÇ api/
Ôöé   Ôö£ÔöÇÔöÇ auth.py                 # register, login, token, refresh, logout,
Ôöé   Ôöé                           # password/reset, password/reset/confirm, me
Ôöé   Ôö£ÔöÇÔöÇ webhooks.py             # endpoints, events, deliveries, retry
Ôöé   ÔööÔöÇÔöÇ health.py               # /health y /ready (sin prefijo)
Ôö£ÔöÇÔöÇ core/
Ôöé   Ôö£ÔöÇÔöÇ config.py               # Pydantic Settings
Ôöé   Ôö£ÔöÇÔöÇ db.py                   # Motor async + sesi├│n por request
Ôöé   Ôö£ÔöÇÔöÇ redis.py                # Cliente Redis (TTL, listas negras)
Ôöé   Ôö£ÔöÇÔöÇ security.py             # Argon2id + JWT (HS256) con jti
Ôöé   Ôö£ÔöÇÔöÇ ratelimit.py            # Fixed-window sobre Redis
Ôöé   Ôö£ÔöÇÔöÇ deps.py                 # Dependencias de autenticaci├│n
Ôöé   ÔööÔöÇÔöÇ seed.py                 # Admin inicial, idempotente
Ôö£ÔöÇÔöÇ models/                     # User, RefreshToken, ServiceClient,
Ôöé                               # PasswordResetToken, WebhookEndpoint,
Ôöé                               # WebhookEvent, WebhookDelivery, AuditLog
Ôö£ÔöÇÔöÇ schemas/                    # Contratos de request/response
Ôö£ÔöÇÔöÇ services/
Ôöé   Ôö£ÔöÇÔöÇ auth_service.py         # Emisi├│n, rotaci├│n, revocaci├│n, auditor├¡a
Ôöé   Ôö£ÔöÇÔöÇ webhook_service.py      # Registro de endpoints y publicaci├│n
Ôöé   Ôö£ÔöÇÔöÇ dispatcher.py           # Firma HMAC y c├ílculo de backoff
Ôöé   ÔööÔöÇÔöÇ audit_service.py        # Escritura de auditor├¡a
ÔööÔöÇÔöÇ workers/
    ÔööÔöÇÔöÇ dispatch_worker.py      # Env├¡o HTTP, reintentos, DLQ
```

**El c├ílculo del backoff** (`app/services/dispatcher.py`) es la pieza m├ís simple y la m├ís
importante del dispatcher:

```python
def compute_backoff(attempt: int) -> timedelta:
    # attempt 1-based: 2s, 4s, 8s, 16s, 32s (base configurable)
    base = settings.webhook_backoff_base_seconds
    return timedelta(seconds=base * (2 ** (attempt - 1)))
```

Y la firma usa **JSON can├│nico** ÔÇö claves ordenadas y sin espacios ÔÇö para que la misma
l├│gica produzca siempre el mismo HMAC, independientemente de c├│mo el receptor reconstruya
el payload:

```python
def sign_payload(payload: dict[str, Any], secret: str) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
```

---

## Modelo de datos

**8 tablas.**

| Tabla | Funci├│n | Campos clave |
| :--- | :--- | :--- |
| `user` | Usuarios humanos | email, `password_hash` (Argon2id), `is_active` |
| `service_client` | Servicios machine-to-machine | `client_id`, `client_secret` (hash), `scopes` |
| `refresh_token` | Refresh tokens emitidos | `jti` (├║nico), `user_id`, `service_client_id`, `expires_at`, `rotated_from_jti` |
| `password_reset_token` | Tokens de reset de un solo uso | `expires_at`, `used` |
| `webhook_endpoint` | Destinos de notificaci├│n | `url`, `secret` (para el HMAC), `max_attempts` (anula el global) |
| `webhook_event` | Eventos publicados | `type`, `payload`, `idempotency_key` (├║nico), `source` |
| `webhook_delivery` | Un evento contra un endpoint | `attempt`, `status` (`success`/`dlq`/...), `http_status`, `error`, `next_retry_at` |
| `audit_log` | Traza de seguridad | actor, acci├│n, resultado, timestamp; retenci├│n 90 d├¡as |

**La rotaci├│n deja rastro:** `rotated_from_jti` encadena cada refresh con su predecesor. Un
refresh reutilizado es detectable porque su `jti` ya fue rotado y no coincide con la
cadena vigente.

---

## API

Prefijo `/api/v1` en auth y webhooks. Las rutas de salud van **sin prefijo** a prop├│sito:
un balanceador no deber├¡a tener que conocer el versionado de la API.

### Autenticaci├│n
| M├®todo | Ruta | Descripci├│n | Rate limit |
| :--- | :--- | :--- | :--- |
| POST | `/api/v1/auth/register` | Crear cuenta (201) | 10/min por IP |
| POST | `/api/v1/auth/login` | Login, devuelve access + refresh | 10/min por IP |
| POST | `/api/v1/auth/token` | `client_credentials` (M2M) | 20/min por IP |
| POST | `/api/v1/auth/refresh` | Rota el refresh token | ÔÇö |
| POST | `/api/v1/auth/logout` | Revoca y pone en lista negra (204) | ÔÇö |
| POST | `/api/v1/auth/password/reset` | Solicitar reset | 10/min por IP |
| POST | `/api/v1/auth/password/reset/confirm` | Confirmar reset | 10/min por IP |
| GET | `/api/v1/auth/me` | Usuario autenticado | ÔÇö |

### Webhooks
| M├®todo | Ruta | Descripci├│n |
| :--- | :--- | :--- |
| POST | `/api/v1/webhooks/endpoints` | Registrar destino (201) |
| GET | `/api/v1/webhooks/endpoints` | Listar destinos |
| POST | `/api/v1/webhooks/events` | Publicar evento. **Requiere `Idempotency-Key`** |
| GET | `/api/v1/webhooks/deliveries` | Consultar entregas y su estado |
| POST | `/api/v1/webhooks/deliveries/{id}/retry` | Reintentar una entrega de la DLQ |

### Salud
| M├®todo | Ruta | Descripci├│n |
| :--- | :--- | :--- |
| GET | `/health` | El proceso est├í vivo |
| GET | `/ready` | La base de datos responde: puede recibir tr├ífico |

La separaci├│n entre `/health` y `/ready` es deliberada: durante un despliegue, reiniciar
la instancia cuando Redis ya no responde solo genera m├ís tr├ífico fallido, no menos.

### Idempotencia en la publicaci├│n

```bash
curl -X POST http://localhost:8000/api/v1/webhooks/events \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: order-paid-8841" \
  -H "Content-Type: application/json" \
  -d '{"type":"order.paid","payload":{"order_id":8841,"amount":129.90},"source":"checkout"}'
```

Sin la cabecera, la respuesta es **422** con `"Idempotency-Key required"`. Con ella, repetir
la misma llamada no crea un segundo evento: es exactamente el escenario donde un reintento
del cliente causar├¡a un cobro doble en el receptor.

---

## Seguridad

**Contrase├▒as:** Argon2id (`argon2-cffi`), el algoritmo ganador de la Password Hashing
Competition, resistente tanto a ataques con GPU como a memoria masiva.

**Tokens de acceso:** 15 minutos, JWT HS256, con `jti` ├║nico por token.

**Refresh tokens:** 7 d├¡as, con rotaci├│n en cada uso y `rotated_from_jti` que registra la
cadena.

**Revocaci├│n:** lista negra en Redis con clave `blacklist:refresh:{jti}` y TTL igual a la
vida restante del token, as├¡ que la lista se autolimpia y no crece sin control.

**Rate limiting:** fixed-window sobre Redis, por IP real ÔÇö se lee `X-Forwarded-For` para
detectar la IP del cliente detr├ís de un proxy. ├ümbitos separados por endpoint.

> **Tradeoff documentado: el rate limiting es *fail-open*.** Si Redis no responde, la
> funci├│n captura la excepci├│n y permite la petici├│n en lugar de rechazarla. La elecci├│n es
> deliberada ÔÇö un Redis ca├¡do no debe dejar inaccesible toda la autenticaci├│n de la
> plataforma ÔÇö pero tiene un coste expl├¡cito: **si Redis cae, la defensa contra fuerza
> bruta desaparece** y hay que compensarlo con WAF o rate limiting en el borde. Es una
> decisi├│n consciente, no un descuido, y por eso est├í escrita aqu├¡.

**Firma de webhooks:** HMAC-SHA256 sobre JSON can├│nico, en la cabecera `X-Signature`
(nombre configurable con `WEBHOOK_HMAC_HEADER`). Cada entrega incluye tambi├®n
`X-Event-Type` e `X-Idempotency-Key`.

**Variable sensible:** `jwt_secret` tiene el valor por defecto `change-me-in-env` y **debe**
cambiarse antes de desplegar.

---

## Pruebas

**16 tests** en 3 m├│dulos.

| M├│dulo | Tests | Cubre |
| :--- | :--- | :--- |
| `test_integration.py` | 8 | Ciclo completo de autenticaci├│n, `client_credentials`, idempotencia de webhooks, flujo de reset de contrase├▒a, email inexistente, y tres tests dedicados a la auditor├¡a |
| `test_baseline.py` | 5 | Health, validaci├│n de registro, round-trip de Argon2id, firma HMAC, crecimiento del backoff |
| `test_hardening.py` | 3 | `/ready`, rate limiting, idempotencia del seed |

```bash
# Requiere PostgreSQL y Redis levantados
docker compose up -d db redis
docker compose exec api alembic upgrade head

pytest -q
pytest --cov=app --cov-report=term-missing
```

---

## Integraci├│n continua

La CI de este repositorio es la m├ís exigente de los cuatro proyectos, porque los tests
dependen de infraestructura real.

| Job | Qu├® hace |
| :--- | :--- |
| **Lint** | `ruff check .` y `ruff format --check .` |
| **Typecheck** | `mypy app` en modo estricto |
| **Tests** | Pytest contra **contenedores de servicio PostgreSQL 16 y Redis 7** |
| **Docker Build & Smoke Test** | Construye la imagen y verifica el arranque con compose |
| **Notify on Failure** | Aggregator con `needs` sobre los cuatro anteriores |

**Detalles que hacen que la CI sea fiable y no decorativa:**

- **Los tests corren contra la base de datos real.** SQLite o mocks pasar├¡an los tests
  aunque la rotaci├│n de tokens o el rate limiting estuvieran rotos, porque el
  comportamiento depende de Redis y de PostgreSQL de verdad.
- **Espera activa en Python puro.** El runner no trae `pg_isready` ni `redis-cli`, as├¡ que
  el workflow espera con un bucle que abre sockets TCP contra ambos puertos en lugar de
  asumir que un `sleep` basta.
- **Las migraciones se ejecutan antes de los tests**, con las mismas variables de entorno
  que usar├ín los tests, de modo que el esquema siempre corresponde al c├│digo bajo prueba.
- **Se sube el reporte de cobertura** como artefacto.

---

## Puesta en marcha

**Requisitos:** Docker Desktop en ejecuci├│n.

```bash
# 1. Clonar y entrar
git clone https://github.com/jerryszc/sso-webhook-service.git
cd sso-webhook-service

# 2. Configurar
cp .env.example .env
#   Antes de nada: cambia JWT_SECRET

# 3. Levantar API + PostgreSQL 16 + Redis 7
docker compose up --build -d

# 4. Verificar
curl http://localhost:8000/health
curl http://localhost:8000/ready

# 5. Documentaci├│n
#    http://localhost:8000/docs
```

```bash
# Detener
docker compose down
docker compose down -v
```

### Desarrollo local sin Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

### Migraciones

```bash
alembic revision --autogenerate -m "descripcion"
alembic upgrade head
alembic current
```

---

## Variables de entorno

| Variable | Por defecto | Descripci├│n |
| :--- | :--- | :--- |
| `APP_ENV` | `dev` | Entorno de ejecuci├│n |
| `API_V1_PREFIX` | `/api/v1` | Prefijo de las rutas versionadas |
| `DATABASE_URL` | `postgresql+psycopg://sso:sso@localhost:5432/sso` | Conexi├│n async |
| `SYNC_DATABASE_URL` | `postgresql+psycopg://sso:sso@localhost:5432/sso` | Conexi├│n s├¡ncrona (Alembic) |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis para blacklist y rate limiting |
| `JWT_SECRET` | `change-me-in-env` | **Cambiar en producci├│n** |
| `JWT_ALG` | `HS256` | Algoritmo de firma |
| `ACCESS_TOKEN_MINUTES` | `15` | Vigencia del access token |
| `REFRESH_TOKEN_DAYS` | `7` | Vigencia del refresh token |
| `WEBHOOK_TIMEOUT_SECONDS` | `10` | Timeout de cada entrega |
| `WEBHOOK_MAX_ATTEMPTS` | `5` | Intentos antes de ir a la DLQ |
| `WEBHOOK_BACKOFF_BASE_SECONDS` | `2` | Base del backoff (2, 4, 8, 16, 32) |
| `WEBHOOK_HMAC_HEADER` | `X-Signature` | Nombre de la cabecera de firma |
| `RATE_LIMIT_AUTH_PER_MINUTE` | `10` | L├¡mite de register, login y reset |
| `RATE_LIMIT_TOKEN_PER_MINUTE` | `20` | L├¡mite del endpoint de token |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Tama├▒o de la ventana |
| `PASSWORD_RESET_TOKEN_MINUTES` | `15` | Vigencia del token de reset |
| `AUDIT_LOG_RETENTION_DAYS` | `90` | Retenci├│n de la auditor├¡a |

---

## Licencia

MIT ÔÇö uso libre comercial y educativo. Ver [LICENSE](LICENSE).
