"""
RAG Service — Retrieval-Augmented Generation using ChromaDB + BM25 hybrid retrieval.
- Persistent ChromaDB (survives restarts)
- 20+ rich built-in incident entries
- Hybrid retrieval: dense (ChromaDB) + sparse (BM25) fused with Reciprocal Rank Fusion
- Returns relevance scores AND source document IDs alongside documents
- Sentence-aware chunking preserving semantic boundaries
- Supports PDF, TXT, DOCX, MD, CSV ingestion
- Maintains a manifest.json for tracking uploaded documents
"""
import io
import json
import os
import re
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Tuple, Optional

try:
    from rank_bm25 import BM25Okapi
    _BM25_AVAILABLE = True
except ImportError:
    _BM25_AVAILABLE = False
    BM25Okapi = None  # type: ignore

logger = logging.getLogger(__name__)

KNOWLEDGE_BASE_DIR = os.path.abspath(
    os.getenv("KNOWLEDGE_BASE_DIR")
    or os.path.join(os.path.dirname(__file__), "..", "..", "knowledge_base")
)

# Hermetic-test switch: skip ChromaDB entirely, use the keyword fallback store
_DISABLE_CHROMA = os.getenv("DISABLE_CHROMA", "").lower() in ("1", "true", "yes")
CHROMA_PERSIST_DIR = os.path.join(KNOWLEDGE_BASE_DIR, "chroma_db")
MANIFEST_PATH = os.path.join(KNOWLEDGE_BASE_DIR, "manifest.json")

os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
os.makedirs(KNOWLEDGE_BASE_DIR, exist_ok=True)

