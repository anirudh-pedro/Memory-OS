"""
tests.test_conversational_chat: Comprehensive regression test suite for
Memory-OS conversational AI chatbot upgrades, intent routing, multi-turn
conversation memory, source citations, and graceful error handling.
"""

import io
import sys
from unittest.mock import patch, MagicMock
import pytest

from core.chat import (
    ChatIntent,
    ConversationSession,
    classify_chat_intent,
    orchestrate_chat,
    orchestrate_chat_stream,
    get_fallback_conversational_response,
    FALLBACK_GREETING,
)
from cli.commands.ask import run_and_print_ask


class TestIntentClassification:
    """Test intent classification rules across various user query types."""

    def test_greetings_routing(self):
        queries = ["Hi", "Hello", "Hey", "Good morning", "good afternoon", "good evening", "hiya", "howdy", "Hello there!"]
        for q in queries:
            intent, diag = classify_chat_intent(q)
            assert intent == ChatIntent.GREETING, f"Expected GREETING for '{q}', got {intent}"

    def test_casual_conversation_routing(self):
        queries = [
            "How are you?",
            "how's it going",
            "Thanks",
            "Thank you very much",
            "Who are you?",
            "What can you do?",
            "Good job",
            "Goodbye"
        ]
        for q in queries:
            intent, diag = classify_chat_intent(q)
            assert intent == ChatIntent.CASUAL, f"Expected CASUAL for '{q}', got {intent}"

    def test_personal_knowledge_routing_personal_keywords(self):
        queries = [
            "What did I work on recently?",
            "What did I do yesterday?",
            "Show my projects",
            "What are my repositories?",
            "Find my code for authentication",
            "Check my emails from yesterday",
            "Show my commits in the branch",
            "What repositories use Python?",
            "Which projects use Docker?",
            "What is Memory-OS?",
        ]
        for q in queries:
            intent, diag = classify_chat_intent(q)
            assert intent == ChatIntent.PERSONAL_KNOWLEDGE, f"Expected PERSONAL_KNOWLEDGE for '{q}', got {intent}"

    def test_follow_up_with_history(self):
        session = ConversationSession()
        session.add_user_message("What is Memory-OS?")
        session.add_assistant_message("Memory-OS is a grounded Personal Knowledge Operating System.")

        follow_ups = [
            "Explain that more simply",
            "explain this simply",
            "Can you elaborate on that?",
            "Tell me more about that",
            "Summarize that",
            "Why is that?",
            "What do you mean by that?"
        ]
        for q in follow_ups:
            intent, diag = classify_chat_intent(q, session=session)
            assert intent == ChatIntent.FOLLOW_UP, f"Expected FOLLOW_UP for '{q}', got {intent}"

    def test_follow_up_without_history_not_classified_as_follow_up(self):
        empty_session = ConversationSession()
        intent, _ = classify_chat_intent("Explain that more simply", session=empty_session)
        assert intent != ChatIntent.FOLLOW_UP

    def test_general_questions_routing(self):
        queries = [
            "What is photosynthesis?",
            "How does quicksort work?",
            "Explain the difference between TCP and UDP",
            "Write a Python function to check palindromes",
            "What is the capital of France?"
        ]
        for q in queries:
            intent, diag = classify_chat_intent(q)
            assert intent == ChatIntent.GENERAL, f"Expected GENERAL for '{q}', got {intent}"


class TestConversationSessionMemory:
    """Verify session memory preserves turns in-memory and keeps indexed data separate."""

    def test_session_turns_management(self):
        session = ConversationSession(max_turns=3)
        assert session.has_history() is False
        assert len(session.turns) == 0

        session.add_user_message("Hello")
        session.add_assistant_message("Hi there!", mode="conversational")
        assert session.has_history() is True
        assert len(session.turns) == 2

        last_assistant = session.get_last_assistant_turn()
        assert last_assistant["role"] == "assistant"
        assert last_assistant["content"] == "Hi there!"

        # Add more turns exceeding limit
        session.add_user_message("Question 2")
        session.add_assistant_message("Answer 2")
        session.add_user_message("Question 3")
        session.add_assistant_message("Answer 3")
        session.add_user_message("Question 4")
        session.add_assistant_message("Answer 4")

        # Bounded by max_turns * 2 messages (6 messages)
        assert len(session.turns) == 6
        assert session.turns[0]["content"] == "Question 2"

        # Clear session
        session.clear()
        assert len(session.turns) == 0
        assert session.has_history() is False

    def test_session_keeps_data_transient_no_db_persistence(self):
        session = ConversationSession()
        session.add_user_message("My secret transient question")
        session.add_assistant_message("Transient answer")
        
        # Verify transient storage
        assert len(session.turns) == 2
        # Verify it has no DB methods or disk writes
        assert not hasattr(session, "save")
        assert not hasattr(session, "persist")


