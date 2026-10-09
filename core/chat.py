"""
core.chat: Unified conversational chat orchestration layer for Memory-OS.

Selects between:
1. Conversational LLM mode (greetings, casual conversation, general questions, follow-ups).
2. Knowledge-grounded RAG mode (queries about user code, repositories, emails, workspace documents).
3. Graceful offline fallback when LLM is unavailable.

Preserves transient multi-turn conversation memory within the active session without persisting
unwanted data to disk or vector/graph databases.
"""

import os
import re
import logging
from enum import Enum
from typing import Iterator, Optional, Callable, Dict, Any, List

from core.llm import (
    query_llm_with_retry,
    stream_llm_with_retry,
    run_hybrid_rag,
    run_hybrid_rag_stream,
)
from core.context_builder import ContextBuilder

try:
    from infrastructure.config import load_config
    load_config()
except Exception:
    pass

logger = logging.getLogger("chat_orchestrator")


class ChatIntent(str, Enum):
    GREETING = "greeting"
    CASUAL = "casual"
    FOLLOW_UP = "follow_up"
    PERSONAL_KNOWLEDGE = "personal_knowledge"
    GENERAL = "general"


class ConversationSession:
    """Manages transient in-memory conversation history for a chat session.

    Strictly stored in memory per session. Never written to permanent databases
    to ensure user privacy, security, and workspace isolation.
    """

    def __init__(self, max_turns: int = 10):
        self.max_turns = max_turns
        self.turns: List[Dict[str, Any]] = []

    def add_user_message(self, message: str) -> None:
        self.turns.append({
            "role": "user",
            "content": message
        })
        self._trim()

    def add_assistant_message(
        self,
        content: str,
        mode: str = "conversational",
        sources: Optional[List[str]] = None,
        repositories: Optional[List[str]] = None,
        confidence: float = 1.0
    ) -> None:
        self.turns.append({
            "role": "assistant",
            "content": content,
            "mode": mode,
            "sources": sources or [],
            "repositories": repositories or [],
            "confidence": confidence
        })
        self._trim()

    def _trim(self) -> None:
        # Keep at most max_turns * 2 individual messages (user + assistant)
        max_messages = self.max_turns * 2
        if len(self.turns) > max_messages:
            self.turns = self.turns[-max_messages:]

    def get_history_messages(self) -> List[Dict[str, str]]:
        """Returns standard chat format messages: [{'role': role, 'content': content}, ...]."""
        return [{"role": t["role"], "content": t["content"]} for t in self.turns]

    def get_last_turn(self) -> Optional[Dict[str, Any]]:
        return self.turns[-1] if self.turns else None

    def get_last_assistant_turn(self) -> Optional[Dict[str, Any]]:
        for turn in reversed(self.turns):
            if turn["role"] == "assistant":
                return turn
        return None

    def has_history(self) -> bool:
        return len(self.turns) > 0

    def clear(self) -> None:
        self.turns.clear()


# Fallback responses used when LLM API is unavailable / offline
FALLBACK_GREETING = "Hello! I'm Memory-OS, your personal knowledge assistant. How can I help you today?"
FALLBACK_CASUAL_HOW_ARE_YOU = "I'm doing well, thank you! I'm Memory-OS, ready to help you navigate and query your personal knowledge, repositories, and documents."
FALLBACK_CASUAL_THANKS = "You're very welcome! Let me know if there's anything else you need."
FALLBACK_CASUAL_GENERAL = "I'm Memory-OS, your grounded personal knowledge assistant. Ask me anything about your connected repositories, documentation, or code."


def get_fallback_conversational_response(intent: ChatIntent, query: str) -> str:
    """Generate an offline fallback response for greetings and casual chit-chat."""
    q_lower = query.lower()
    if intent == ChatIntent.GREETING:
        return FALLBACK_GREETING
    if "how are you" in q_lower or "how's it going" in q_lower:
        return FALLBACK_CASUAL_HOW_ARE_YOU
    if "thank" in q_lower or "thx" in q_lower:
        return FALLBACK_CASUAL_THANKS
    return FALLBACK_CASUAL_GENERAL


SYSTEM_CONVERSATIONAL_PROMPT = (
    "You are Memory-OS, a friendly, intelligent personal knowledge assistant. "
    "Respond to greetings, pleasantries, and conversational inquiries warmly, naturally, and concisely. "
    "If asked who you are or what you do, explain that you are Memory-OS, an AI system that helps search, "
    "understand, and synthesize personal knowledge across repositories, documents, and emails."
)

SYSTEM_GENERAL_PROMPT = (
    "You are Memory-OS, a helpful, highly knowledgeable AI assistant. "
    "Answer the user's question clearly, accurately, and conversationally. "
    "Since this is a general question not specific to personal workspace files, provide a direct and comprehensive response."
)

SYSTEM_FOLLOW_UP_PROMPT = (
    "You are Memory-OS, a helpful personal knowledge assistant. "
    "The user is asking a follow-up question referencing the preceding conversation turns. "
    "Answer the follow-up question directly using the conversation context. "
    "If asked to simplify ('explain that more simply', 'make it simpler'), explain the previous concept "
    "in clear, plain, accessible terms without losing the core meaning."
)


def _check_db_for_repo(query_lower: str) -> Optional[str]:
    """Helper to detect if query mentions an indexed repository."""
    try:
        from core.vector_store import detect_repo_in_query
        repo = detect_repo_in_query(query_lower)
        if repo:
            return repo
    except Exception:
        pass

    try:
        from storage.db import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM repos")
        for row in cursor.fetchall():
            rname = row[0]
            if rname and rname.lower() in query_lower:
                conn.close()
                return rname
        conn.close()
    except Exception:
        pass

    return None


