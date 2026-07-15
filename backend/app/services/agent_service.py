"""
Knowledge Sync Agent — "Agent de synchronisation de la base de connaissances".

Automates what an admin does by hand:
  1. Turns the knowledge base on (platform_settings section "knowledge", key "enabled").
  2. Ingests published incident guides into the RAG knowledge base.
  3. Mirrors knowledge-base documents as published guides so they appear
     in the Documents section.

Runs on a schedule (default: weekly). Frequency is stored globally in the
platform_settings "agent" section and can be changed from the user settings page.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import IncidentGuide, PlatformSetting
from app.services.rag_service import rag_service

logger = logging.getLogger(__name__)

FREQUENCIES = {
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=30),
}
DEFAULT_FREQUENCY = "weekly"

KB_SOURCE_PREFIX = "guide-"       # manifest filename for guides ingested into the KB
GUIDE_SOURCE_PREFIX = "KB:"       # IncidentGuide.generated_from marker for mirrored KB docs


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize naive/aware datetimes to aware UTC for safe comparison."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return _as_utc(datetime.fromisoformat(value))
    except (ValueError, TypeError):
        return None


async def _get_setting(db: AsyncSession, section: str) -> Optional[PlatformSetting]:
    result = await db.execute(
        select(PlatformSetting).where(PlatformSetting.section == section)
    )
    return result.scalar_one_or_none()


async def _merge_setting(db: AsyncSession, section: str, values: dict) -> PlatformSetting:
    """Merge values into a settings section, creating the row if missing.

    Always assigns a fresh dict — in-place mutation of the JSON column is not
    change-tracked by SQLAlchemy.
    """
    row = await _get_setting(db, section)
    if row:
        row.data = {**(row.data or {}), **values}
    else:
        row = PlatformSetting(section=section, data=values)
        db.add(row)
    return row


async def kb_enabled(db: AsyncSession) -> bool:
    """Whether the knowledge base is enabled for chat retrieval (default: on)."""
    row = await _get_setting(db, "knowledge")
    if row is None:
        return True
    return bool((row.data or {}).get("enabled", True))


# ── RAG runtime configuration (platform_settings section "rag") ────
RAG_DEFAULTS = {
    "t_low": 0.35,             # below → skip KB context entirely
    "t_high": 0.75,            # above → KB treated as authoritative
    "reranker_enabled": True,
    "evaluator_enabled": False,
    "cache_enabled": True,
    "cache_threshold": 0.93,
    "cache_ttl_hours": 24,
    "expansion_enabled": False,
    "followups_enabled": True,
}


async def rag_settings(db: AsyncSession) -> dict:
    """Current RAG configuration, merged over defaults."""
    row = await _get_setting(db, "rag")
    return {**RAG_DEFAULTS, **((row.data or {}) if row else {})}


async def update_rag_settings(db: AsyncSession, values: dict) -> dict:
    """Persist a partial RAG configuration update. Caller commits."""
    allowed = {k: v for k, v in values.items() if k in RAG_DEFAULTS}
    await _merge_setting(db, "rag", allowed)
    return await rag_settings(db)


class KnowledgeSyncAgent:
    """Background agent that keeps the KB and the guide library in sync."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._running = False

    # ── Status / configuration ────────────────────────────────────

    async def get_status(self, db: AsyncSession) -> dict:
        agent_row = await _get_setting(db, "agent")
        data = (agent_row.data or {}) if agent_row else {}
        frequency = data.get("frequency")
        if frequency not in FREQUENCIES:
            frequency = DEFAULT_FREQUENCY
        return {
            "enabled": await kb_enabled(db),
            "frequency": frequency,
            "last_run": data.get("last_run"),
            "next_run": data.get("next_run"),
            "running": self._running,
            "last_result": data.get("last_result"),
        }

    async def set_frequency(self, db: AsyncSession, frequency: str) -> dict:
        if frequency not in FREQUENCIES:
            raise ValueError(
                f"Fréquence invalide : '{frequency}'. Valeurs acceptées : {', '.join(FREQUENCIES)}."
            )
        agent_row = await _get_setting(db, "agent")
        data = (agent_row.data or {}) if agent_row else {}
        last_run = _parse_iso(data.get("last_run"))
        next_run = (last_run + FREQUENCIES[frequency]).isoformat() if last_run else None
        await _merge_setting(db, "agent", {"frequency": frequency, "next_run": next_run})
        await db.commit()
        logger.info("Knowledge sync agent frequency set to '%s'", frequency)
        return await self.get_status(db)

    # ── Daily email digest ────────────────────────────────────────

    async def run_digest_if_due(self, db: AsyncSession) -> bool:
        """Send the daily admin digest (opt-in via notifications.digest_enabled)."""
        notif = await _get_setting(db, "notifications")
        if not notif or not (notif.data or {}).get("digest_enabled"):
            return False

        agent_row = await _get_setting(db, "agent")
        data = (agent_row.data or {}) if agent_row else {}
        last = _parse_iso(data.get("digest_last_run"))
        now = datetime.now(timezone.utc)
        if last is not None and last + timedelta(days=1) > now:
            return False

        try:
            html = await self._build_digest_html(db)
            from app.services.email_service import email_service
            from app.models.db import User
            admins = (await db.execute(
                select(User).where(User.role == "admin", User.status == "active")
            )).scalars().all()
            sent = 0
            for admin in admins:
                if await email_service.send_email(
                    str(admin.email), "DXC Copilot — Digest quotidien", html
                ):
                    sent += 1
            await _merge_setting(db, "agent", {"digest_last_run": now.isoformat()})
            await db.commit()
            logger.info("Daily digest sent to %d admin(s)", sent)
            return sent > 0
        except Exception as exc:
            logger.warning("Daily digest failed: %s", exc)
            return False

    @staticmethod
    async def _build_digest_html(db: AsyncSession) -> str:
        from sqlalchemy import text as sql_text
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")

        totals = (await db.execute(sql_text(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN routing = 'cache' THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN routing = 'groq_only' THEN 1 ELSE 0 END) "
            "FROM rag_analytics WHERE timestamp >= :c"
        ), {"c": yesterday})).first()
        total, cache_hits, kb_misses = (int(totals[0] or 0), int(totals[1] or 0), int(totals[2] or 0))

        intents = (await db.execute(sql_text(
            "SELECT COALESCE(intent, 'inconnu'), COUNT(*) FROM rag_analytics "
            "WHERE timestamp >= :c GROUP BY intent ORDER BY COUNT(*) DESC LIMIT 5"
        ), {"c": yesterday})).all()
        intent_rows = "".join(
            f"<tr><td style='padding:4px 12px'>{i}</td><td style='padding:4px 12px'><b>{n}</b></td></tr>"
            for i, n in intents
        ) or "<tr><td style='padding:4px 12px' colspan='2'>Aucune donnée</td></tr>"

        from app.services.clustering_service import latest_report
        gaps = await latest_report(db, "knowledge_gaps") or {}
        gap_rows = "".join(
            f"<li>{c.get('title', '?')} — {c.get('count', 0)} question(s)</li>"
            for c in (gaps.get("clusters") or [])[:3]
        ) or "<li>Aucune lacune détectée</li>"

        return f"""
        <div style="font-family: Arial, sans-serif; max-width: 620px; margin: 0 auto; color: #1a1a24;">
          <div style="background: #5F259F; color: #fff; padding: 18px 24px; border-radius: 10px 10px 0 0;">
            <h2 style="margin: 0;">DXC Copilot — Digest quotidien</h2>
            <span style="font-size: 12px; opacity: 0.85;">Dernières 24 heures</span>
          </div>
          <div style="border: 1px solid #e3e3ea; border-top: none; padding: 20px 24px; border-radius: 0 0 10px 10px;">
            <table style="width:100%; text-align:center; margin-bottom: 16px;">
              <tr>
                <td><div style="font-size:26px;font-weight:bold">{total}</div><div style="font-size:12px;color:#666">Requêtes</div></td>
                <td><div style="font-size:26px;font-weight:bold">{cache_hits}</div><div style="font-size:12px;color:#666">Cache sémantique</div></td>
                <td><div style="font-size:26px;font-weight:bold">{kb_misses}</div><div style="font-size:12px;color:#666">Hors KB</div></td>
              </tr>
            </table>
            <h3 style="font-size:14px;">Intents les plus fréquents</h3>
            <table style="font-size:13px; border-collapse: collapse;">{intent_rows}</table>
            <h3 style="font-size:14px; margin-top:16px;">Lacunes de la base de connaissances</h3>
            <ul style="font-size:13px;">{gap_rows}</ul>
            <p style="font-size:11px;color:#999;margin-top:20px;">
              Digest automatique — désactivable dans Administration → Paramètres → Notifications.
            </p>
          </div>
        </div>
        """

    # ── Scheduling ────────────────────────────────────────────────

    async def run_if_due(self, db: AsyncSession) -> bool:
        """Run the sync if the configured interval has elapsed. Returns True if it ran."""
        agent_row = await _get_setting(db, "agent")
        data = (agent_row.data or {}) if agent_row else {}
        frequency = data.get("frequency")
        if frequency not in FREQUENCIES:
            frequency = DEFAULT_FREQUENCY
        last_run = _parse_iso(data.get("last_run"))
        now = datetime.now(timezone.utc)
        if last_run is not None and last_run + FREQUENCIES[frequency] > now:
            return False
        await self.run_sync(db)
        return True

    # ── Sync logic ────────────────────────────────────────────────

    async def run_sync(self, db: AsyncSession) -> dict:
        """Enable the KB, ingest published guides, mirror KB docs as guides."""
        async with self._lock:
            self._running = True
            try:
                return await self._do_sync(db)
            finally:
                self._running = False

    async def _do_sync(self, db: AsyncSession) -> dict:
        logger.info("Knowledge sync agent: run started")

        # 1. Ensure the knowledge base is enabled
        await _merge_setting(db, "knowledge", {"enabled": True})

        manifest = {d["filename"]: d for d in rag_service.get_documents()}

        # 2. Ingest published guides into the KB (skip KB-mirrored guides — their
        #    content is already in the KB as the original uploaded document)
        guides = (await db.execute(
            select(IncidentGuide).where(IncidentGuide.is_draft == False)  # noqa: E712
        )).scalars().all()

        guides_ingested = 0
        for g in guides:
            if str(g.generated_from or "").startswith(GUIDE_SOURCE_PREFIX):
                continue
            source = f"{KB_SOURCE_PREFIX}{g.id}"
            entry = manifest.get(source)
            if entry:
                ingested_at = _parse_iso(entry.get("uploaded_at"))
                updated_at = _as_utc(g.updated_at)
                if ingested_at and updated_at and updated_at <= ingested_at:
                    continue  # already up to date
            text = self._guide_to_text(g)
            try:
                chunks = await rag_service.ingest_text(text, source=source, topic="incident-guide")
                if chunks > 0:
                    guides_ingested += 1
            except Exception as exc:
                logger.warning("Agent: failed to ingest guide #%s: %s", g.id, exc)

        # 3. Mirror KB documents as published guides in the Documents section
        docs_mirrored = 0
        for entry in rag_service.get_documents():
            filename = entry.get("filename", "")
            if entry.get("topic") == "incident-guide" or filename.startswith(KB_SOURCE_PREFIX):
                continue
            marker = f"{GUIDE_SOURCE_PREFIX}{entry['id']}"
            existing = (await db.execute(
                select(IncidentGuide).where(IncidentGuide.generated_from == marker)
            )).scalars().first()
            if existing:
                continue
            db.add(IncidentGuide(
                title=filename,
                description=f"Document de la base de connaissances ({entry.get('chunks', 0)} section(s) indexée(s)).",
                category="Documentation",
                severity="P3",
                status="Résolu",
                tags=["kb-sync"],
                generated_from=marker,
                is_draft=False,
            ))
            docs_mirrored += 1

        # 4. Data-driven insight reports (best effort — never blocks the sync)
        gap_clusters = None
        threshold_status = None
        try:
            from app.services.clustering_service import (
                analyze_knowledge_gaps, recommend_thresholds
            )
            cfg = await rag_settings(db)
            gaps = await analyze_knowledge_gaps(db, t_low=cfg["t_low"])
            gap_clusters = len(gaps.get("clusters", []))
            thresholds = await recommend_thresholds(db)
            threshold_status = thresholds.get("status")
        except Exception as exc:
            logger.warning("Agent: insight analysis failed: %s", exc)

        # 5. Persist run metadata
        agent_row = await _get_setting(db, "agent")
        data = (agent_row.data or {}) if agent_row else {}
        frequency = data.get("frequency")
        if frequency not in FREQUENCIES:
            frequency = DEFAULT_FREQUENCY
        now = datetime.now(timezone.utc)
        result = {"guides_ingested": guides_ingested, "docs_mirrored": docs_mirrored}
        if gap_clusters is not None:
            result["knowledge_gap_clusters"] = gap_clusters
        if threshold_status is not None:
            result["threshold_recommendation"] = threshold_status
        await _merge_setting(db, "agent", {
            "frequency": frequency,
            "last_run": now.isoformat(),
            "next_run": (now + FREQUENCIES[frequency]).isoformat(),
            "last_result": result,
        })
        await db.commit()

        logger.info(
            "Knowledge sync agent: run finished — %d guide(s) ingested, %d document(s) mirrored",
            guides_ingested, docs_mirrored
        )
        return result

    @staticmethod
    def _guide_to_text(g: IncidentGuide) -> str:
        parts = [
            str(g.title or ""),
            str(g.description or ""),
            f"Catégorie: {g.category} | Sévérité: {g.severity} | Statut: {g.status}",
        ]
        if g.tags:
            parts.append("Tags: " + ", ".join(str(t) for t in g.tags))
        if g.specs:
            try:
                parts.append(json.dumps(g.specs, ensure_ascii=False))
            except (TypeError, ValueError):
                pass
        return "\n".join(p for p in parts if p)


# Singleton
knowledge_sync_agent = KnowledgeSyncAgent()