class TestChatOrchestration:
    """Test unified chat orchestration behavior, RAG grounding, and fallbacks."""

    def test_greeting_produces_natural_response(self):
        res = orchestrate_chat("Hi")
        # Ensure it does NOT respond with knowledge retrieval failure
        assert "couldn't find that information in the indexed knowledge" not in res["answer"].lower()
        assert res["mode"] in ["conversational", "fallback"]
        assert res["sources"] == []
        assert res["repositories"] == []
        assert len(res["answer"]) > 0

    def test_greeting_offline_fallback(self):
        with patch("core.chat.query_llm_with_retry", side_effect=RuntimeError("Offline")):
            res = orchestrate_chat("Hi")
            assert res["mode"] == "fallback"
            assert res["answer"] == FALLBACK_GREETING
            assert res["sources"] == []
            assert res["repositories"] == []

    def test_casual_chit_chat_offline_fallback(self):
        with patch("core.chat.query_llm_with_retry", side_effect=RuntimeError("Offline")):
            res = orchestrate_chat("How are you?")
            assert res["mode"] == "fallback"
            assert "doing well" in res["answer"].lower()
            assert res["sources"] == []

    def test_general_question_offline_clear_explanation(self):
        with patch("core.chat.query_llm_with_retry", side_effect=RuntimeError("Connection refused")):
            res = orchestrate_chat("What is photosynthesis?")
            assert res["mode"] == "fallback"
            assert "unable to reach the language model" in res["answer"].lower()
            assert "memory-os doctor" in res["answer"].lower()
            assert res["sources"] == []

    def test_what_is_memory_os_with_rag_sources(self):
        mock_rag_res = {
            "answer": "Memory-OS is a personal knowledge operating system.",
            "sources": ["README.md"],
            "repositories": ["Memory-OS"],
            "confidence": 0.95
        }
        res = orchestrate_chat("What is Memory-OS?", rag_fn=lambda q: mock_rag_res)
        assert res["mode"] == "rag"
        assert res["answer"] == "Memory-OS is a personal knowledge operating system."
        assert res["sources"] == ["README.md"]
        assert res["repositories"] == ["Memory-OS"]
        assert res["confidence"] == 0.95

    def test_what_is_memory_os_when_not_indexed_explains_usefully(self):
        mock_empty_rag = {
            "answer": "I couldn't find that information in the indexed knowledge.",
            "sources": [],
            "repositories": [],
            "confidence": 0.0
        }
        res = orchestrate_chat("What is Memory-OS?", rag_fn=lambda q: mock_empty_rag)
        assert res["mode"] == "rag"
        # Must produce a useful answer about Memory-OS rather than pure empty rejection
        assert "memory-os is a grounded personal knowledge operating system" in res["answer"].lower()
        assert res["sources"] == []
        assert res["repositories"] == []

    def test_personal_activity_not_indexed_explains_sync(self):
        mock_empty_rag = {
            "answer": "I couldn't find that information in the indexed knowledge.",
            "sources": [],
            "repositories": [],
            "confidence": 0.0
        }
        res = orchestrate_chat("What did I work on recently?", rag_fn=lambda q: mock_empty_rag)
        assert res["mode"] == "rag"
        assert "couldn't find any recent work or activity" in res["answer"].lower()
        assert "memory-os sync" in res["answer"].lower()
        assert res["sources"] == []

    def test_follow_up_uses_conversation_context(self):
        session = ConversationSession()
        session.add_user_message("What is Memory-OS?")
        session.add_assistant_message("Memory-OS is an operating system and personal knowledge assistant.")

        captured_messages = []
        def mock_llm_query(messages):
            captured_messages.extend(messages)
            return "In simple terms, Memory-OS is like a personal smart search engine for your computer."

        with patch("core.chat.query_llm_with_retry", side_effect=mock_llm_query):
            res = orchestrate_chat("Explain that more simply", session=session)
            assert res["intent"] == "follow_up"
            assert "simple terms" in res["answer"].lower()

            # Verify that previous turn was supplied to the LLM
            history_roles = [m["role"] for m in captured_messages]
            history_contents = [m["content"] for m in captured_messages]
            assert "system" in history_roles
            assert any("What is Memory-OS?" in c for c in history_contents)
            assert any("Memory-OS is an operating system" in c for c in history_contents)
            assert any("Explain that more simply" in c for c in history_contents)

    def test_streaming_greeting(self):
        tokens = []
        for item in orchestrate_chat_stream("Hi"):
            if item.get("type") == "token":
                tokens.append(item.get("content"))
            elif item.get("type") == "done":
                assert item["mode"] in ["conversational", "fallback"]
                assert item["sources"] == []
                assert item["repositories"] == []
        full_streamed = "".join(tokens)
        assert len(full_streamed) > 0
        assert "couldn't find that information in the indexed knowledge" not in full_streamed.lower()


