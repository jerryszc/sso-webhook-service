import redis.asyncio as redis

from app.core.config import settings


def get_redis() -> redis.Redis:
    # Cliente nuevo por llamada: evita reutilizar conexiones ligadas a un event loop
    # cerrado (pytest-asyncio crea un loop por test; el singleton fallaba en suite completa).
    return redis.from_url(settings.redis_url, decode_responses=True)
