"""
Chat Agent Service — bounded tool-calling loop for incident diagnosis and Jira drafting.

Instead of a single-shot RAG+LLM call, the model reasons in a loop with
read-only tools (plus a Jira *draft* — creation stays a user click in the UI):
  - search_kb            → hybrid+reranked knowledge base search
  - get_incident_history → recurring incident counters (RG2 table)
  - get_session_context  → recent messages of the current conversation
  - draft_jira_ticket    → returns a pre-filled ticket draft to the UI popup

Used only for incident/jira intents (routed from chat.py) — plain questions keep
the cheaper single-shot path. Both Groq and OpenAI SDKs accept the same tools schema.
"""
import json
import logging
import re
import time
from types import SimpleNamespace
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import registry
from app.models.db import Incident, Message
from app.services.llm_service import llm_service, SYSTEM_PROMPT
from app.services.rag_service import rag_service

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5
TIME_BUDGET_SECONDS = 60.0
MAX_TOOL_OUTPUT_CHARS = 2000

# Human-readable French labels for the live reasoning timeline
TOOL_LABELS = {
    "search_kb": "Recherche dans la base de connaissances",
    "get_incident_history": "Consultation de l'historique des incidents",
    "get_session_context": "Relecture de la conversation",
    "draft_jira_ticket": "Préparation du brouillon Jira",
}

AGENT_INSTRUCTIONS = (
    "\n\nTu disposes d'outils pour enquêter avant de répondre :\n"
    "- search_kb : cherche dans la base de connaissances TMA (procédures, incidents connus).\n"
    "- get_incident_history : consulte l'historique des incidents récurrents (RG2).\n"
    "- get_session_context : relit les derniers messages de la conversation.\n"
    "- draft_jira_ticket : prépare un BROUILLON de ticket Jira. Un formulaire pré-rempli "
    "s'affiche alors dans l'interface ; l'utilisateur le vérifie et crée le ticket en un clic. "
    "Ne dis jamais que tu ne peux pas créer de ticket et ne rédige pas d'exemple de ticket "
    "dans ta réponse : utilise l'outil.\n\n"
    "Utilise les outils nécessaires (pas plus), puis donne une réponse finale concise en français. "
    "Quand tu utilises une information issue de search_kb, cite la source entre crochets si pertinent."
)

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "search_kb",
            "description": "Recherche hybride dans la base de connaissances TMA (procédures, incidents connus, guides). Retourne les extraits les plus pertinents avec leurs sources et scores.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Requête de recherche en français"},
                    "n_results": {"type": "integer", "description": "Nombre d'extraits (défaut 3, max 5)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_incident_history",
            "description": "Historique des incidents récurrents (compteurs RG2) : type, nombre d'occurrences, dernière occurrence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "incident_type": {"type": "string", "description": "Filtrer sur un type précis (optionnel)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_session_context",
            "description": "Derniers messages de la conversation en cours, pour retrouver le contexte.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Nombre de messages (défaut 6, max 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_jira_ticket",
            "description": "Prépare un brouillon de ticket Jira affiché à l'utilisateur dans un formulaire pré-rempli. N'appelle cet outil qu'une seule fois, avec un résumé et une description complets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Résumé court du ticket (max 80 caractères)"},
                    "description": {"type": "string", "description": "Description détaillée : contexte, impact, étapes"},
                    "priority": {"type": "string", "enum": ["Critique", "Haute", "Moyenne", "Basse"]},
                },
                "required": ["summary", "description"],
            },
        },
    },
]


