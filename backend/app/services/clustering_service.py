"""
Clustering / Insights Service — turns collected chat data into admin insights.

Three analyses, all built on the shared multilingual embeddings:
  - Knowledge gaps  : cluster queries the KB failed to answer (low scores /
                      negative feedback) → "users keep asking about X and the
                      KB has nothing".
  - Incident clusters: cluster incident-intent messages to surface recurring
                      themes beyond the simple RG2 keyword counters.
  - Threshold recommendation: grid-search routing thresholds (t_low/t_high)
                      against feedback joined to rag_analytics; never
                      auto-applied — stored as a recommendation report.

Reports persist in the agent_reports table.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MIN_CLUSTER_SIZE = 3
MIN_RATED_ROWS_FOR_THRESHOLDS = 100


# ── Generic embedding clustering ──────────────────────────────────

def _cluster_texts_sync(texts: List[str]) -> List[dict]:
    """Cluster texts with HDBSCAN (fallback: agglomerative). Returns
    [{"indices": [...], "medoid": idx, "size": n}] sorted by size desc.
    Noise points are dropped."""
    from app.services.embedding_service import embedding_service
    import numpy as np

    if len(texts) < MIN_CLUSTER_SIZE or not embedding_service.available:
        return []
    vectors = embedding_service.encode_sync(texts, normalize=True)

    labels = None
    try:
        from sklearn.cluster import HDBSCAN
        labels = HDBSCAN(min_cluster_size=MIN_CLUSTER_SIZE).fit_predict(vectors)
        if (labels >= 0).sum() == 0:
            labels = None  # everything is noise — try the fallback
    except Exception as e:
        logger.warning("HDBSCAN failed (%s) — trying agglomerative", e)

    if labels is None:
        try:
            from sklearn.cluster import AgglomerativeClustering
            labels = AgglomerativeClustering(
                n_clusters=None, distance_threshold=0.65, metric="cosine", linkage="average"
            ).fit_predict(vectors)
        except Exception as e:
            logger.warning("Agglomerative clustering failed: %s", e)
            return []

    clusters = []
    for label in set(labels):
        if label < 0:
            continue
        indices = [i for i, lbl in enumerate(labels) if lbl == label]
        if len(indices) < MIN_CLUSTER_SIZE:
            continue
        # Medoid = member closest to the cluster centroid
        member_vecs = vectors[indices]
        centroid = member_vecs.mean(axis=0)
        centroid /= (np.linalg.norm(centroid) or 1.0)
        sims = member_vecs @ centroid
        medoid = indices[int(np.argmax(sims))]
        clusters.append({"indices": indices, "medoid": medoid, "size": len(indices)})
    clusters.sort(key=lambda c: c["size"], reverse=True)
    return clusters


async def cluster_texts(texts: List[str]) -> List[dict]:
    return await asyncio.to_thread(_cluster_texts_sync, texts)


async def _title_cluster(examples: List[str]) -> Optional[str]:
    """One fast LLM call to give a cluster a short French title (best effort)."""
    from app.services.llm_service import llm_service
    if not llm_service.available:
        return None
    try:
        msg = await llm_service.chat_completion(
            [
                {"role": "system", "content": (
                    "Donne un titre court (max 8 mots, en français) qui résume le thème "
                    "commun de ces messages d'utilisateurs. Réponds uniquement avec le titre."
                )},
                {"role": "user", "content": "\n".join(f"- {e[:200]}" for e in examples[:5])},
            ],
            fast=True, max_tokens=30, temperature=0.2, timeout=8.0,
        )
        return (msg.content or "").strip().strip('"')[:100] or None
    except Exception:
        return None


async def _save_report(db: AsyncSession, report_type: str, payload: dict) -> None:
    await db.execute(
        text("INSERT INTO agent_reports (report_type, payload) VALUES (:rt, :pl)"),
        {"rt": report_type, "pl": json.dumps(payload, ensure_ascii=False)},
    )


async def latest_report(db: AsyncSession, report_type: str) -> Optional[dict]:
    row = (await db.execute(
        text(
            "SELECT payload, created_at FROM agent_reports "
            "WHERE report_type = :rt ORDER BY id DESC LIMIT 1"
        ),
        {"rt": report_type},
    )).first()
    if not row:
        return None
    payload = json.loads(row[0])
    payload["generated_at"] = str(row[1])
    return payload


# ── Knowledge-gap analysis (B5) ───────────────────────────────────

async def analyze_knowledge_gaps(db: AsyncSession, t_low: float = 0.35, days: int = 30) -> dict:
    """Cluster queries the KB could not answer well. Persists a report."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    # Low-score / KB-skipped queries
    rows = (await db.execute(
        text(
            "SELECT query_text, top_score FROM rag_analytics "
            "WHERE query_text IS NOT NULL AND timestamp >= :cutoff "
            "AND (routing = 'groq_only' OR top_score < :tl)"
        ),
        {"cutoff": cutoff, "tl": t_low},
    )).all()
    texts = [r[0] for r in rows if r[0] and r[0].strip()]

    # User questions that led to negatively-rated bot replies
    neg_rows = (await db.execute(
        text(
            "SELECT ra.query_text FROM rag_analytics ra "
            "JOIN feedback f ON f.message_id = ra.bot_message_id "
            "WHERE f.rating = 'negative' AND ra.query_text IS NOT NULL "
            "AND ra.timestamp >= :cutoff"
        ),
        {"cutoff": cutoff},
    )).all()
    texts.extend(r[0] for r in neg_rows if r[0] and r[0].strip())

    report = {"window_days": days, "analyzed_queries": len(texts), "clusters": []}
    if len(texts) >= MIN_CLUSTER_SIZE:
        clusters = await cluster_texts(texts)
        for c in clusters[:10]:
            examples = [texts[i] for i in c["indices"][:5]]
            title = await _title_cluster(examples)
            report["clusters"].append({
                "title": title or texts[c["medoid"]][:80],
                "representative_query": texts[c["medoid"]],
                "count": c["size"],
                "examples": examples,
            })

    await _save_report(db, "knowledge_gaps", report)
    logger.info(
        "Knowledge-gap analysis: %d queries → %d cluster(s)",
        len(texts), len(report["clusters"])
    )
    return report


