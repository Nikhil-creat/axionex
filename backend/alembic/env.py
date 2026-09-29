"""Async Alembic environment (asyncpg) targeting app metadata incl. PostGIS types."""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.database import Base
from app.models import models  # noqa: F401  (register tables)

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def _include_object(obj, name, type_, reflected, compare_to):
    return not (type_ == "table" and name in {"spatial_ref_sys"})


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, include_object=_include_object,
                      compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(settings.database_url, poolclass=pool.NullPool)
    async with engine.connect() as conn:
        await conn.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_online())