def classify_chat_intent(query: str, session: Optional[ConversationSession] = None) -> tuple[ChatIntent, Dict[str, Any]]:
    """Classify user intent into Greeting, Casual, Follow-Up, Personal Knowledge, or General Question.

    Returns:
        (ChatIntent, diagnostics_dict)
    """
    clean_query = query.strip()
    q_lower = clean_query.lower()
    text_stripped = re.sub(r'^[^\w]+|[^\w]+$', '', q_lower)

    diagnostics = {
        "raw_query": clean_query,
        "matched_rule": None
    }

    # 1. Check for explicit Personal Knowledge triggers FIRST.
    # If the user says "Hi, what repositories use Python?", the primary goal is personal knowledge retrieval.
    personal_keywords = [
        "my project", "my projects", "my repo", "my repos", "my repository", "my repositories",
        "my code", "my work", "what did i work on", "what did i do", "what have i done",
        "recent work", "worked on recently", "my commit", "my commits", "my branch", "my branches",
        "my email", "my emails", "my inbox", "my doc", "my docs", "my document", "my documents",
        "my note", "my notes", "my notion", "in my repo", "in my workspace", "our project", "our repo"
    ]
    if any(k in q_lower for k in personal_keywords):
        diagnostics["matched_rule"] = "personal_keywords"
        return ChatIntent.PERSONAL_KNOWLEDGE, diagnostics

    # Memory-OS explicit reference (user asking about Memory-OS system or codebase)
    memory_os_patterns = [r'\bmemory[-_ ]os\b', r'\bcli-memory-os\b']
    if any(re.search(pat, q_lower) for pat in memory_os_patterns):
        diagnostics["matched_rule"] = "memory_os_system_query"
        return ChatIntent.PERSONAL_KNOWLEDGE, diagnostics

    # Check known repository names in local workspace/database
    detected_repo = _check_db_for_repo(q_lower)
    if detected_repo:
        diagnostics["matched_rule"] = f"detected_repo:{detected_repo}"
        diagnostics["detected_repo"] = detected_repo
        return ChatIntent.PERSONAL_KNOWLEDGE, diagnostics

    # Check ContextBuilder query classification
    # If ContextBuilder classifies as Technology, Email, Repository, Documentation, or Cross Repository Question
    context_class = ContextBuilder.classify_query(clean_query, detected_repo)
    if context_class in ["Technology Question", "Email Question", "Repository Question", "Documentation Question", "Cross Repository Question"]:
        diagnostics["matched_rule"] = f"context_builder:{context_class}"
        diagnostics["query_class"] = context_class
        return ChatIntent.PERSONAL_KNOWLEDGE, diagnostics

    # 2. Check for Follow-Up queries if active session history exists
    has_history = session is not None and session.has_history()
    if has_history:
        follow_up_patterns = [
            r'\bexplain that(\s+more\s+simply|\s+simply|\s+better|\s+again)?\b',
            r'\bexplain this(\s+more\s+simply|\s+simply)?\b',
            r'\bexplain it(\s+more\s+simply|\s+simply)?\b',
            r'\b(simplify that|simplify it|make it simpler|break that down)\b',
            r'\b(can you elaborate|elaborate on that|elaborate|tell me more|tell me more about that|more details)\b',
            r'\b(summarize that|summarize this|summarize it|give me a summary|recap that)\b',
            r'\b(why is that|why\?|how so\?|what do you mean|what do you mean by that|repeat that)\b',
            r'\b(what about the second one|what about the first one|what about the other)\b',
            r'^(what about|what does it|how does it|where is it|can it|does it|is it|why did it)\b',
        ]
        if any(re.search(pat, q_lower) for pat in follow_up_patterns):
            diagnostics["matched_rule"] = "follow_up_pattern"
            return ChatIntent.FOLLOW_UP, diagnostics

    # 3. Check for pure Greetings
    greeting_words = {
        "hi", "hello", "hey", "hiya", "howdy", "yo", "greetings",
        "good morning", "good afternoon", "good evening", "good day",
        "hey there", "hello there", "hi there", "sup"
    }
    if text_stripped in greeting_words or re.match(r'^(hi|hello|hey|greetings|good (morning|afternoon|evening|day))(\s+(there|memory[-_ ]os|bot|assistant))?[\s!.,:;~]*$', q_lower):
        diagnostics["matched_rule"] = "greeting_exact"
        return ChatIntent.GREETING, diagnostics

    # 4. Check for Casual chit-chat & pleasantries
    casual_patterns = [
        r'\bhow are you( doing)?\b',
        r"\bhow('s| is) it going\b",
        r'\bhow do you do\b',
        r"\bwhat('s|s) up\b",
        r'\b(thanks|thank you|thanks a lot|thank you very much|thx|ty|cheers)\b',
        r'\b(who are you|what is your name|what are you|what can you do|introduce yourself|help me|help)\b',
        r'\b(good job|great job|nice work|awesome|cool|great)\b',
        r'\b(bye|goodbye|see you|see ya|have a good day)\b'
    ]
    if any(re.search(pat, q_lower) for pat in casual_patterns):
        diagnostics["matched_rule"] = "casual_phrase"
        return ChatIntent.CASUAL, diagnostics

    # 5. Otherwise, treat as a General Question
    diagnostics["matched_rule"] = "general_fallback"
    return ChatIntent.GENERAL, diagnostics


