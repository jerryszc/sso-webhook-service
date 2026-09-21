import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel

from app.models.user import utcnow


class PasswordResetToken(SQLModel, table=True):
    __tablename__ = "password_reset_tokens"  # type: ignore[assignment]

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    token_hash: str = Field(max_length=512)
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    used: bool = Field(default=False)
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )