"""
Maintenance Service — real database backup / optimization / cache cleanup.

Works against both dev SQLite (online .backup() copy, VACUUM) and production
PostgreSQL (pg_dump when the client is available, VACUUM ANALYZE). Backups are
written to BACKUP_DIR (default ./backups) with timestamped names and a simple
retention policy.
"""
import asyncio
import glob
import logging
import os
import sqlite3
from datetime import datetime, timezone

from sqlalchemy import text

from app.core.config import DATABASE_URL
from app.core.database import engine

logger = logging.getLogger(__name__)

BACKUP_DIR = os.path.abspath(os.getenv("BACKUP_DIR", "./backups"))
BACKUP_KEEP = int(os.getenv("BACKUP_KEEP", "14"))

_IS_SQLITE = DATABASE_URL.startswith("sqlite")


def _sqlite_path() -> str:
    # sqlite+aiosqlite:///./dxc_copilot.db → ./dxc_copilot.db
    return DATABASE_URL.split("///", 1)[-1]


def _rotate_backups() -> int:
    """Keep the newest BACKUP_KEEP files, delete the rest. Returns count removed."""
    files = sorted(glob.glob(os.path.join(BACKUP_DIR, "backup-*")), reverse=True)
    removed = 0
    for old in files[BACKUP_KEEP:]:
        try:
            os.remove(old)
            removed += 1
        except OSError:
            pass
    return removed


async def run_backup() -> dict:
    """Create a timestamped database backup. Returns {path, size_bytes}."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    if _IS_SQLITE:
        src = _sqlite_path()
        dest = os.path.join(BACKUP_DIR, f"backup-{stamp}.db")

        def _copy():
            # sqlite online backup API — safe while the app is writing
            with sqlite3.connect(src) as source, sqlite3.connect(dest) as target:
                source.backup(target)

        await asyncio.to_thread(_copy)
    else:
        dest = os.path.join(BACKUP_DIR, f"backup-{stamp}.sql.gz")
        # pg_dump reads connection params from the URL (strip the asyncpg driver)
        pg_url = DATABASE_URL.replace("+asyncpg", "")
        proc = await asyncio.create_subprocess_shell(
            f'pg_dump --no-owner --compress=6 --file="{dest}" "{pg_url}"',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode != 0:
            err = (stderr or b"").decode(errors="replace")[:300]
            if "not found" in err.lower() or proc.returncode == 127:
                raise RuntimeError(
                    "pg_dump introuvable dans ce conteneur — les sauvegardes PostgreSQL "
                    "sont gérées par le service 'backup' de docker-compose."
                )
            raise RuntimeError(f"pg_dump a échoué: {err}")

    size = os.path.getsize(dest)
    rotated = _rotate_backups()
    logger.info("Backup created: %s (%d bytes), %d old backup(s) rotated", dest, size, rotated)
    return {"path": dest, "size_bytes": size, "rotated": rotated}


async def optimize_database() -> dict:
    """VACUUM + ANALYZE (real). Requires autocommit — VACUUM can't run in a transaction."""
    started = datetime.now(timezone.utc)
    async with engine.connect() as conn:
        raw = await conn.execution_options(isolation_level="AUTOCOMMIT")
        if _IS_SQLITE:
            await raw.execute(text("VACUUM"))
            await raw.execute(text("ANALYZE"))
            statements = ["VACUUM", "ANALYZE"]
        else:
            await raw.execute(text("VACUUM ANALYZE"))
            statements = ["VACUUM ANALYZE"]
    duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    logger.info("Database optimized (%s) in %d ms", ", ".join(statements), duration_ms)
    return {"statements": statements, "duration_ms": duration_ms}


async def clean_caches() -> dict:
    """Clear the semantic answer cache and prune old telemetry rows."""
    from app.services.query_service import query_service

    cache_entries = len(query_service._cache)
    query_service.invalidate_cache()

    # Prune rag_analytics rows older than 90 days (telemetry, not business data)
    async with engine.connect() as conn:
        result = await conn.execute(text(
            "DELETE FROM rag_analytics WHERE timestamp < datetime('now', '-90 days')"
            if _IS_SQLITE else
            "DELETE FROM rag_analytics WHERE timestamp < NOW() - INTERVAL '90 days'"
        ))
        await conn.commit()
        pruned = result.rowcount if result.rowcount and result.rowcount > 0 else 0

    logger.info("Caches cleaned: %d semantic entries, %d telemetry rows pruned", cache_entries, pruned)
    return {"semantic_cache_entries": cache_entries, "telemetry_rows_pruned": pruned}