def orchestrate_chat(
    query: str,
    session: Optional[ConversationSession] = None,
    rag_fn: Optional[Callable[[str], Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Execute unified chat routing synchronously.

    Returns dict with:
        answer: str
        mode: 'conversational' | 'rag' | 'fallback'
        intent: str
        sources: list[str]
        repositories: list[str]
        confidence: float
        diagnostics: dict
    """
    if rag_fn is None:
        rag_fn = run_hybrid_rag

    intent, diag = classify_chat_intent(query, session)
    diag["selected_intent"] = intent.value

    # --- Mode 1: Personal Knowledge (Hybrid RAG) ---
    if intent == ChatIntent.PERSONAL_KNOWLEDGE:
        rag_result = rag_fn(query)
        sources = rag_result.get("sources", [])
        repos = rag_result.get("repositories", [])
        confidence = rag_result.get("confidence", 0.0)
        answer = rag_result.get("answer", "")

        # Check if RAG had no indexed matches
        is_missing = (
            confidence == 0.0 or
            "i couldn't find that information in the indexed knowledge" in answer.lower()
        )

        if is_missing:
            q_lower = query.lower()
            # If asking about Memory-OS system itself and it wasn't indexed in DB
            if "memory-os" in q_lower or "memory_os" in q_lower or "memory os" in q_lower:
                answer = (
                    "I couldn't find Memory-OS documentation in your indexed personal knowledge. "
                    "However, Memory-OS is a grounded Personal Knowledge Operating System (PKOS) designed "
                    "to index, track, and query your repositories, documents, and emails using hybrid search."
                )
            elif any(k in q_lower for k in ["what did i work on", "my work", "my commit", "my email", "my activity"]):
                answer = (
                    "I couldn't find any recent work or activity recorded in your indexed knowledge. "
                    "Make sure your repositories, documents, or connectors are synced using 'memory-os sync'."
                )
            else:
                # Offer a helpful general answer if possible
                try:
                    gen_messages = [
                        {"role": "system", "content": SYSTEM_GENERAL_PROMPT},
                        {"role": "user", "content": query}
                    ]
                    general_reply = query_llm_with_retry(gen_messages).strip()
                    answer = (
                        "I couldn't find specific details for that in your indexed workspace knowledge. "
                        f"However, generally speaking:\n\n{general_reply}"
                    )
                except Exception:
                    answer = (
                        "I couldn't find that information in your indexed personal knowledge. "
                        "You can index relevant repositories or documents using 'memory-os sync'."
                    )

        if session is not None:
            session.add_user_message(query)
            session.add_assistant_message(
                answer,
                mode="rag",
                sources=sources,
                repositories=repos,
                confidence=confidence
            )

        return {
            "answer": answer,
            "mode": "rag",
            "intent": intent.value,
            "sources": sources,
            "repositories": repos,
            "confidence": confidence,
            "diagnostics": diag
        }

    # --- Mode 2: Follow-Up Questions ---
    if intent == ChatIntent.FOLLOW_UP:
        messages = [{"role": "system", "content": SYSTEM_FOLLOW_UP_PROMPT}]
        if session is not None:
            messages.extend(session.get_history_messages()[-8:])
        messages.append({"role": "user", "content": query})

        try:
            answer = query_llm_with_retry(messages).strip()
            mode = "conversational"
        except Exception as e:
            logger.warning(f"Follow-up LLM inference failed: {e}")
            answer = (
                "I'm unable to reach the language model right now to process this follow-up. "
                "Please check your internet connection or run 'memory-os doctor'."
            )
            mode = "fallback"

        if session is not None:
            session.add_user_message(query)
            session.add_assistant_message(answer, mode=mode, sources=[], repositories=[])

        return {
            "answer": answer,
            "mode": mode,
            "intent": intent.value,
            "sources": [],
            "repositories": [],
            "confidence": 1.0 if mode == "conversational" else 0.0,
            "diagnostics": diag
        }

    # --- Mode 3: Greetings & Casual Chit-Chat ---
    if intent in [ChatIntent.GREETING, ChatIntent.CASUAL]:
        messages = [{"role": "system", "content": SYSTEM_CONVERSATIONAL_PROMPT}]
        if session is not None:
            messages.extend(session.get_history_messages()[-4:])
        messages.append({"role": "user", "content": query})

        try:
            answer = query_llm_with_retry(messages).strip()
            mode = "conversational"
        except Exception as e:
            logger.info(f"Conversational LLM offline ({e}); using friendly fallback template.")
            answer = get_fallback_conversational_response(intent, query)
            mode = "fallback"

        if session is not None:
            session.add_user_message(query)
            session.add_assistant_message(answer, mode=mode, sources=[], repositories=[])

        return {
            "answer": answer,
            "mode": mode,
            "intent": intent.value,
            "sources": [],
            "repositories": [],
            "confidence": 1.0,
            "diagnostics": diag
        }

    # --- Mode 4: General Questions ---
    messages = [{"role": "system", "content": SYSTEM_GENERAL_PROMPT}]
    if session is not None:
        messages.extend(session.get_history_messages()[-4:])
    messages.append({"role": "user", "content": query})

    try:
        answer = query_llm_with_retry(messages).strip()
        mode = "conversational"
        confidence = 1.0
    except Exception as e:
        logger.error(f"General question LLM inference failed: {e}")
        answer = (
            "I'm unable to reach the language model right now to answer this question. "
            "Please check your internet connection and verify your Groq API key configuration using 'memory-os doctor'."
        )
        mode = "fallback"
        confidence = 0.0

    if session is not None:
        session.add_user_message(query)
        session.add_assistant_message(answer, mode=mode, sources=[], repositories=[])

    return {
        "answer": answer,
        "mode": mode,
        "intent": intent.value,
        "sources": [],
        "repositories": [],
        "confidence": confidence,
        "diagnostics": diag
    }


def orchestrate_chat_stream(
    query: str,
    session: Optional[ConversationSession] = None,
    rag_stream_fn: Optional[Callable[[str], Iterator[Dict[str, Any]]]] = None
) -> Iterator[Dict[str, Any]]:
    """Execute unified chat routing in streaming mode.

    Yields:
        {"type": "diagnostics", "data": dict}
        {"type": "token", "content": str}
        {"type": "done", "answer": str, "mode": str, "sources": list, "repositories": list, "confidence": float}
    """
    if rag_stream_fn is None:
        rag_stream_fn = run_hybrid_rag_stream

    intent, diag = classify_chat_intent(query, session)
    diag["selected_intent"] = intent.value

    # --- Mode 1: Personal Knowledge (Hybrid RAG) ---
    if intent == ChatIntent.PERSONAL_KNOWLEDGE:
        yield {
            "type": "diagnostics",
            "data": {
                "mode": "rag",
                "intent": intent.value,
                "query_class": diag.get("query_class", "Personal Knowledge"),
                **diag
            }
        }

        full_answer = ""
        sources = []
        repos = []
        confidence = 0.0

        for item in rag_stream_fn(query):
            if item.get("type") == "token":
                full_answer += item.get("content", "")
                yield item
            elif item.get("type") == "done":
                sources = item.get("sources", [])
                repos = item.get("repositories", [])
                confidence = item.get("confidence", 0.0)
                full_answer = item.get("answer", full_answer)

        # Check if RAG yielded missing context
        is_missing = (
            confidence == 0.0 or
            "i couldn't find that information in the indexed knowledge" in full_answer.lower()
        )
        if is_missing:
            q_lower = query.lower()
            if "memory-os" in q_lower or "memory_os" in q_lower or "memory os" in q_lower:
                supplement = (
                    "\n\n(Memory-OS is a grounded Personal Knowledge Operating System designed "
                    "to index and query your repositories, documents, and emails with hybrid RAG.)"
                )
                yield {"type": "token", "content": supplement}
                full_answer += supplement

        if session is not None:
            session.add_user_message(query)
            session.add_assistant_message(
                full_answer,
                mode="rag",
                sources=sources,
                repositories=repos,
                confidence=confidence
            )

        yield {
            "type": "done",
            "answer": full_answer,
            "mode": "rag",
            "sources": sources,
            "repositories": repos,
            "confidence": confidence
        }
        return

    # --- Mode 2: Follow-Up Questions ---
    if intent == ChatIntent.FOLLOW_UP:
        yield {
            "type": "diagnostics",
            "data": {
                "mode": "conversational",
                "intent": intent.value,
                "query_class": "Follow-Up Conversation",
                **diag
            }
        }

        messages = [{"role": "system", "content": SYSTEM_FOLLOW_UP_PROMPT}]
        if session is not None:
            messages.extend(session.get_history_messages()[-8:])
        messages.append({"role": "user", "content": query})

        full_answer = ""
        try:
            for token in stream_llm_with_retry(messages):
                full_answer += token
                yield {"type": "token", "content": token}
            mode = "conversational"
        except Exception as e:
            logger.warning(f"Follow-up streaming failed ({e})")
            err_msg = (
                "I'm unable to reach the language model right now to process this follow-up. "
                "Please check your internet connection or run 'memory-os doctor'."
            )
            yield {"type": "token", "content": err_msg}
            full_answer = err_msg
            mode = "fallback"

        if session is not None:
            session.add_user_message(query)
            session.add_assistant_message(full_answer, mode=mode, sources=[], repositories=[])

        yield {
            "type": "done",
            "answer": full_answer,
            "mode": mode,
            "sources": [],
            "repositories": [],
            "confidence": 1.0 if mode == "conversational" else 0.0
        }
        return

    # --- Mode 3: Greetings & Casual Chit-Chat ---
    if intent in [ChatIntent.GREETING, ChatIntent.CASUAL]:
        yield {
            "type": "diagnostics",
            "data": {
                "mode": "conversational",
                "intent": intent.value,
                "query_class": "Casual Conversation",
                **diag
            }
        }

        messages = [{"role": "system", "content": SYSTEM_CONVERSATIONAL_PROMPT}]
        if session is not None:
            messages.extend(session.get_history_messages()[-4:])
        messages.append({"role": "user", "content": query})

        full_answer = ""
        try:
            for token in stream_llm_with_retry(messages):
                full_answer += token
                yield {"type": "token", "content": token}
            mode = "conversational"
        except Exception as e:
            logger.info(f"Streaming LLM unavailable for greeting ({e}); using fallback template.")
            fallback = get_fallback_conversational_response(intent, query)
            yield {"type": "token", "content": fallback}
            full_answer = fallback
            mode = "fallback"

        if session is not None:
            session.add_user_message(query)
            session.add_assistant_message(full_answer, mode=mode, sources=[], repositories=[])

        yield {
            "type": "done",
            "answer": full_answer,
            "mode": mode,
            "sources": [],
            "repositories": [],
            "confidence": 1.0
        }
        return

    # --- Mode 4: General Questions ---
    yield {
        "type": "diagnostics",
        "data": {
            "mode": "conversational",
            "intent": intent.value,
            "query_class": "General Knowledge",
            **diag
        }
    }

    messages = [{"role": "system", "content": SYSTEM_GENERAL_PROMPT}]
    if session is not None:
        messages.extend(session.get_history_messages()[-4:])
    messages.append({"role": "user", "content": query})

    full_answer = ""
    try:
        for token in stream_llm_with_retry(messages):
            full_answer += token
            yield {"type": "token", "content": token}
        mode = "conversational"
        confidence = 1.0
    except Exception as e:
        logger.error(f"Streaming LLM unavailable for general question ({e})")
        err_msg = (
            "I'm unable to reach the language model right now to answer this question. "
            "Please check your internet connection and verify your Groq API key configuration using 'memory-os doctor'."
        )
        yield {"type": "token", "content": err_msg}
        full_answer = err_msg
        mode = "fallback"
        confidence = 0.0

    if session is not None:
        session.add_user_message(query)
        session.add_assistant_message(full_answer, mode=mode, sources=[], repositories=[])

    yield {
        "type": "done",
        "answer": full_answer,
        "mode": mode,
        "sources": [],
        "repositories": [],
        "confidence": confidence
    }
