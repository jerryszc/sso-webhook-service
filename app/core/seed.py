"""Seed idempotente de service_clients M2M. Sin credenciales hardcodeadas."""

import os
import sys

from sqlmodel import select

from app.core.db import async_session_factory
from app.core.security import hash_password
from app.models.service_client import ServiceClient


async def main() -> None:
    client_id = os.getenv("SEED_CLIENT_ID", "").strip()
    secret = os.getenv("SEED_CLIENT_SECRET", "").strip()
    scopes = os.getenv("SEED_CLIENT_SCOPES", "webhooks:publish").strip()
    if not client_id or not secret:
        print("SEED_CLIENT_ID y SEED_CLIENT_SECRET son requeridos en el entorno", file=sys.stderr)
        raise SystemExit(2)
    async with async_session_factory() as session:
        existing = (
            await session.exec(select(ServiceClient).where(ServiceClient.client_id == client_id))
        ).first()
        if existing is not None:
            print(f"exists: {client_id}")
            return
        session.add(
            ServiceClient(
                client_id=client_id,
                client_secret_hash=hash_password(secret),
                scopes=scopes,
                is_active=True,
            )
        )
        await session.commit()
        print(f"created: {client_id} scopes={scopes}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
