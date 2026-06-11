from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.config import DATABASE_URL

# Pool settings — SQLite uses StaticPool (no pool_size), PostgreSQL benefits from these settings
_is_sqlite = DATABASE_URL.startswith("sqlite")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    **({} if _is_sqlite else {
        "pool_size": 20,
        "max_overflow": 40,
        "pool_pre_ping": True,
        "pool_recycle": 3600,
    })
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with async_session() as session:
        yield session


async def init_db():
    from app.models.db import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # ── Schema migrations for columns added after initial deploy ──
        # SQLite ALTER TABLE only supports ADD COLUMN; safe to run on every start.
        _migrations = [
            "ALTER TABLE users ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN locked_until DATETIME",
            # RAG analytics table — tracks every retrieval event for observability
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
        ]
        import sqlalchemy
        for sql in _migrations:
            try:
                await conn.execute(sqlalchemy.text(sql))
            except Exception:
                pass  # column/table already exists — ignore
