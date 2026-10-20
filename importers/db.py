"""Raw psycopg connections for the importers.

The app talks to Postgres through SQLAlchemy; the importers need the psycopg
connection itself, because `COPY` is a libpq-level operation. Both read the
same `DATABASE_URL`, so there is still only one place to configure the database.
"""

from __future__ import annotations

import psycopg

from app.config import get_settings


def dsn() -> str:
    """`DATABASE_URL` as libpq wants it.

    SQLAlchemy URLs name the driver (`postgresql+psycopg://`); psycopg does not
    understand that prefix.
    """
    url = get_settings().database_url

    for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]

    return url


def connect() -> psycopg.Connection:
    """A non-autocommit connection. Importers commit once per batch."""
    return psycopg.connect(dsn())