# ── Built-in knowledge base (20+ detailed TMA incident entries) ────
_BUILTIN_DOCS = [
    {
        "id": "tma-restart",
        "content": (
            "Procédure de redémarrage d'un service TMA: Vérifier d'abord les logs du service "
            "avec journalctl -u <service> -n 100. Arrêter proprement avec systemctl stop <service> "
            "et vérifier qu'aucun processus résiduel ne tourne (ps aux | grep <service>). "
            "Redémarrer avec systemctl start <service> puis contrôler le statut avec systemctl status <service>. "
            "Surveiller les logs de démarrage pendant 5 minutes avant de clôturer l'incident."
        ),
        "topic": "maintenance"
    },
    {
        "id": "tma-incident-procedure",
        "content": (
            "Procédure de gestion d'incident TMA: Identifier le service impacté et classifier la sévérité (P1=critique, "
            "P2=majeur, P3=mineur). Ouvrir immédiatement un ticket Jira avec les métriques d'impact. "
            "Notifier l'équipe on-call via PagerDuty. Appliquer la procédure de résolution correspondante. "
            "Documenter chaque action avec horodatage. Si l'incident se répète 3 fois (RG2), générer un guide permanent."
        ),
        "topic": "incident"
    },
    {
        "id": "api-gateway-saturation",
        "content": (
            "Incident: Saturation mémoire API Gateway (P2). Symptômes: latence > 2s, erreurs 503, CPU > 90%. "
            "Cause racine: absence de règles d'autoscaling proactif, seuil d'alerte mémoire fixé à 95% sans trigger. "
            "Résolution immédiate: redémarrer l'API Gateway, augmenter la mémoire (+4 GB), activer l'autoscaling sur seuil 70%. "
            "Prévention: load testing hebdomadaire, alertes PagerDuty sur mémoire > 70%, circuit breaker sur tous les consumers."
        ),
        "topic": "infrastructure"
    },
    {
        "id": "llm-timeout",
        "content": (
            "Incident: Timeouts LLM Service (P2). Symptômes: 100% des inférences > 30s échouent, erreur 504. "
            "Cause racine: déploiement du modèle v2.3 sans chunking des inputs > 8K tokens, absence de timeout applicatif. "
            "Résolution: rollback vers LLM v2.1, activer le circuit breaker (seuil 5s), déployer middleware de chunking automatique. "
            "Prévention: tester tous les modèles avec inputs > 8K en staging, définir timeout applicatif de 10s, rollback automatique si error rate > 5%."
        ),
        "topic": "performance"
    },
    {
        "id": "redis-corruption",
        "content": (
            "Incident: Corruption cache Redis (P2). Symptômes: 8% des utilisateurs reçoivent des données incorrectes, réponses incohérentes. "
            "Cause racine: désynchronisation entre opérations d'écriture et invalidation du cache, TTL trop long (24h) pour données mutables. "
            "Résolution immédiate: identifier les clés corrompues (SCAN), purge sélective, réduire TTL à 1h. "
            "Prévention: implémenter pattern Write-Through, réduire TTL des données mutables à 30 min max, checksums sur valeurs critiques."
        ),
        "topic": "infrastructure"
    },
    {
        "id": "auth-latency",
        "content": (
            "Incident: Latence Auth Service > 800ms (P3). Symptômes: 40% des utilisateurs avec latence élevée, login lent. "
            "Cause racine: TTL Redis remis à 0 lors d'une mise à jour de configuration, cache de sessions désactivé. "
            "Résolution: reconfigurer TTL Redis à 3600 secondes, vider et recharger le cache de sessions. "
            "Prévention: validation du TTL Redis dans les checks post-déploiement, alerting sur cache hit rate < 80%."
        ),
        "topic": "security"
    },
    {
        "id": "502-bad-gateway",
        "content": (
            "Incident: Erreurs 502 Bad Gateway (P2). Symptômes: 12% des requêtes retournent 502, intermittent. "
            "Cause racine: mise à jour load balancer v3.2 avec breaking change sur health checks (header X-Health requis). "
            "Résolution: rollback LB vers v3.1, ajouter header X-Health aux backends, valider chaque nœud. "
            "Prévention: canary deploy obligatoire pour mises à jour LB, tests de compatibilité health check en staging."
        ),
        "topic": "availability"
    },
    {
        "id": "db-fragmentation",
        "content": (
            "Incident: Latence base de données PostgreSQL +35% (P3). Symptômes: requêtes lentes, Seq Scan sur tables > 50M lignes. "
            "Cause racine: fragmentation des index btree après 6 mois sans REINDEX, taux de fragmentation 67%. "
            "Résolution: REINDEX CONCURRENTLY sur les 5 tables les plus fragmentées, VACUUM ANALYZE hebdomadaire. "
            "Prévention: REINDEX CONCURRENTLY mensuel, alerting sur fragmentation > 30%, dimensionner AUTOVACUUM selon la charge."
        ),
        "topic": "performance"
    },
    {
        "id": "ssl-expiry",
        "content": (
            "Incident: Certificat SSL expiré (P3). Symptômes: erreurs HTTPS sur domaine, browsers bloquent accès. "
            "Cause racine: renouvellement automatique Let's Encrypt non configuré, aucune alerte sur expiration. "
            "Résolution immédiate: renouveler manuellement avec certbot renew --force-renewal, recharger nginx. "
            "Prévention: configurer certbot en cron (0 12 * * * certbot renew), alerting 30 jours avant expiration, monitoring ssl-cert-check."
        ),
        "topic": "security"
    },
    {
        "id": "queue-overflow",
        "content": (
            "Incident: Saturation file d'attente workers (P2). Symptômes: jobs en attente > 10K, délai de traitement > 1h. "
            "Cause racine: batch job de réindexation planifié à 02h sans analyse des patterns de trafic, conflits avec trafic Asie-Pacifique. "
            "Résolution: annuler le batch, scale-up workers × 3, reprogrammer à 04h30. "
            "Prévention: scheduler intelligent basé sur métriques, throttling batch à 20% max, maintenir 80% capacité min la nuit."
        ),
        "topic": "infrastructure"
    },
    {
        "id": "memory-leak-worker",
        "content": (
            "Incident: Fuite mémoire Queue Worker P1. Symptômes: service redémarre en boucle, mémoire Node.js à 98%. "
            "Cause racine: event listener WebSocket non supprimé sur disconnect, accumulation après 4h de fonctionnement. "
            "Résolution: redémarrer avec préservation file Redis, déployer patch de suppression des listeners, valider avec 10K connect/disconnect. "
            "Prévention: code review obligatoire pour tout event listener, alerting mémoire par processus à 80%, redémarrage gracieux si > 90%."
        ),
        "topic": "infrastructure"
    },
    {
        "id": "db-migration-downtime",
        "content": (
            "Incident: Interruption base de données 18 min (P1). Symptômes: 100% des opérations read/write bloquées. "
            "Cause racine: migration schéma v14 exécutée directement en production sans blue-green, verrou exclusif sur tables principales. "
            "Résolution: attente fin migration, vérification intégrité données, documentation procédure sans downtime. "
            "Prévention: toute migration doit utiliser pg_repack ou migration online, fenêtre maintenance obligatoire avec approbation CAB."
        ),
        "topic": "availability"
    },
    {
        "id": "circuit-breaker",
        "content": (
            "Pattern circuit breaker pour services TMA: Un circuit breaker protège les services en aval en coupant le flux de requêtes "
            "quand le taux d'erreur dépasse un seuil (ex: 50% en 30s). États: CLOSED (normal), OPEN (bloqué), HALF-OPEN (test). "
            "Implémentation: utiliser Hystrix, Resilience4j ou une librairie Python équivalente. "
            "Configuration recommandée: seuil 5 erreurs consécutives, timeout 5s, délai de récupération 30s avant test HALF-OPEN."
        ),
        "topic": "architecture"
    },
    {
        "id": "api-quota-exceeded",
        "content": (
            "Incident: Quota API externe dépassé (P3). Symptômes: 8% des requêtes LLM bloquées, erreur 429 de l'API externe. "
            "Cause racine: boucle de retry sans condition de sortie sur erreur 429, quota journalier épuisé en 2h. "
            "Résolution: arrêt du gestionnaire de retry bogué, attente reset quota à minuit UTC. "
            "Prévention: backoff exponentiel obligatoire (max 3 tentatives), alerting à 80% quota consommé, circuit breaker sur appels externes."
        ),
        "topic": "performance"
    },
    {
        "id": "container-crash",
        "content": (
            "Incident: Crash de conteneur Docker en production (P2). Symptômes: pods Kubernetes en CrashLoopBackOff, service indisponible. "
            "Diagnostic: kubectl logs <pod> --previous pour voir les logs avant le crash, kubectl describe pod pour les events. "
            "Causes fréquentes: OOMKilled (mémoire insuffisante), probe liveness trop agressive, dépendance externe non disponible. "
            "Résolution: augmenter les resource limits, corriger la liveness probe, vérifier les dépendances externes avant démarrage."
        ),
        "topic": "infrastructure"
    },
    {
        "id": "notification-crash",
        "content": (
            "Incident: Crash Notification Service (P3). Symptômes: notifications non envoyées, service en erreur. "
            "Cause racine: mise à jour automatique dépendance nodemailer v4.2 avec breaking change dans l'API SMTP. "
            "Résolution: rollback vers nodemailer v4.1.8, corriger configuration transport. "
            "Prévention: interdire 'latest' en package.json, committer package-lock.json, tests d'intégration SMTP en CI."
        ),
        "topic": "infrastructure"
    },
    {
        "id": "security-brute-force",
        "content": (
            "Incident sécurité: Attaque brute-force sur /auth/login (P2). Symptômes: 1842 tentatives depuis 3 IPs, logs d'erreurs auth en masse. "
            "Cause racine: absence de rate limiting sur l'endpoint login, pas de détection d'anomalies comportementales. "
            "Résolution immédiate: blacklister les 3 IPs sources via firewall, activer rate limiting (5 tentatives/IP/minute). "
            "Prévention: CAPTCHA après 3 échecs, blacklist automatique après 10 échecs en 5 minutes, alerting dès la 1ère tentative suspecte."
        ),
        "topic": "security"
    },
    {
        "id": "canary-rollback",
        "content": (
            "Incident: Échec déploiement canary avec rollback automatique (P2). Symptômes: taux d'erreur 8% dans les 5 premières minutes post-déploiement. "
            "Cause racine: tests pré-déploiement ne couvrant pas le cas d'usage réel, régression non détectée en staging. "
            "Résolution: rollback automatique déclenché par Argo Rollouts, rollback manuel si automatique échoue. "
            "Prévention: enrichir les tests E2E de staging, critères de promotion stricts (error rate < 1%, latence < 500ms)."
        ),
        "topic": "deployment"
    },
    {
        "id": "tma-database",
        "content": (
            "Résolution des problèmes de base de données: Vérifier la connectivité réseau (telnet db-host 5432). "
            "Consulter les logs PostgreSQL (/var/log/postgresql/). Contrôler l'espace disque (df -h). "
            "Vérifier les connexions actives (SELECT * FROM pg_stat_activity). Identifier les requêtes bloquantes. "
            "Redémarrer le service si nécessaire (systemctl restart postgresql). Toujours sauvegarder avant intervention."
        ),
        "topic": "database"
    },
    {
        "id": "tma-monitoring",
        "content": (
            "Monitoring et alerting TMA: Configurer les health checks pour chaque service (endpoint /health retournant 200). "
            "Définir les SLA (99.9% uptime) et SLO (latence P99 < 500ms). "
            "Configurer les alertes Prometheus/Grafana avec seuils: CPU > 80%, mémoire > 85%, erreurs > 1%. "
            "Surveiller les temps de réponse API et l'utilisation des ressources. "
            "Mettre en place des dashboards Grafana avec les métriques clés de chaque service TMA."
        ),
        "topic": "monitoring"
    },
    {
        "id": "tma-deployment",
        "content": (
            "Procédure de déploiement TMA: Valider les tests unitaires et d'intégration (100% pass). "
            "Créer un tag de release Git (git tag v2.x.x). Déployer en environnement de staging en premier. "
            "Valider les tests de non-régression complets. Déployer en production avec stratégie canary (10% → 25% → 100%). "
            "Monitorer les métriques post-déploiement pendant 30 minutes. Documenter le déploiement dans le changelog."
        ),
        "topic": "deployment"
    },
    {
        "id": "tma-security",
        "content": (
            "Bonnes pratiques sécurité TMA: Rotation régulière des secrets et API keys (tous les 90 jours). "
            "Audit des dépendances (npm audit, pip audit) à chaque déploiement. "
            "Scan des images Docker avec Trivy avant mise en production. "
            "Vérification des headers OWASP (X-Frame-Options, CSP, HSTS). "
            "Rate limiting sur toutes les APIs publiques. Logs d'audit pour les actions sensibles (admin, données personnelles)."
        ),
        "topic": "security"
    },
    {
        "id": "tma-rg2",
        "content": (
            "Guide RG2 - Gestion des récurrences d'incidents: Quand un incident se produit 3 fois ou plus, déclencher le processus RG2. "
            "Analyser la cause racine commune entre les occurrences. Documenter le pattern de récurrence. "
            "Proposer une solution permanente (patch, refactoring, configuration). "
            "Créer un ticket Jira de type 'Amélioration' avec priorité Haute. "
            "Mettre à jour la base de connaissances avec le guide de résolution définitif."
        ),
        "topic": "rg2"
    },
    {
        "id": "load-balancer-config",
        "content": (
            "Configuration et dépannage du load balancer TMA: Vérifier les health checks de tous les backends (statut UP/DOWN). "
            "Contrôler la distribution du trafic (algorithme round-robin, least-connections ou IP-hash). "
            "Vérifier les logs d'accès pour identifier les backends qui retournent des erreurs. "
            "En cas de nœud défaillant: l'exclure manuellement, corriger le problème, réintégrer progressivement. "
            "Configurer des timeouts appropriés: connect 5s, read 30s, send 30s."
        ),
        "topic": "infrastructure"
    },
    {
        "id": "tma-performance-diagnostic",
        "content": (
            "Diagnostic de performance applicative TMA: Analyser les métriques CPU/RAM/IO avec top, iostat, vmstat. "
            "Identifier les requêtes SQL lentes (EXPLAIN ANALYZE, pg_stat_statements). "
            "Vérifier les index de base de données manquants ou fragmentés. "
            "Contrôler les files d'attente (longueur, délai de traitement). "
            "Vérifier la configuration du cache Redis (taux de hit, évictions). "
            "Profiler l'application si nécessaire (py-spy pour Python, async-profiler pour Java)."
        ),
        "topic": "performance"
    },
]


