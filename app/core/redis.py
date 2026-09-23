from typing import Any

import redis.asyncio as redis

from app.core.config import settings


def get_redis() -> Any:
    # Cliente nuevo por llamada: evita reutilizar conexiones ligadas a un event loop
    # cerrado (pytest-asyncio crea un loop por test; el singleton fallaba en suite completa).
    # redis-py no provee stubs precisos para from_url (no-untyped-call), por lo que
    # el tipo de retorno es Any y los call sites aplican cast donde necesiten await.
    return redis.from_url(settings.redis_url, decode_responses=True)  # type: ignore[no-untyped-call]
