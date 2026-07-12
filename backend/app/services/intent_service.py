"""
Intent Service — French intent classification via embedding similarity (kNN).

Classifies user messages into {incident_report, jira_request, question, smalltalk}
by comparing the message embedding against curated example utterances with the
shared multilingual model. No fine-tuning, ~1 ms per message once loaded, and
new examples can be added by editing the lists below.

Falls back to (None, 0.0) when local embeddings are unavailable — callers then
keep the legacy keyword detection.
"""
import asyncio
import logging
import threading
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

INTENT_INCIDENT = "incident_report"
INTENT_JIRA = "jira_request"
INTENT_QUESTION = "question"
INTENT_SMALLTALK = "smalltalk"

# Below this best-intent similarity, default to "question"
MIN_CONFIDENCE = 0.45

INTENT_EXAMPLES = {
    INTENT_INCIDENT: [
        "Le service API Gateway est en panne depuis ce matin",
        "On a une erreur 502 sur la prod",
        "Le serveur ne répond plus, timeout sur toutes les requêtes",
        "La base de données PostgreSQL est inaccessible",
        "Les utilisateurs signalent des lenteurs importantes sur l'application",
        "Le conteneur redémarre en boucle en production",
        "Il y a un crash du service de notification",
        "Exception non gérée dans les logs du backend",
        "Le cache Redis renvoie des données corrompues",
        "Incident critique : le login ne fonctionne plus",
        "On observe une fuite mémoire sur le worker",
        "Le certificat SSL a expiré et le site est bloqué",
        "Panne totale du load balancer",
        "Le déploiement a échoué et le service est indisponible",
        "Erreur 500 intermittente sur l'API de paiement",
        "Le batch de nuit ne s'est pas exécuté, la file est saturée",
        "Dysfonctionnement du module d'authentification depuis la mise à jour",
        "La prod est down, les clients ne peuvent plus se connecter",
    ],
    INTENT_JIRA: [
        "Crée un ticket Jira pour cet incident",
        "Peux-tu ouvrir un ticket pour ce problème",
        "Il faut créer un bug dans Jira",
        "Ouvre un ticket ServiceNow pour le suivi",
        "Je veux déclarer ce problème dans Jira",
        "Génère un ticket avec priorité haute",
        "Créer une issue pour l'équipe de dev",
        "Fais un ticket jira urgent pour la panne redis",
        "Enregistre cet incident dans l'outil de ticketing",
        "On doit tracer ça dans Jira, tu peux préparer le ticket",
        "Ouvre-moi un ticket SMAX s'il te plaît",
        "Créer un ticket d'incident pour la prod",
        "Peux-tu remplir un ticket avec le contexte de notre discussion",
        "Déclare une anomalie dans Jira",
        "Nouveau ticket : erreur 502 récurrente",
    ],
    INTENT_QUESTION: [
        "Comment redémarrer un service TMA proprement",
        "Quelle est la procédure de déploiement en production",
        "Comment configurer les alertes Prometheus",
        "Quelles sont les bonnes pratiques de sécurité pour les API",
        "Comment diagnostiquer une requête SQL lente",
        "Explique-moi le pattern circuit breaker",
        "Quelle est la différence entre un rollback et un canary deploy",
        "Comment vérifier l'espace disque sur le serveur",
        "Que veut dire RG2 dans la gestion des incidents",
        "Comment analyser les logs d'un pod Kubernetes",
        "Quels sont les seuils d'alerte recommandés pour le CPU",
        "Comment renouveler un certificat Let's Encrypt",
        "Peux-tu m'expliquer la procédure d'escalade vers le support N2",
        "Comment fonctionne l'autoscaling de l'API Gateway",
        "Quelles étapes pour une migration de schéma sans downtime",
        "Comment purger le cache Redis en sécurité",
    ],
    INTENT_SMALLTALK: [
        "Bonjour",
        "Salut, comment ça va",
        "Merci beaucoup",
        "Merci pour ton aide",
        "Bonne journée",
        "Au revoir",
        "Parfait, super",
        "Ok merci c'est noté",
        "Hello",
        "Coucou",
        "Très bien merci",
        "À bientôt",
        "Top, merci !",
        "D'accord",
        "Qui es-tu",
        "Que sais-tu faire",
    ],
}


class IntentService:
    def __init__(self):
        self._lock = threading.Lock()
        self._index = None      # list[(intent, np.ndarray examples)]
        self._failed = False

    def _build_index(self):
        if self._index is not None or self._failed:
            return self._index
        with self._lock:
            if self._index is not None or self._failed:
                return self._index
            try:
                from app.services.embedding_service import embedding_service
                if not embedding_service.available:
                    self._failed = True
                    return None
                index = []
                for intent, examples in INTENT_EXAMPLES.items():
                    vectors = embedding_service.encode_sync(examples, normalize=True)
                    index.append((intent, vectors))
                self._index = index
                logger.info(
                    "Intent index built: %d intents, %d examples",
                    len(index), sum(len(v) for _, v in index)
                )
            except Exception as e:
                self._failed = True
                logger.warning("Intent classifier unavailable: %s", e)
        return self._index

    def classify_sync(self, message: str) -> Tuple[Optional[str], float]:
        """Returns (intent, confidence) or (None, 0.0) when unavailable."""
        index = self._build_index()
        if index is None or not message.strip():
            return None, 0.0
        try:
            from app.services.embedding_service import embedding_service
            query_vec = embedding_service.encode_sync([message[:500]], normalize=True)[0]
            best_intent, best_score = INTENT_QUESTION, 0.0
            for intent, vectors in index:
                sims = vectors @ query_vec  # normalized → dot product = cosine
                top = sorted(sims, reverse=True)[:3]
                score = float(sum(top) / len(top))
                if score > best_score:
                    best_intent, best_score = intent, score
            if best_score < MIN_CONFIDENCE:
                return INTENT_QUESTION, best_score
            return best_intent, best_score
        except Exception as e:
            logger.warning("Intent classification failed: %s", e)
            return None, 0.0

    async def classify(self, message: str) -> Tuple[Optional[str], float]:
        return await asyncio.to_thread(self.classify_sync, message)


# Singleton
intent_service = IntentService()
