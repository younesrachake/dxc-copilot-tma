"""
LLM Service — OpenAI GPT-4o integration with RAG context, prompt protection,
input sanitization, and French language support.
"""
import re
import asyncio
import logging
from typing import Optional, List

from app.core.config import OPENAI_API_KEY, GROQ_API_KEY

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es DXC Copilot, un assistant IA spécialisé en Tierce Maintenance Applicative (TMA).

Ton rôle:
- Aider les techniciens et ingénieurs à résoudre les incidents applicatifs
- Fournir des procédures de maintenance et de dépannage
- Analyser les logs et diagnostiquer les problèmes
- Guider les déploiements et les mises à jour
- Créer des tickets Jira pour le suivi des incidents

Règles:
- Réponds TOUJOURS en français
- Sois concis et professionnel
- Structure tes réponses avec des étapes numérotées quand pertinent
- Si tu n'es pas sûr, indique-le clairement
- Ne divulgue jamais d'informations sensibles (mots de passe, clés API, etc.)
- Base tes réponses sur le contexte fourni quand disponible
"""

INJECTION_PATTERNS = [
    r"ignore\s+(previous|all|above)\s+(instructions?|prompts?)",
    r"you\s+are\s+now\s+",
    r"forget\s+(everything|all|your)\s+",
    r"new\s+instructions?\s*:",
    r"system\s*:\s*",
    r"<\|.*\|>",
    r"\[INST\]",
    r"override\s+system",
    r"jailbreak",
    r"DAN\s+mode",
]


class LLMService:
    def __init__(self):
        self._client = None
        self._available = False
        self._provider = "none"
        self._init_client()

    def _init_client(self):
        # Try Groq first, then fall back to OpenAI
        logger.info("Initializing LLM client. GROQ_API_KEY set: %s", bool(GROQ_API_KEY))
        if GROQ_API_KEY and GROQ_API_KEY != "gq-placeholder-set-your-real-key":
            try:
                from groq import Groq
                self._client = Groq(api_key=GROQ_API_KEY)
                self._provider = "groq"
                self._available = True
                logger.info("Groq LLM client initialized")
                return
            except ImportError as e:
                logger.warning("groq package not installed: %s", e)
            except Exception as e:
                logger.error("Failed to initialize Groq client: %s", e)

        if OPENAI_API_KEY and OPENAI_API_KEY != "sk-placeholder-set-your-real-key":
            try:
                import openai
                self._client = openai.OpenAI(api_key=OPENAI_API_KEY)
                self._provider = "openai"
                self._available = True
                logger.info("OpenAI LLM client initialized")
            except ImportError:
                logger.warning("openai package not installed")
        else:
            logger.warning("No Groq or OpenAI API key configured — LLM in simulation mode")

    def sanitize_input(self, text: str) -> str:
        """Remove potential prompt injection attempts."""
        sanitized = text
        for pattern in INJECTION_PATTERNS:
            if re.search(pattern, sanitized, re.IGNORECASE):
                sanitized = re.sub(pattern, "[FILTERED]", sanitized, flags=re.IGNORECASE)
                logger.warning(f"Prompt injection attempt detected and filtered")
        sanitized = sanitized.replace("\x00", "")
        sanitized = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f]", "", sanitized)
        return sanitized.strip()

    async def generate_response(
        self,
        user_message: str,
        context_docs: Optional[List[str]] = None,
        context_scores: Optional[List[float]] = None,
        file_context: Optional[str] = None,
        timeout: float = 45.0
    ) -> str:
        """Generate LLM response with RAG context and timeout.

        context_scores: similarity scores (0-1) from RAG search.
          < 0.35  → ignore KB context, let LLM answer freely
          0.35-0.75 → inject KB as supplementary hint
          ≥ 0.75  → inject KB with strong instruction to base answer on it
        """
        sanitized = self.sanitize_input(user_message)

        # Confidence-threshold routing
        top_score = max(context_scores) if context_scores else 0.0
        if top_score < 0.35:
            logger.info("RAG score %.3f < 0.35 — skipping KB context, Groq answers freely", top_score)
            context_docs = None
        elif top_score >= 0.75:
            logger.info("RAG score %.3f ≥ 0.75 — strong KB match, using KB-first answer", top_score)
        else:
            logger.info("RAG score %.3f in [0.35, 0.75) — using KB as hint", top_score)

        if not self._available or not self._client:
            return self._fallback_response(sanitized, context_docs, file_context)  # noqa: after routing

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        if context_docs:
            context_text = "\n\n".join(context_docs)
            if top_score >= 0.75:
                kb_instruction = (
                    "IMPORTANT: La base de connaissances TMA contient une réponse très pertinente "
                    "pour cette question. Base ta réponse PRINCIPALEMENT sur le contexte suivant:\n\n"
                    f"{context_text}"
                )
            else:
                kb_instruction = (
                    "Contexte de la base de connaissances TMA (utilise-le comme référence complémentaire):\n"
                    f"{context_text}"
                )
            messages.append({
                "role": "system",
                "content": kb_instruction
            })

        if file_context:
            messages.append({
                "role": "system",
                "content": f"Contenu du fichier joint:\n{file_context[:3000]}"
            })

        messages.append({"role": "user", "content": sanitized})

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self._call_openai, messages),
                timeout=timeout
            )
            return response
        except asyncio.TimeoutError:
            logger.error("LLM response timed out after 45s")
            return ("⏱️ Le service est temporairement indisponible (timeout 45s). "
                    "Veuillez réessayer dans quelques instants ou reformuler votre demande.")
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return f"⚠️ Erreur du service IA ({self._provider}): {str(e)}"

    def _call_openai(self, messages: list) -> str:
        if self._client is None:
            raise RuntimeError("LLM client not initialized")
        
        if self._provider == "groq":
            completion = self._client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                max_tokens=1024,
                temperature=0.3
            )
        else:  # openai
            completion = self._client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                max_tokens=1024,
                temperature=0.3
            )
        return completion.choices[0].message.content

    def _fallback_response(
        self,
        user_message: str,
        context_docs: Optional[List[str]] = None,
        file_context: Optional[str] = None
    ) -> str:
        """Generate a structured fallback response without OpenAI."""
        parts = [f"Je comprends votre demande concernant : \"{user_message[:100]}\"."]

        if context_docs:
            parts.append("\n📚 **Informations pertinentes de la base de connaissances:**")
            for i, doc in enumerate(context_docs[:2], 1):
                parts.append(f"\n{i}. {doc[:200]}...")

        if file_context:
            parts.append(f"\n📎 **Fichier analysé:** {file_context[:150]}...")

        if not context_docs and not file_context:
            parts.append("\n💡 Suggestion: Essayez de préciser votre demande ou joindre un fichier pour un diagnostic plus précis.")

        return "\n".join(parts)


# Singleton
llm_service = LLMService()
