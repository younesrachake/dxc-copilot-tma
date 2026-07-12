"""Baseline — full schema as of 2026-07 (models + telemetry tables).

This baseline is intentionally idempotent so it can be applied both to a fresh
database AND to an existing pre-alembic deployment (where the tables were
created by init_db()). Existing deployments end up stamped at this revision.
Future schema changes must be regular, explicit alembic revisions.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

# Columns historically added outside the SQLAlchemy models: (table, column, ddl)
_EXTRA_COLUMNS_SQLITE = [
    ("users", "failed_attempts",
     "ALTER TABLE users ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0"),
    ("users", "locked_until",
     "ALTER TABLE users ADD COLUMN locked_until DATETIME"),
    ("rag_analytics", "query_text",
     "ALTER TABLE rag_analytics ADD COLUMN query_text TEXT"),
    ("rag_analytics", "bot_message_id",
     "ALTER TABLE rag_analytics ADD COLUMN bot_message_id INTEGER"),
    ("rag_analytics", "grounded",
     "ALTER TABLE rag_analytics ADD COLUMN grounded INTEGER"),
    ("rag_analytics", "intent",
     "ALTER TABLE rag_analytics ADD COLUMN intent TEXT"),
]

_EXTRA_TABLES_SQLITE = [
    """
    CREATE TABLE IF NOT EXISTS rag_analytics (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        query_hash TEXT    NOT NULL,
        top_score  REAL    NOT NULL,
        routing    TEXT    NOT NULL,
        doc_ids    TEXT,
        latency_ms INTEGER,
        timestamp  DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_reports (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        report_type TEXT    NOT NULL,
        payload     TEXT    NOT NULL,
        created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
]

_EXTRA_SQL_POSTGRES = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_attempts INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ",
    """
    CREATE TABLE IF NOT EXISTS rag_analytics (
        id         SERIAL PRIMARY KEY,
        query_hash TEXT    NOT NULL,
        top_score  REAL    NOT NULL,
        routing    TEXT    NOT NULL,
        doc_ids    TEXT,
        latency_ms INTEGER,
        timestamp  TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    "ALTER TABLE rag_analytics ADD COLUMN IF NOT EXISTS query_text TEXT",
    "ALTER TABLE rag_analytics ADD COLUMN IF NOT EXISTS bot_message_id INTEGER",
    "ALTER TABLE rag_analytics ADD COLUMN IF NOT EXISTS grounded INTEGER",
    "ALTER TABLE rag_analytics ADD COLUMN IF NOT EXISTS intent TEXT",
    """
    CREATE TABLE IF NOT EXISTS agent_reports (
        id          SERIAL PRIMARY KEY,
        report_type TEXT    NOT NULL,
        payload     TEXT    NOT NULL,
        created_at  TIMESTAMPTZ DEFAULT NOW()
    )
    """,
]


def _sqlite_has_column(bind, table: str, column: str) -> bool:
    rows = bind.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(row[1] == column for row in rows)


def upgrade() -> None:
    bind = op.get_bind()

    # All SQLAlchemy model tables (checkfirst → no-op on existing deployments)
    from app.models.db import Base
    Base.metadata.create_all(bind=bind, checkfirst=True)

    if bind.dialect.name == "postgresql":
        for stmt in _EXTRA_SQL_POSTGRES:
            bind.execute(sa.text(stmt))
    else:
        for stmt in _EXTRA_TABLES_SQLITE:
            bind.execute(sa.text(stmt))
        # SQLite has no ADD COLUMN IF NOT EXISTS — probe via PRAGMA instead of
        # try/except, which would poison the migration transaction
        for table, column, ddl in _EXTRA_COLUMNS_SQLITE:
            if not _sqlite_has_column(bind, table, column):
                bind.execute(sa.text(ddl))


def downgrade() -> None:
    raise NotImplementedError("Baseline cannot be downgraded — restore from backup instead.")