class RAGService:
    def __init__(self):
        self._chroma_available = False
        self._collection = None
        self._client = None   # shared PersistentClient (also used by conversation index)
        self._documents: List[dict] = list(_BUILTIN_DOCS)
        # BM25 hybrid retrieval index
        self._bm25: Optional[object] = None
        self._bm25_corpus: List[str] = []     # chunk texts (parallel with _bm25_ids)
        self._bm25_ids: List[str] = []        # chunk IDs / source labels
        self._init_backend()

    def _init_backend(self):
        if _DISABLE_CHROMA:
            logger.info("DISABLE_CHROMA set — using in-memory keyword fallback store")
            self._chroma_available = False
            self._collection = None
            return
        try:
            import chromadb
            client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
            self._client = client

            # Prefer the local multilingual embedding model (French-aware) over
            # ChromaDB's default English-centric ONNX model when available.
            embedding_fn = None
            target_model = None
            try:
                from app.services.embedding_service import (
                    embedding_service, EMBEDDING_MODEL_NAME, MultilingualEmbeddingFunction
                )
                if embedding_service.available:
                    embedding_fn = MultilingualEmbeddingFunction()
                    target_model = EMBEDDING_MODEL_NAME
            except Exception as e:
                logger.warning("Local embedding model unavailable (%s) — using ChromaDB default", e)

            collection = self._get_collection(client, embedding_fn, target_model)

            # Verify the embedding function works before committing to ChromaDB mode
            _probe_id = "__health_probe__"
            collection.upsert(
                ids=[_probe_id],
                documents=["probe"],
                metadatas=[{"source": "_probe", "topic": "_probe"}]
            )
            collection.delete(ids=[_probe_id])
            self._collection = collection
            self._chroma_available = True
            logger.info(
                "ChromaDB PersistentClient initialized at %s (embeddings: %s)",
                CHROMA_PERSIST_DIR, target_model or "chromadb-default"
            )
            self._load_builtin_knowledge()
        except Exception as e:
            logger.warning(
                "ChromaDB unavailable or embedding function failed (%s) — using keyword fallback. "
                "Install missing deps: pip install chromadb[default] or pip install onnxruntime",
                e
            )
            self._chroma_available = False
            self._collection = None
            # Built-in docs already pre-loaded in self._documents at __init__ time

    def _get_collection(self, client, embedding_fn, target_model: Optional[str]):
        """Open the KB collection, re-indexing it when the embedding model changed.

        Old and new vectors are both 384-dim, so ChromaDB would silently mix
        them — the `embedding_model` metadata marker prevents that.
        """
        kwargs = {"embedding_function": embedding_fn} if embedding_fn else {}
        metadata = {"hnsw:space": "cosine"}
        if target_model:
            metadata["embedding_model"] = target_model

        collection = client.get_or_create_collection(
            name="dxc_knowledge_base", metadata=metadata, **kwargs
        )
        if not target_model:
            return collection

        existing_model = (collection.metadata or {}).get("embedding_model")
        if existing_model == target_model:
            return collection
        if collection.count() == 0:
            # Empty legacy collection: recreate with the marker, nothing to migrate
            client.delete_collection("dxc_knowledge_base")
            return client.get_or_create_collection(
                name="dxc_knowledge_base", metadata=metadata, **kwargs
            )
        return self._reindex_collection(client, collection, metadata, kwargs)

    @staticmethod
    def _reindex_collection(client, old_collection, metadata: dict, kwargs: dict):
        """Re-embed every stored chunk with the current embedding model."""
        logger.info(
            "Embedding model changed (was: %s, now: %s) — re-indexing knowledge base...",
            (old_collection.metadata or {}).get("embedding_model", "chromadb-default"),
            metadata.get("embedding_model"),
        )
        data = old_collection.get(include=["documents", "metadatas"])
        ids = data.get("ids") or []
        docs = data.get("documents") or []
        metas = data.get("metadatas") or []

        client.delete_collection("dxc_knowledge_base")
        new_collection = client.get_or_create_collection(
            name="dxc_knowledge_base", metadata=metadata, **kwargs
        )
        batch = 100
        for i in range(0, len(ids), batch):
            new_collection.add(
                ids=ids[i:i + batch],
                documents=docs[i:i + batch],
                metadatas=metas[i:i + batch],
            )
            logger.info("Re-indexed %d/%d chunks", min(i + batch, len(ids)), len(ids))
        logger.info("Knowledge base re-index complete: %d chunks", len(ids))
        return new_collection

    def _load_builtin_knowledge(self):
        """Load built-in knowledge entries into ChromaDB + BM25 if not already present."""
        if not self._chroma_available or self._collection is None:
            return
        try:
            existing_ids = set(self._collection.get(ids=[d["id"] for d in _BUILTIN_DOCS])["ids"])
            missing = [d for d in _BUILTIN_DOCS if d["id"] not in existing_ids]
            if missing:
                self._collection.add(
                    ids=[d["id"] for d in missing],
                    documents=[d["content"] for d in missing],
                    metadatas=[{"topic": d["topic"], "source": d["id"]} for d in missing]
                )
                logger.info("Loaded %d new built-in docs into ChromaDB", len(missing))
        except Exception as e:
            logger.error("Failed to load built-in docs: %s", e)
        # Always rebuild BM25 from the full ChromaDB corpus
        self._rebuild_bm25()

    def _rebuild_bm25(self):
        """Rebuild the in-memory BM25 index from all documents stored in ChromaDB."""
        if not _BM25_AVAILABLE or not self._chroma_available or self._collection is None:
            return
        try:
            count = self._collection.count()
            if count == 0:
                return
            all_data = self._collection.get(include=["documents", "metadatas"])
            self._bm25_corpus = all_data.get("documents") or []
            metadatas = all_data.get("metadatas") or []
            self._bm25_ids = [
                m.get("source", f"doc-{i}") if m else f"doc-{i}"
                for i, m in enumerate(metadatas)
            ]
            tokenized = [doc.lower().split() for doc in self._bm25_corpus]
            self._bm25 = BM25Okapi(tokenized)
            logger.info("BM25 index rebuilt with %d documents", len(self._bm25_corpus))
        except Exception as e:
            logger.warning("BM25 rebuild failed: %s", e)

    def _rrf_fuse(
        self,
        dense_ids: List[str], dense_scores: List[float],
        sparse_ids: List[str], sparse_raw: List[float],
        k: int = 60
    ) -> List[Tuple[str, float]]:
        """
        Reciprocal Rank Fusion: combines dense and sparse rankings.
        RRF score = Σ 1 / (k + rank_i)   — higher is better.
        """
        rrf: dict = {}
        for rank, doc_id in enumerate(dense_ids):
            rrf[doc_id] = rrf.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
        for rank, doc_id in enumerate(sparse_ids):
            rrf[doc_id] = rrf.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
        return sorted(rrf.items(), key=lambda x: x[1], reverse=True)

    # ── Search ────────────────────────────────────────────────────

    async def search(
        self, query: str, n_results: int = 3, rerank: bool = True
    ) -> Tuple[List[str], List[float], List[str]]:
        """
        Hybrid search: dense (ChromaDB) + sparse (BM25) fused with Reciprocal Rank Fusion,
        optionally reranked with a multilingual cross-encoder.
        Returns (documents, scores, sources) where:
          - scores are 0-1 (1 = perfect match); cross-encoder sigmoid scores when reranked
          - sources are document IDs / topic labels for attribution
        """
        if not (self._chroma_available and self._collection is not None):
            return self._search_keyword(query, n_results)

        use_rerank = False
        if rerank:
            try:
                from app.services.embedding_service import embedding_service
                use_rerank = embedding_service.reranker_available
            except Exception:
                use_rerank = False

        # Fetch a wider candidate pool when reranking
        candidate_n = max(10, n_results * 3) if use_rerank else n_results
        docs, scores, sources = self._search_hybrid(query, candidate_n)

        if use_rerank and docs:
            try:
                from app.services.embedding_service import embedding_service
                ce_scores = await embedding_service.rerank(query, docs)
                if ce_scores:
                    # Cross-encoder logits are not calibrated to the cosine scale
                    # used by confidence routing — use them for ORDERING only and
                    # keep each doc's dense similarity score attached.
                    order = sorted(
                        range(len(docs)), key=lambda i: ce_scores[i], reverse=True
                    )[:n_results]
                    reranked = (
                        [docs[i] for i in order],
                        [scores[i] for i in order],
                        [sources[i] for i in order],
                    )
                    logger.info(
                        "Reranked %d candidates (kept dense scores, top %.3f)",
                        len(docs), max(reranked[1]) if reranked[1] else 0.0
                    )
                    return reranked
            except Exception as e:
                logger.warning("Cross-encoder rerank failed (%s) — using fused order", e)

        return docs[:n_results], scores[:n_results], sources[:n_results]

    def _search_hybrid(self, query: str, n_results: int) -> Tuple[List[str], List[float], List[str]]:
        """Dense (ChromaDB) + Sparse (BM25) retrieval fused with RRF."""
        try:
            if self._collection is None:
                return self._search_keyword(query, n_results)

            total = self._collection.count()
            if total == 0:
                return [], [], []

            # ── Dense retrieval via ChromaDB ──────────────────────
            fetch_n = min(max(n_results * 2, 5), total)
            # NB: "ids" must not appear in include (chromadb 0.4.x rejects it);
            # ids are always returned regardless.
            results = self._collection.query(
                query_texts=[query],
                n_results=fetch_n,
                include=["documents", "distances", "metadatas"]
            )
            dense_docs_raw = results.get("documents", [[]])[0]
            dense_dists    = results.get("distances",  [[]])[0]
            dense_metas    = results.get("metadatas",  [[]])[0]
            dense_ids_raw  = results.get("ids",        [[]])[0]

            # Convert cosine distance [0,2] → similarity [0,1]
            dense_scores = [max(0.0, min(1.0, 1.0 - (d / 2.0))) for d in dense_dists]
            dense_source_map = {
                doc_id: (doc, score, meta)
                for doc_id, doc, score, meta in zip(
                    dense_ids_raw, dense_docs_raw, dense_scores, dense_metas
                )
            }

            # ── Sparse retrieval via BM25 ─────────────────────────
            sparse_ids: List[str] = []
            sparse_scores: List[float] = []
            if _BM25_AVAILABLE and self._bm25 is not None and self._bm25_corpus:
                tokenized_query = query.lower().split()
                bm25_scores = self._bm25.get_scores(tokenized_query)
                top_sparse_idx = sorted(
                    range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True
                )[:fetch_n]
                for idx in top_sparse_idx:
                    if bm25_scores[idx] > 0 and idx < len(self._bm25_ids):
                        sparse_ids.append(self._bm25_ids[idx])
                        sparse_scores.append(float(bm25_scores[idx]))

            # ── Reciprocal Rank Fusion ────────────────────────────
            fused = self._rrf_fuse(dense_ids_raw, dense_scores, sparse_ids, sparse_scores)
            top_fused = fused[:n_results]

            # ── Reconstruct ordered results ───────────────────────
            final_docs: List[str] = []
            final_scores: List[float] = []
            final_sources: List[str] = []

            for doc_id, rrf_score in top_fused:
                if doc_id in dense_source_map:
                    doc, dense_score, meta = dense_source_map[doc_id]
                    # Use the dense similarity score for confidence routing
                    final_docs.append(doc)
                    final_scores.append(dense_score)
                    source = (meta or {}).get("source", doc_id) if meta else doc_id
                    final_sources.append(source)
                else:
                    # BM25-only hit: look it up in corpus
                    try:
                        idx = self._bm25_ids.index(doc_id)
                        final_docs.append(self._bm25_corpus[idx])
                        final_scores.append(0.3)   # moderate confidence for BM25-only hits
                        final_sources.append(doc_id)
                    except (ValueError, IndexError):
                        pass

            mode = "hybrid (dense+BM25+RRF)" if sparse_ids else "dense-only"
            logger.info(
                "RAG %s: %d results (top score: %.3f) for: %.60s",
                mode, len(final_docs), max(final_scores) if final_scores else 0, query
            )
            return final_docs, final_scores, final_sources

        except Exception as e:
            logger.error("Hybrid search failed: %s", e)
            return self._search_keyword(query, n_results)

    def _search_keyword(self, query: str, n_results: int) -> Tuple[List[str], List[float], List[str]]:
        """Simple keyword-based fallback search with normalized scores."""
        query_words = set(query.lower().split())
        scored = []
        for doc in self._documents:
            content_words = set(doc["content"].lower().split())
            hits = len(query_words & content_words)
            if hits > 0:
                score = min(1.0, hits / max(len(query_words), 1) * 0.8)
                scored.append((score, doc["content"], doc.get("id", "keyword-fallback")))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:n_results]
        logger.info("Keyword fallback: %d results for: %.60s", len(top), query)
        return [s[1] for s in top], [s[0] for s in top], [s[2] for s in top]

    # ── Ingestion ─────────────────────────────────────────────────

    async def ingest_pdf(self, file_bytes: bytes, filename: str) -> int:
        """Ingest a PDF into the knowledge base. Returns number of chunks added."""
        from app.services.ocr_service import ocr_service
        text = ocr_service._extract_from_pdf(file_bytes, filename)
        # Only bail on the specific "no extractable text" placeholder — other content is valid
        if not text or (text.startswith("[PDF sans texte") or text.startswith("[Document PDF")):
            logger.warning("PDF extraction failed or empty for %s", filename)
            return 0
        return await self.ingest_text(text, filename, topic="uploaded-pdf")

    async def ingest_text(self, text: str, source: str, topic: str = "uploaded") -> int:
        """Chunk a plain text string and add to the knowledge base."""
        if not text.strip():
            return 0
        chunks = self._chunk_text(text, chunk_size=400, overlap=1)
        if not chunks:
            return 0

        chroma_ok = False
        if self._chroma_available and self._collection is not None:
            try:
                ids = [f"{source}-chunk-{i}" for i in range(len(chunks))]
                # Remove existing chunks for this source before re-adding
                try:
                    existing = self._collection.get(where={"source": source})
                    if existing["ids"]:
                        self._collection.delete(ids=existing["ids"])
                except Exception:
                    pass
                self._collection.add(
                    ids=ids,
                    documents=chunks,
                    metadatas=[{"source": source, "topic": topic}] * len(chunks)
                )
                logger.info("Ingested %d chunks from %s into ChromaDB", len(chunks), source)
                self._rebuild_bm25()
                chroma_ok = True
            except Exception as e:
                logger.error("ChromaDB ingest failed for %s: %s — falling back to keyword store", source, e)

        if not chroma_ok:
            # Keyword fallback — store in-memory (also used when ChromaDB is unavailable)
            self._documents = [d for d in self._documents if not d.get("id", "").startswith(source)]
            for i, chunk in enumerate(chunks):
                self._documents.append({"id": f"{source}-{i}", "content": chunk, "topic": topic})
            logger.info("Stored %d chunks from %s in keyword fallback store", len(chunks), source)

        self._update_manifest(source, topic, len(chunks))
        self._invalidate_semantic_cache()
        return len(chunks)

    @staticmethod
    def _invalidate_semantic_cache():
        """KB content changed — cached answers may be stale."""
        try:
            from app.services.query_service import query_service
            query_service.invalidate_cache()
        except Exception:
            pass

    async def ingest_docx(self, file_bytes: bytes, filename: str) -> int:
        """Extract text from DOCX and ingest into the knowledge base."""
        try:
            from docx import Document
            doc = Document(io.BytesIO(file_bytes))
            paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            text = "\n".join(paragraphs)
            if not text:
                logger.warning("DOCX %s appears empty", filename)
                return 0
            return await self.ingest_text(text, filename, topic="uploaded-docx")
        except Exception as e:
            logger.error("Failed to parse DOCX %s: %s", filename, e)
            return 0

    async def ingest_csv(self, file_bytes: bytes, filename: str) -> int:
        """Convert CSV rows to text chunks and ingest."""
        try:
            import csv
            text_lines = []
            reader = csv.DictReader(io.StringIO(file_bytes.decode("utf-8", errors="replace")))
            for row in reader:
                text_lines.append(" | ".join(f"{k}: {v}" for k, v in row.items()))
            text = "\n".join(text_lines)
            return await self.ingest_text(text, filename, topic="uploaded-csv")
        except Exception as e:
            logger.error("Failed to parse CSV %s: %s", filename, e)
            return 0

    # ── Document management ────────────────────────────────────────

    def get_documents(self) -> List[dict]:
        """Return all uploaded documents from manifest (excludes built-ins)."""
        return self._read_manifest()

    def delete_document(self, doc_id: str) -> int:
        """Remove a document and its chunks from ChromaDB + manifest. Returns chunks removed."""
        manifest = self._read_manifest()
        entry = next((d for d in manifest if d["id"] == doc_id), None)
        if not entry:
            return 0
        source = entry["filename"]
        chunks_removed = 0

        if self._chroma_available and self._collection is not None:
            try:
                existing = self._collection.get(where={"source": source})
                if existing["ids"]:
                    self._collection.delete(ids=existing["ids"])
                    chunks_removed = len(existing["ids"])
            except Exception as e:
                logger.error("Failed to delete chunks for %s: %s", source, e)
        else:
            before = len(self._documents)
            self._documents = [d for d in self._documents
                               if not d.get("id", "").startswith(source)]
            chunks_removed = before - len(self._documents)

        manifest = [d for d in manifest if d["id"] != doc_id]
        self._write_manifest(manifest)
        self._invalidate_semantic_cache()
        logger.info("Deleted document %s (%d chunks)", source, chunks_removed)
        return chunks_removed

    def get_stats(self) -> dict:
        """Return knowledge base statistics."""
        manifest = self._read_manifest()
        total_chunks = sum(d.get("chunks", 0) for d in manifest)
        builtin_count = len(_BUILTIN_DOCS)
        chroma_count = 0
        if self._chroma_available and self._collection is not None:
            try:
                chroma_count = self._collection.count()
            except Exception:
                pass
        else:
            # Keyword fallback: count in-memory docs (excluding built-ins)
            chroma_count = len([d for d in self._documents if d.get("topic") == "uploaded"
                                 or d.get("topic", "").startswith("uploaded")])
        return {
            "builtin_docs": builtin_count,
            "uploaded_docs": len(manifest),
            "total_chunks_uploaded": total_chunks,
            "total_vectors": chroma_count,
            "backend": "chromadb-persistent" if self._chroma_available else "keyword-fallback",
            "last_updated": manifest[-1]["uploaded_at"] if manifest else None,
        }

    def reseed_builtin(self) -> int:
        """Force-reload all built-in knowledge entries. Returns count reloaded."""
        if not self._chroma_available or self._collection is None:
            self._documents = list(_BUILTIN_DOCS)
            return len(_BUILTIN_DOCS)
        try:
            builtin_ids = [d["id"] for d in _BUILTIN_DOCS]
            try:
                self._collection.delete(ids=builtin_ids)
            except Exception:
                pass
            self._collection.add(
                ids=builtin_ids,
                documents=[d["content"] for d in _BUILTIN_DOCS],
                metadatas=[{"topic": d["topic"], "source": d["id"]} for d in _BUILTIN_DOCS]
            )
            logger.info("Reseeded %d built-in docs", len(_BUILTIN_DOCS))
            self._rebuild_bm25()
            return len(_BUILTIN_DOCS)
        except Exception as e:
            logger.error("Failed to reseed built-in knowledge: %s", e)
            return 0

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 400, overlap: int = 1) -> List[str]:
        """
        Sentence-aware chunking: splits on sentence boundaries, groups sentences
        into chunks of ~chunk_size words, with `overlap` sentences of continuity
        between adjacent chunks.
        """
        # Split on sentence-ending punctuation followed by whitespace, or blank lines
        sentences = re.split(r'(?<=[.!?])\s+|\n{2,}', text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            return []

        chunks: List[str] = []
        current: List[str] = []
        current_len = 0

        for sent in sentences:
            word_count = len(sent.split())
            if current_len + word_count > chunk_size and current:
                chunks.append(" ".join(current))
                # Keep the last `overlap` sentences for semantic continuity
                current = current[-overlap:] if overlap > 0 else []
                current_len = sum(len(s.split()) for s in current)
            current.append(sent)
            current_len += word_count

        if current:
            chunks.append(" ".join(current))

        return chunks

    def _read_manifest(self) -> List[dict]:
        if not os.path.exists(MANIFEST_PATH):
            return []
        try:
            with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _write_manifest(self, manifest: List[dict]) -> None:
        try:
            with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Failed to write manifest: %s", e)

    def _update_manifest(self, filename: str, topic: str, chunks: int) -> None:
        manifest = self._read_manifest()
        # Update existing or add new entry
        existing = next((d for d in manifest if d["filename"] == filename), None)
        if existing:
            existing["chunks"] = chunks
            existing["uploaded_at"] = datetime.now(timezone.utc).isoformat()
            existing["topic"] = topic
        else:
            manifest.append({
                "id": str(uuid.uuid4()),
                "filename": filename,
                "topic": topic,
                "chunks": chunks,
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
            })
        self._write_manifest(manifest)


# Singleton
rag_service = RAGService()