class ChatAgentService:

    async def run(
        self,
        message: str,
        session_id: str,
        db: AsyncSession,
        file_context: Optional[str] = None,
        kb_on: bool = True,
        on_step=None,
    ) -> dict:
        """Run the bounded agent loop. Returns
        {reply, jira_ticket, sources, scores, docs_by_source, tool_trace}.

        on_step: optional sync callable({"tool", "label"}) fired before each
        tool execution — feeds the live reasoning timeline in the UI."""
        sanitized = llm_service.sanitize_input(message)

        # Auto-load tools from enabled integration connectors (Jira, Slack, …)
        try:
            conn_schemas, conn_index = await registry.agent_tools(db)
        except Exception as e:
            logger.warning("Connector tools unavailable: %s", e)
            conn_schemas, conn_index = [], {}

        state = {
            "jira_ticket": None,
            "sources": [],
            "scores": [],
            "docs_by_source": {},
            "tool_trace": [],
            "kb_on": kb_on,
            "session_id": session_id,
            "on_step": on_step,
            "conn_index": conn_index,
            "pending_actions": [],
        }

        instructions = AGENT_INSTRUCTIONS
        if conn_schemas:
            instructions += (
                "\n\nDes intégrations externes sont connectées (Jira, ServiceNow, Slack, etc.). "
                "Tu peux appeler leurs outils de LECTURE librement (recherche, statut). "
                "Pour une action d'ÉCRITURE (créer un ticket, publier un message, déclencher une "
                "alerte), l'utilisateur devra confirmer via une carte affichée dans l'interface : "
                "appelle simplement l'outil, puis confirme-lui en une phrase que l'action est prête "
                "à être validée."
            )
        tools_for_llm = TOOLS_SCHEMA + conn_schemas
        known_names = {t["function"]["name"] for t in tools_for_llm}

        messages = [{"role": "system", "content": SYSTEM_PROMPT + instructions}]
        if file_context:
            messages.append({"role": "system", "content": f"Contenu du fichier joint:\n{file_context[:3000]}"})
        messages.append({"role": "user", "content": sanitized})

        deadline = time.monotonic() + TIME_BUDGET_SECONDS
        reply = None

        for iteration in range(MAX_ITERATIONS):
            remaining = deadline - time.monotonic()
            if remaining <= 5:
                break
            try:
                msg = await llm_service.chat_completion(
                    messages, tools=tools_for_llm, timeout=min(remaining, 45.0)
                )
            except Exception as e:
                # llama tool-calling flakiness: Groq rejects malformed tool syntax
                # with a 400 whose payload contains the intended call — salvage it.
                msg = self._salvage_failed_tool_call(e, known_names)
                if msg is None:
                    logger.error("Agent loop LLM call failed (iteration %d): %s", iteration, e)
                    break
                logger.info("Agent: salvaged malformed tool call (%s)",
                            msg.tool_calls[0].function.name)

            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                reply = msg.content or ""
                break

            # Append assistant turn (serialized for both SDKs), then tool results
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ],
            })
            for tc in tool_calls:
                result = await self._execute_tool(tc, db, state)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result[:MAX_TOOL_OUTPUT_CHARS],
                })

        if reply is None:
            # Loop/budget exhausted or errored: force a final answer without tools
            messages.append({
                "role": "system",
                "content": "Donne maintenant ta réponse finale à l'utilisateur, sans utiliser d'outil.",
            })
            try:
                msg = await llm_service.chat_completion(messages, timeout=30.0)
                reply = msg.content or ""
            except Exception as e:
                logger.error("Agent final answer failed: %s", e)
                reply = (
                    "⚠️ Je n'ai pas pu finaliser l'analyse. "
                    "Veuillez réessayer ou reformuler votre demande."
                )

        logger.info(
            "Agent run: %d tool call(s) [%s]",
            len(state["tool_trace"]),
            ", ".join(t["tool"] for t in state["tool_trace"]),
        )
        return {
            "reply": reply,
            "jira_ticket": state["jira_ticket"],
            "sources": state["sources"],
            "scores": state["scores"],
            "docs_by_source": state["docs_by_source"],
            "tool_trace": state["tool_trace"],
            "pending_actions": state["pending_actions"],
        }

    @staticmethod
    def _salvage_failed_tool_call(error: Exception, known_names: set):
        """Extract the intended tool call from a Groq `tool_use_failed` error.

        llama sometimes emits `<function=name>{args}</function>` instead of the
        tool-call JSON; the API rejects it but returns the raw generation."""
        text = str(error)
        if "tool_use_failed" not in text and "failed_generation" not in text:
            return None
        match = re.search(r"<function=(\w+)>\s*(\{.*?\})\s*</function>", text, re.DOTALL)
        if not match:
            return None
        name, raw_args = match.group(1), match.group(2)
        try:
            json.loads(raw_args.replace("\\'", "'"))
            raw_args = raw_args.replace("\\'", "'")
        except json.JSONDecodeError:
            try:
                json.loads(raw_args)
            except json.JSONDecodeError:
                return None
        if name not in known_names:
            return None
        return SimpleNamespace(
            content="",
            tool_calls=[SimpleNamespace(
                id=f"salvaged-{int(time.monotonic() * 1000)}",
                function=SimpleNamespace(name=name, arguments=raw_args),
            )],
        )

    # ── Tool execution ────────────────────────────────────────────

    async def _execute_tool(self, tool_call, db: AsyncSession, state: dict) -> str:
        name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments or "{}")
            if not isinstance(args, dict):
                raise ValueError("arguments is not an object")
        except (json.JSONDecodeError, ValueError) as e:
            # Malformed args happen with llama tool calling — let the model retry
            return f"Erreur: arguments invalides pour {name} ({e}). Réessaie avec un JSON valide."

        state["tool_trace"].append({"tool": name, "args": args})
        if state.get("on_step"):
            try:
                state["on_step"]({"tool": name, "label": TOOL_LABELS.get(name, name)})
            except Exception:
                pass
        try:
            if name == "search_kb":
                return await self._tool_search_kb(args, state)
            if name == "get_incident_history":
                return await self._tool_incident_history(args, db)
            if name == "get_session_context":
                return await self._tool_session_context(args, db, state["session_id"])
            if name == "draft_jira_ticket":
                return self._tool_draft_jira(args, state)
            # Integration connector tools (auto-loaded when enabled)
            if name in state.get("conn_index", {}):
                return await self._tool_connector(name, args, state)
            return f"Erreur: outil inconnu '{name}'."
        except Exception as e:
            logger.warning("Tool %s failed: %s", name, e)
            return f"Erreur lors de l'exécution de {name}: {e}"

    async def _tool_connector(self, name: str, args: dict, state: dict) -> str:
        """Read tools run inline; write tools are gated behind a confirmation card."""
        connector, tool, cfg = state["conn_index"][name]
        if tool.kind == "read":
            result = await tool.handler(cfg, args)
            return json.dumps(result, ensure_ascii=False)[:MAX_TOOL_OUTPUT_CHARS]
        # write: propose a confirmation card instead of executing
        summary = tool.summarize(args) if tool.summarize else f"Action {name}"
        state["pending_actions"].append({
            "connector": connector.key,
            "connector_name": connector.name,
            "icon": connector.icon,
            "tool": name,
            "args": args,
            "summary": summary,
        })
        return (
            f"Une carte de confirmation a été préparée pour : {summary}. "
            "L'utilisateur doit la valider dans l'interface. Confirme-lui que l'action est prête."
        )

    async def _tool_search_kb(self, args: dict, state: dict) -> str:
        if not state["kb_on"]:
            return "La base de connaissances est désactivée."
        query = str(args.get("query", "")).strip()
        if not query:
            return "Erreur: requête vide."
        n = min(int(args.get("n_results", 3) or 3), 5)
        docs, scores, sources = await rag_service.search(query, n_results=n)
        if not docs:
            return "Aucun résultat dans la base de connaissances."
        # Track KB usage for response attribution (dedupe, keep best score)
        for doc_text, doc_src, doc_score in zip(docs, sources, scores):
            if doc_src not in state["sources"]:
                state["sources"].append(doc_src)
                state["scores"].append(doc_score)
                state["docs_by_source"][doc_src] = doc_text
        lines = [
            f"[{src}] (score {score:.2f}) {doc[:500]}"
            for doc, score, src in zip(docs, scores, sources)
        ]
        return "\n\n".join(lines)

    async def _tool_incident_history(self, args: dict, db: AsyncSession) -> str:
        stmt = select(Incident).order_by(Incident.count.desc()).limit(10)
        incident_type = args.get("incident_type")
        if incident_type:
            stmt = select(Incident).where(
                Incident.incident_type == str(incident_type).lower().strip()
            )
        incidents = (await db.execute(stmt)).scalars().all()
        if not incidents:
            return "Aucun incident enregistré."
        return "\n".join(
            f"- {i.incident_type}: {i.count} occurrence(s), dernière: {i.last_seen}"
            for i in incidents
        )

    async def _tool_session_context(self, args: dict, db: AsyncSession, session_id: str) -> str:
        limit = min(int(args.get("limit", 6) or 6), 10)
        recent = (await db.execute(
            select(Message).where(Message.session_id == session_id)
            .order_by(Message.created_at.desc()).limit(limit)
        )).scalars().all()
        if not recent:
            return "Aucun message précédent dans cette conversation."
        lines = []
        for m in reversed(recent):
            role = "Utilisateur" if m.sender == "user" else "Copilot"
            lines.append(f"[{role}] {str(m.text)[:200]}")
        return "\n".join(lines)

    def _tool_draft_jira(self, args: dict, state: dict) -> str:
        summary = str(args.get("summary", "")).strip()[:80]
        description = str(args.get("description", "")).strip()
        priority = args.get("priority")
        if priority not in ("Critique", "Haute", "Moyenne", "Basse"):
            priority = "Moyenne"
        if not summary or not description:
            return "Erreur: summary et description sont requis."
        state["jira_ticket"] = {
            "summary": summary,
            "description": description,
            "type": "Incident",
            "priority": priority,
            "project": "TMA",
            "assignee": "Équipe TMA",
        }
        return (
            "Brouillon de ticket créé et affiché à l'utilisateur dans le formulaire. "
            "Confirme-lui en 2-3 phrases qu'il peut le vérifier puis cliquer sur "
            "« Créer un ticket Jira »."
        )


# Singleton
chat_agent_service = ChatAgentService()
