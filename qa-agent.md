# 3. EXECUTION, QUALITY, AND SECURITY RULES
- **Async & DB Transactions (SQLModel/SQLAlchemy):** Strict use of `AsyncSession` with proper context managers, explicit `commit`/`rollback`, and prevention of lazy-loading issues in async context.
- **SQL Injection Prevention:** Strict parameterization; never concatenate raw variables into SQL queries.
- **Secret & Config Management:** Mandatory environment loading via `pydantic-settings`; zero hardcoded credentials or API keys.
- **Input Validation & Contracts:** Enforce rigorous Pydantic schema validation for all incoming requests and webhook payloads.
- **Defensive Error Handling:** Catch specific exceptions, map them to clean HTTP status codes (400, 401, 403, 404, 422, 500), and suppress raw stack traces.
- **Testing & Quality Assurance:** Every feature/endpoint must include unit and integration tests using `pytest` and `HTTPX`, ensuring mock isolation and high coverage.
- **Idempotency & Reliability:** Ensure webhook dispatchers and critical mutations implement idempotency keys and safe retry logic.
- **Minimal Changes & Verification:** Provide clean, production-ready code with explicit verification steps.