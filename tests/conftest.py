"""Test configuration for the SSO webhook service.

The only thing that needs configuring here is the event loop policy: on
Windows the default Proactor loop cannot run psycopg's async driver, so every
async test fails with "Psycopg cannot use the 'ProactorEventLoop' to run in
async mode". Linux already defaults to Selector, so this only changes
behaviour where it has to.

No seeding is needed: the suite creates its own users through
POST /auth/register and authenticates with them.
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _apply_migrations() -> None:
    """Bring the schema up to date with Alembic."""
    from alembic.config import Config

    from alembic import command

    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "alembic")
    command.upgrade(cfg, "head")


def pytest_configure() -> None:
    _apply_migrations()
