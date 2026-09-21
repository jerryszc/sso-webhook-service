from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class EndpointCreate(BaseModel):
    url: HttpUrl
    secret: str = Field(min_length=16, max_length=512)
    event_types: list[str] = Field(min_length=1)
    max_attempts: int = Field(default=5, ge=1, le=10)


class EndpointOut(BaseModel):
    id: str
    url: str
    event_types: list[str]
    is_active: bool
    max_attempts: int


class EventPublish(BaseModel):
    type: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="internal", max_length=64)


class EventOut(BaseModel):
    id: str
    type: str
    idempotency_key: str


class DeliveryOut(BaseModel):
    id: str
    event_id: str
    endpoint_id: str
    attempt: int
    status: str
    http_status: int | None = None
    error: str | None = None
