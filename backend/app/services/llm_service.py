"""
LLM Service — Groq/OpenAI integration with RAG context, prompt protection,
input sanitization, inline citations, SSE streaming and French language support.
"""
import re
import asyncio
import logging
import threading
from typing import AsyncIterator, Optional, List, Tuple

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

# Fast/cheap model used for auxiliary calls (evaluator, query expansion, cluster titles)
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_FAST_MODEL = "llama-3.1-8b-instant"
OPENAI_MODEL = "gpt-4o"
OPENAI_FAST_MODEL = "gpt-4o-mini"


class LLMService:
    def __init__(self):
        self._client = None
        self._available = False
        self._provider = "none"
        # ── Admin-tunable runtime config (admin Settings → "IA & Modèles LLM") ──
        # Overridden live by runtime_settings.apply_section("ai", …). The model
        # selector is deliberately NOT wired: its options (gpt-4-turbo, claude…)
        # don't match the configured provider's model IDs and would break calls.
        self._rt_system_prompt: Optional[str] = None
        self._rt_temperature: float = 0.3
        self._rt_max_tokens: int = 1024
        self._init_client()

    def apply_runtime_config(self, data: dict) -> None:
        """Apply the saved 'ai' settings section to live generation parameters.

        Missing keys revert to the built-in defaults, so passing ``{}`` resets.
        """
        prompt = (data.get("systemPrompt") or "").strip()
        self._rt_system_prompt = prompt or None
        try:
            t = float(data.get("temperature", 0.3))
            self._rt_temperature = min(max(t, 0.0), 2.0)
        except (TypeError, ValueError):
            self._rt_temperature = 0.3
        try:
            mt = int(data.get("maxTokens", 1024))
            self._rt_max_tokens = min(max(mt, 64), 32768)
        except (TypeError, ValueError):
            self._rt_max_tokens = 1024
        logger.info(
            "AI settings applied — temperature=%.2f max_tokens=%d custom_prompt=%s",
            self._rt_temperature, self._rt_max_tokens, self._rt_system_prompt is not None,
        )

    @property
    def _system_prompt(self) -> str:
        return self._rt_system_prompt or SYSTEM_PROMPT

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

    @property
    def available(self) -> bool:
        return self._available

    def sanitize_input(self, text: str) -> str:
        """Remove potential prompt injection attempts."""
        sanitized = text
        for pattern in INJECTION_PATTERNS:
            if re.search(pattern, sanitized, re.IGNORECASE):
                sanitized = re.sub(pattern, "[FILTERED]", sanitized, flags=re.IGNORECASE)
                logger.warning("Prompt injection attempt detected and filtered")
        sanitized = sanitized.replace("\x00", "")
        sanitized = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f]", "", sanitized)
        return sanitized.strip()

    # ── Prompt assembly ───────────────────────────────────────────

    def _build_messages(
        self,
        user_message: str,
        context_docs: Optional[List[str]],
        context_scores: Optional[List[float]],
        context_sources: Optional[List[str]],
        file_context: Optional[str],
        extra_instructions: Optional[str],
        t_low: float,
        t_high: float,
        history: Optional[List[dict]] = None,
    ) -> Tuple[list, str, float]:
        """Shared prompt builder for blocking and streaming generation.

        Confidence-threshold routing on the top RAG score:
          < t_low        → ignore KB context, let LLM answer freely
          [t_low, t_high) → inject KB as supplementary hint
          ≥ t_high       → inject KB with strong instruction to base answer on it
        """
        sanitized = self.sanitize_input(user_message)

        top_score = max(context_scores) if context_scores else 0.0
        if top_score < t_low:
            logger.info("RAG score %.3f < %.2f — skipping KB context, LLM answers freely", top_score, t_low)
            context_docs = None
        elif top_score >= t_high:
            logger.info("RAG score %.3f ≥ %.2f — strong KB match, using KB-first answer", top_score, t_high)
        else:
            logger.info("RAG score %.3f in [%.2f, %.2f) — using KB as hint", top_score, t_low, t_high)

        messages = [{"role": "system", "content": self._system_prompt}]

        if context_docs:
            numbered = []
            for i, doc in enumerate(context_docs, 1):
                source = context_sources[i - 1] if context_sources and i <= len(context_sources) else f"doc-{i}"
                numbered.append(f"[{i}] (source: {source})\n{doc}")
            context_text = "\n\n".join(numbered)
            citation_rule = (
                "\n\nQuand tu utilises une information d'un extrait, cite-la avec [n] "
                "correspondant au numéro de la source (par exemple [1]). N'invente pas de numéros."
            )
            if top_score >= t_high:
                kb_instruction = (
                    "IMPORTANT: La base de connaissances TMA contient une réponse très pertinente "
                    "pour cette question. Base ta réponse PRINCIPALEMENT sur les extraits numérotés suivants:\n\n"
                    f"{context_text}{citation_rule}"
                )
            else:
                kb_instruction = (
                    "Extraits numérotés de la base de connaissances TMA "
                    "(utilise-les comme référence complémentaire):\n"
                    f"{context_text}{citation_rule}"
                )
            messages.append({"role": "system", "content": kb_instruction})

        if file_context:
            messages.append({
                "role": "system",
                "content": f"Contenu du fichier joint:\n{file_context[:3000]}"
            })

        if extra_instructions:
            messages.append({"role": "system", "content": extra_instructions})

        # Conversation memory: prior turns of this session (already truncated by caller)
        for turn in (history or []):
            role = turn.get("role")
            content = (turn.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": sanitized})
        return messages, sanitized, top_score

    # ── Generation ────────────────────────────────────────────────

    async def generate_response(
        self,
        user_message: str,
        context_docs: Optional[List[str]] = None,
        context_scores: Optional[List[float]] = None,
        context_sources: Optional[List[str]] = None,
        file_context: Optional[str] = None,
        extra_instructions: Optional[str] = None,
        timeout: float = 45.0,
        t_low: float = 0.35,
        t_high: float = 0.75,
        history: Optional[List[dict]] = None,
    ) -> str:
        """Generate LLM response with RAG context, inline citations and timeout."""
        messages, sanitized, _top = self._build_messages(
            user_message, context_docs, context_scores, context_sources,
            file_context, extra_instructions, t_low, t_high, history
        )

        if not self._available or not self._client:
            docs = context_docs if _top >= t_low else None
            return self._fallback_response(sanitized, docs, file_context)

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self._call_completion, messages),
                timeout=timeout
            )
            return response
        except asyncio.TimeoutError:
            logger.error("LLM response timed out after %.0fs", timeout)
            self._record_error("timeout")
            return ("⏱️ Le service est temporairement indisponible (timeout 45s). "
                    "Veuillez réessayer dans quelques instants ou reformuler votre demande.")
        except Exception as e:
            logger.error(f"LLM error: {e}")
            self._record_error("api_error")
            return f"⚠️ Erreur du service IA ({self._provider}): {str(e)}"

    def _record_error(self, kind: str) -> None:
        try:
            from app.core.metrics import LLM_ERRORS
            LLM_ERRORS.labels(provider=self._provider, kind=kind).inc()
        except Exception:
            pass

    async def generate_response_stream(
        self,
        user_message: str,
        context_docs: Optional[List[str]] = None,
        context_scores: Optional[List[float]] = None,
        context_sources: Optional[List[str]] = None,
        file_context: Optional[str] = None,
        extra_instructions: Optional[str] = None,
        t_low: float = 0.35,
        t_high: float = 0.75,
        history: Optional[List[dict]] = None,
    ) -> AsyncIterator[str]:
        """Stream the LLM response token by token (text deltas)."""
        messages, sanitized, _top = self._build_messages(
            user_message, context_docs, context_scores, context_sources,
            file_context, extra_instructions, t_low, t_high, history
        )

        if not self._available or not self._client:
            docs = context_docs if _top >= t_low else None
            yield self._fallback_response(sanitized, docs, file_context)
            return

        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        _DONE = object()

        def worker():
            try:
                model = GROQ_MODEL if self._provider == "groq" else OPENAI_MODEL
                stream = self._client.chat.completions.create(
                    model=model, messages=messages,
                    max_tokens=self._rt_max_tokens, temperature=self._rt_temperature, stream=True
                )
                for chunk in stream:
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        loop.call_soon_threadsafe(queue.put_nowait, delta)
                loop.call_soon_threadsafe(queue.put_nowait, _DONE)
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, e)

        threading.Thread(target=worker, daemon=True).start()

        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=60.0)
            except asyncio.TimeoutError:
                logger.error("LLM stream stalled (60s without token)")
                self._record_error("timeout")
                yield "\n\n⏱️ Le flux de réponse a été interrompu (timeout)."
                return
            if item is _DONE:
                return
            if isinstance(item, Exception):
                logger.error("LLM stream error: %s", item)
                self._record_error("api_error")
                yield f"\n\n⚠️ Erreur du service IA ({self._provider}): {item}"
                return
            yield item

    def _call_completion(self, messages: list) -> str:
        if self._client is None:
            raise RuntimeError("LLM client not initialized")
        model = GROQ_MODEL if self._provider == "groq" else OPENAI_MODEL
        completion = self._client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=self._rt_max_tokens,
            temperature=self._rt_temperature
        )
        return completion.choices[0].message.content

    # ── Raw completion passthrough (tool-calling agent, aux tasks) ──

    async def chat_completion(
        self,
        messages: list,
        tools: Optional[list] = None,
        fast: bool = False,
        max_tokens: int = 1024,
        temperature: float = 0.3,
        timeout: float = 30.0,
    ):
        """Raw chat.completions call reusing provider selection. Returns the SDK
        message object (with .content / .tool_calls). Raises on error/timeout."""
        if not self._available or not self._client:
            raise RuntimeError("LLM client not available")

        def call():
            if fast:
                model = GROQ_FAST_MODEL if self._provider == "groq" else OPENAI_FAST_MODEL
            else:
                model = GROQ_MODEL if self._provider == "groq" else OPENAI_MODEL
            kwargs = dict(model=model, messages=messages, max_tokens=max_tokens, temperature=temperature)
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            completion = self._client.chat.completions.create(**kwargs)
            return completion.choices[0].message

        return await asyncio.wait_for(asyncio.to_thread(call), timeout=timeout)

    # ── Groundedness evaluator ────────────────────────────────────

    async def evaluate_groundedness(
        self, answer: str, context_docs: List[str]
    ) -> Optional[bool]:
        """Cheap second-pass check: is the answer supported by the KB excerpts?
        Returns True/False, or None when the check could not run (never blocks)."""
        if not self._available or not self._client or not context_docs:
            return None
        excerpts = "\n\n".join(d[:1200] for d in context_docs[:3])
        messages = [
            {"role": "system", "content": (
                "Tu es un vérificateur factuel. On te donne des extraits d'une base de "
                "connaissances et une réponse d'assistant. Réponds STRICTEMENT par OUI si la "
                "réponse est globalement soutenue par les extraits, ou NON sinon. Un seul mot."
            )},
            {"role": "user", "content": f"EXTRAITS:\n{excerpts}\n\nRÉPONSE:\n{answer[:2000]}\n\nSoutenue par les extraits ?"},
        ]
        try:
            msg = await self.chat_completion(messages, fast=True, max_tokens=5, temperature=0.0, timeout=8.0)
            verdict = (msg.content or "").strip().upper()
            if verdict.startswith("OUI"):
                return True
            if verdict.startswith("NON"):
                return False
            return None
        except Exception as e:
            logger.warning("Groundedness evaluation failed: %s", e)
            return None

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
