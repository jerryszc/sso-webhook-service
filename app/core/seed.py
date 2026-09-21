"""Seeds idempotentes (M2M + admin). Sin credenciales hardcodeadas: todo vía entorno."""

import os
import sys

from sqlmodel import select

from app.core.db import async_session_factory
from app.core.security import hash_password
from app.models.service_client import ServiceClient
from app.models.user import User


async def seed_client() -> None:
    client_id = os.getenv("SEED_CLIENT_ID", "").strip()
    secret = os.getenv("SEED_CLIENT_SECRET", "").strip()
    scopes = os.getenv("SEED_CLIENT_SCOPES", "webhooks:publish").strip()
    if not client_id or not secret:
        print("seed client: SKIP (SEED_CLIENT_ID/SEED_CLIENT_SECRET no definidos)")
        return
    async with async_session_factory() as session:
        existing = (
            await session.exec(select(ServiceClient).where(ServiceClient.client_id == client_id))
        ).first()
        if existing is not None:
            print(f"seed client: exists {client_id}")
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
        print(f"seed client: created {client_id} scopes={scopes}")


async def seed_admin() -> None:
    email = os.getenv("SEED_ADMIN_EMAIL", "").strip()
    password = os.getenv("SEED_ADMIN_PASSWORD", "").strip()
    if not email or not password:
        print("seed admin: SKIP (SEED_ADMIN_EMAIL/SEED_ADMIN_PASSWORD no definidos)")
        return
    if len(password) < 8:
        print("seed admin: ERROR password mínimo 8 caracteres", file=sys.stderr)
        raise SystemExit(2)
    async with async_session_factory() as session:
        existing = (await session.exec(select(User).where(User.email == email))).first()
        if existing is not None:
            if existing.role != "admin":
                existing.role = "admin"
                session.add(existing)
                await session.commit()
                print(f"seed admin: promoted {email}")
            else:
                print(f"seed admin: exists {email}")
            return
        session.add(User(email=email, password_hash=hash_password(password), role="admin", is_active=True))
        await session.commit()
        print(f"seed admin: created {email}")


async def main() -> None:
    await seed_client()
    await seed_admin()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