# ── Incident clustering (C8) ──────────────────────────────────────

async def analyze_incident_clusters(db: AsyncSession, days: int = 30) -> dict:
    """Cluster incident-intent messages to surface recurring themes."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = (await db.execute(
        text(
            "SELECT query_text, timestamp FROM rag_analytics "
            "WHERE intent = 'incident_report' AND query_text IS NOT NULL "
            "AND timestamp >= :cutoff"
        ),
        {"cutoff": cutoff},
    )).all()
    texts = [r[0] for r in rows if r[0] and r[0].strip()]
    stamps = [str(r[1]) for r in rows if r[0] and r[0].strip()]

    report = {"window_days": days, "analyzed_messages": len(texts), "clusters": []}
    if len(texts) >= MIN_CLUSTER_SIZE:
        clusters = await cluster_texts(texts)
        for c in clusters[:10]:
            examples = [texts[i] for i in c["indices"][:5]]
            cluster_stamps = sorted(stamps[i] for i in c["indices"])
            title = await _title_cluster(examples)
            report["clusters"].append({
                "title": title or texts[c["medoid"]][:80],
                "representative_message": texts[c["medoid"]],
                "count": c["size"],
                "examples": examples,
                "first_seen": cluster_stamps[0],
                "last_seen": cluster_stamps[-1],
            })

    await _save_report(db, "incident_clusters", report)
    logger.info(
        "Incident clustering: %d messages → %d cluster(s)",
        len(texts), len(report["clusters"])
    )
    return report


# ── Learned routing thresholds (C9) ───────────────────────────────

async def recommend_thresholds(db: AsyncSession) -> dict:
    """Grid-search t_low/t_high maximizing the estimated positive-feedback rate.

    Counterfactual estimate: from rated history we learn the observed positive
    rate per (score bin, actual routing). For candidate thresholds each sample
    is re-routed by its score and scored with the learned rate for that
    (bin, routing) combo — falling back to the bin's overall rate when that
    combo was never observed. Recommendation only — admin applies it."""
    rows = (await db.execute(
        text(
            "SELECT ra.top_score, ra.routing, f.rating FROM rag_analytics ra "
            "JOIN feedback f ON f.message_id = ra.bot_message_id "
            "WHERE ra.routing != 'cache'"
        )
    )).all()
    samples = [
        (float(r[0]), str(r[1]), 1 if r[2] == "positive" else 0)
        for r in rows if r[2] in ("positive", "negative")
    ]

    report: dict = {"rated_rows": len(samples)}
    if len(samples) < MIN_RATED_ROWS_FOR_THRESHOLDS:
        report["status"] = "insufficient_data"
        report["required_rows"] = MIN_RATED_ROWS_FOR_THRESHOLDS
        await _save_report(db, "threshold_recommendation", report)
        return report

    def _bin(score: float) -> int:
        return min(int(score / 0.05), 19)

    # Observed rates: rate[(bin, routing)] and rate[bin] overall
    combo_stats: dict = {}
    bin_stats: dict = {}
    for score, routing, ok in samples:
        b = _bin(score)
        combo_stats.setdefault((b, routing), [0, 0])
        combo_stats[(b, routing)][0] += ok
        combo_stats[(b, routing)][1] += 1
        bin_stats.setdefault(b, [0, 0])
        bin_stats[b][0] += ok
        bin_stats[b][1] += 1

    overall_rate = sum(ok for _, _, ok in samples) / len(samples)

    def _estimated_rate(b: int, routing: str) -> float:
        combo = combo_stats.get((b, routing))
        if combo and combo[1] >= 3:
            return combo[0] / combo[1]
        bucket = bin_stats.get(b)
        if bucket and bucket[1] > 0:
            return bucket[0] / bucket[1]
        return overall_rate

    def score_pair(t_low: float, t_high: float) -> float:
        total = 0.0
        for score, _actual, _ok in samples:
            if score >= t_high:
                simulated = "kb_primary"
            elif score >= t_low:
                simulated = "kb_hint"
            else:
                simulated = "groq_only"
            total += _estimated_rate(_bin(score), simulated)
        return total / len(samples)

    grid_low = [round(0.20 + 0.05 * i, 2) for i in range(7)]    # 0.20 … 0.50
    grid_high = [round(0.55 + 0.05 * i, 2) for i in range(8)]   # 0.55 … 0.90
    best = None
    for tl in grid_low:
        for th in grid_high:
            if tl >= th:
                continue
            s = score_pair(tl, th)
            if best is None or s > best[0]:
                best = (s, tl, th)

    report.update({
        "status": "ok",
        "recommended_t_low": best[1],
        "recommended_t_high": best[2],
        "expected_positive_rate": round(best[0], 4),
        "current_positive_rate": round(overall_rate, 4),
    })
    await _save_report(db, "threshold_recommendation", report)
    logger.info(
        "Threshold recommendation: t_low=%.2f t_high=%.2f (from %d rated rows)",
        best[1], best[2], len(samples)
    )
    return report