class TestCLIAskOutputFormatting:
    """Verify that CLI output formats conversational vs RAG responses appropriately."""

    def test_ask_greeting_formatting(self):
        captured_stdout = io.StringIO()
        with patch("sys.stdout", captured_stdout):
            run_and_print_ask("Hi")
        output = captured_stdout.getvalue()
        assert "ANSWER" in output
        # For a greeting, SOURCES and REPOSITORIES USED should NOT be forced
        assert "SOURCES" not in output
        assert "REPOSITORIES USED" not in output
        assert "couldn't find that information in the indexed knowledge" not in output.lower()

    def test_ask_personal_knowledge_formatting_with_sources(self):
        mock_rag = {
            "answer": "Python is used across connected microservices.",
            "sources": ["main.py", "README.md"],
            "repositories": ["demo-repo"],
            "confidence": 0.95
        }
        captured_stdout = io.StringIO()
        with patch("sys.stdout", captured_stdout):
            with patch("cli.commands.ask.run_hybrid_rag", return_value=mock_rag):
                run_and_print_ask("What repositories use Python?")
        output = captured_stdout.getvalue()
        assert "ANSWER" in output
        assert "Python is used across connected microservices." in output
        assert "SOURCES" in output
        assert "- main.py" in output
        assert "- README.md" in output
        assert "REPOSITORIES USED" in output
        assert "- demo-repo" in output
        assert "Confidence: 0.95" in output


class TestTUIConversationalIntegration:
    """Test TUI ChatPanel conversational behavior, greeting rendering, and multiline support."""

    @pytest.mark.asyncio
    async def test_tui_chat_panel_greeting(self):
        from cli.tui.app import MemoryOSTUIApp

        def mock_greeting_generator(question, session=None, rag_stream_fn=None):
            yield {"type": "diagnostics", "data": {"mode": "conversational", "query_class": "Greeting"}}
            yield {"type": "token", "content": "Hello! How can I help you today?"}
            yield {"type": "done", "answer": "Hello! How can I help you today?", "mode": "conversational", "sources": [], "repositories": [], "confidence": 1.0}

        with patch("cli.tui.app.Sidebar.perform_health_checks"):
            with patch("cli.tui.app.orchestrate_chat_stream", side_effect=mock_greeting_generator):
                app = MemoryOSTUIApp()
                async with app.run_test() as pilot:
                    chat_input = app.query_one("#chat_input")
                    chat_input.value = "Hi"
                    await pilot.press("enter")
                    await pilot.pause()

                    # Find chat history messages
                    history = app.query_one("#chat_history_scroll")
                    agent_msgs = history.query(".chat_msg_agent")
                    assert len(agent_msgs) >= 1
                    last_widget = agent_msgs[-1]
                    visual = last_widget.render()
                    renderable = getattr(visual, "_renderable", visual)
                    markup_text = str(getattr(renderable, "markup", renderable))
                    # Ensure conversational reply rendered without sources
                    assert "Hello! How can I help you today?" in markup_text
                    assert "Sources" not in markup_text

    @pytest.mark.asyncio
    async def test_tui_chat_multiline_continuation(self):
        from cli.tui.app import MemoryOSTUIApp

        with patch("cli.tui.app.Sidebar.perform_health_checks"):
            app = MemoryOSTUIApp()
            async with app.run_test() as pilot:
                chat_input = app.query_one("#chat_input")
                # Type line 1 with backslash continuation
                chat_input.value = "First line of a multiline question \\"
                await pilot.press("enter")
                await pilot.pause()

                # Value should retain line 1 without submitting yet
                assert "First line of a multiline question" in chat_input.value
                assert chat_input.disabled is False
