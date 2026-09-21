import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel

from app.models.user import utcnow


class ServiceClient(SQLModel, table=True):
    __tablename__ = "service_clients"  # type: ignore[assignment]

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    client_id: str = Field(unique=True, index=True, max_length=128)
    client_secret_hash: str = Field(max_length=512)
    scopes: str = Field(default="", max_length=1024)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
