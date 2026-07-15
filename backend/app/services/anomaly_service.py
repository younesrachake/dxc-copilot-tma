"""
Anomaly Service — statistical spike detection on chat telemetry + webhook alerts.

Hourly (from the agent scheduler loop): compares the last hour's message volume
and KB-miss (groq_only) rate against the trailing 7-day baseline from
rag_analytics. A z-score > 3 raises an anomaly: persisted to agent_reports and
POSTed to the Teams/Slack webhook configured in platform_settings
["notifications"]["webhookUrl"] (the same one admin "test webhook" uses).
Cooldown: at most one alert per anomaly type every 6 hours.
"""
import json
import logging
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

Z_THRESHOLD = 3.0
COOLDOWN_HOURS = 6
MIN_BASELINE_HOURS = 24   # need at least a day of history before judging


def zscore(value: float, baseline: list[float]) -> float:
    """Z-score of value against a baseline sample (0.0 when undecidable)."""
    if len(baseline) < 2:
        return 0.0
    mean = sum(baseline) / len(baseline)
    var = sum((x - mean) ** 2 for x in baseline) / (len(baseline) - 1)
    std = math.sqrt(var)
    if std < 1e-9:
        # Flat baseline: any activity where there was strictly none is a spike
        return float("inf") if value > mean else 0.0
    return (value - mean) / std


async def _hourly_counts(db: AsyncSession, hours: int) -> list[dict]:
    """Per-hour message volume + groq_only count for the trailing window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:00:00")
    is_sqlite = db.get_bind().dialect.name == "sqlite"
    bucket_expr = (
        "strftime('%Y-%m-%d %H', timestamp)" if is_sqlite
        else "to_char(timestamp, 'YYYY-MM-DD HH24')"
    )
    rows = (await db.execute(text(
        f"SELECT {bucket_expr} AS bucket, "
        "COUNT(*) AS total, "
        "SUM(CASE WHEN routing = 'groq_only' THEN 1 ELSE 0 END) AS misses "
        "FROM rag_analytics WHERE timestamp >= :cutoff AND routing != 'cache' "
        "GROUP BY bucket ORDER BY bucket"
    ), {"cutoff": cutoff})).all()
    return [{"bucket": r[0], "total": int(r[1] or 0), "misses": int(r[2] or 0)} for r in rows]


async def _recent_alert_exists(db: AsyncSession, kind: str) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=COOLDOWN_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    row = (await db.execute(text(
        "SELECT payload FROM agent_reports WHERE report_type = 'anomaly' "
        "AND created_at >= :cutoff ORDER BY id DESC LIMIT 20"
    ), {"cutoff": cutoff})).all()
    for (payload,) in row:
        try:
            if json.loads(payload).get("kind") == kind:
                return True
        except Exception:
            continue
    return False


async def _notify_webhook(db: AsyncSession, title: str, description: str) -> bool:
    """POST a MessageCard to the configured Teams/Slack webhook (best effort)."""
    from app.services.agent_service import _get_setting
    row = await _get_setting(db, "notifications")
    url = ((row.data or {}).get("webhookUrl") or (row.data or {}).get("slackWebhook") or "").strip() if row else ""
    if not url:
        return False
    try:
        import httpx
        payload = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": "E34948",
            "summary": title,
            "sections": [{"activityTitle": f"🚨 {title}", "activitySubtitle": description}],
            "text": f"{title} — {description}",  # Slack-compatible fallback field
        }
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.post(url, json=payload)
        return resp.status_code < 300
    except Exception as e:
        logger.warning("Anomaly webhook notification failed: %s", e)
        return False


async def check_anomalies(db: AsyncSession) -> list[dict]:
    """Run the hourly anomaly sweep. Returns the anomalies raised (may be [])."""
    counts = await _hourly_counts(db, hours=7 * 24)
    if len(counts) < MIN_BASELINE_HOURS:
        return []

    *baseline_rows, current = counts
    baseline_totals = [r["total"] for r in baseline_rows]
    anomalies = []

    # 1) Message volume spike
    z_vol = zscore(current["total"], baseline_totals)
    if z_vol > Z_THRESHOLD and current["total"] >= 10:
        anomalies.append({
            "kind": "volume_spike",
            "title": "Pic de volume de messages",
            "description": (
                f"{current['total']} messages sur la dernière heure "
                f"(z-score {z_vol:.1f} vs les 7 derniers jours)."
            ),
            "value": current["total"],
            "zscore": round(min(z_vol, 99.0), 2),
        })

    # 2) KB-miss rate spike (users asking things the KB can't answer)
    baseline_rates = [r["misses"] / r["total"] for r in baseline_rows if r["total"] >= 5]
    if current["total"] >= 10 and baseline_rates:
        rate = current["misses"] / current["total"]
        z_rate = zscore(rate, baseline_rates)
        if z_rate > Z_THRESHOLD and rate > 0.5:
            anomalies.append({
                "kind": "kb_miss_spike",
                "title": "Pic de questions hors base de connaissances",
                "description": (
                    f"{rate:.0%} des requêtes de la dernière heure ont contourné la KB "
                    f"(z-score {z_rate:.1f}) — lacunes de contenu probables."
                ),
                "value": round(rate, 3),
                "zscore": round(min(z_rate, 99.0), 2),
            })

    raised = []
    for anomaly in anomalies:
        if await _recent_alert_exists(db, anomaly["kind"]):
            continue
        anomaly["detected_at"] = datetime.now(timezone.utc).isoformat()
        anomaly["notified"] = await _notify_webhook(db, anomaly["title"], anomaly["description"])
        await db.execute(
            text("INSERT INTO agent_reports (report_type, payload) VALUES ('anomaly', :pl)"),
            {"pl": json.dumps(anomaly, ensure_ascii=False)},
        )
        await db.commit()
        logger.warning("ANOMALY raised: %s — %s", anomaly["kind"], anomaly["description"])
        raised.append(anomaly)
    return raised
