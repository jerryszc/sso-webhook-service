import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import settings


def sign_payload(payload: dict[str, Any], secret: str) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def compute_backoff(attempt: int) -> timedelta:
    # attempt 1-based: 2s, 4s, 8s, 16s, 32s (base configurable)
    base = settings.webhook_backoff_base_seconds
    seconds = base * (2 ** (attempt - 1))
    return timedelta(seconds=seconds)


def next_retry_at(attempt: int) -> datetime:
    return datetime.now(UTC) + compute_backoff(attempt)
