import pytest
from unittest.mock import patch, MagicMock
from cli.tui.app import MemoryOSTUIApp


@pytest.mark.asyncio
async def test_tui_app_boot_and_default_view():
    """Verify that the TUI boots correctly and defaults to the chat screen."""
    app = MemoryOSTUIApp()
    async with app.run_test() as pilot:
        assert app.title == "Memory-OS Terminal UI"
        
        # Verify initial screen switcher state is 'chat'
        switcher = app.query_one("#panel_switcher")
        assert switcher.current == "chat"
        
        # Verify sidebar menu is visible initially
        assert app.sidebar_visible is True


@pytest.mark.asyncio
async def test_tui_sidebar_toggle():
    """Test sidebar visibility toggles on ctrl+b keystroke."""
    app = MemoryOSTUIApp()
    async with app.run_test() as pilot:
        assert app.sidebar_visible is True
        
        # Send ctrl+b
        await pilot.press("ctrl+b")
        assert app.sidebar_visible is False
        
        # Send ctrl+b again
        await pilot.press("ctrl+b")
        assert app.sidebar_visible is True


@pytest.mark.asyncio
async def test_tui_view_switching():
    """Test switching screens using hotkeys."""
    app = MemoryOSTUIApp()
    async with app.run_test() as pilot:
        switcher = app.query_one("#panel_switcher")
        assert switcher.current == "chat"

        # Unfocus input before pressing hotkeys
        app.set_focus(None)

        # Press 's' to go to Sync
        app.set_focus(None)
        await pilot.press("s")
        assert switcher.current == "sync"

        # Press 'd' to go to Doctor
        app.set_focus(None)
        await pilot.press("d")
        assert switcher.current == "doctor"

        # Press 'g' to go to Graph
        app.set_focus(None)
        await pilot.press("g")
        assert switcher.current == "graph"

        # Press 'f' to go to Search
        app.set_focus(None)
        await pilot.press("f")
        assert switcher.current == "search"

        # Press 'm' to go to Monitor
        app.set_focus(None)
        await pilot.press("m")
        assert switcher.current == "monitor"

        # Press 'e' to go to Settings
        app.set_focus(None)
        await pilot.press("e")
        assert switcher.current == "settings"

        # Press 'c' to return to Chat
        app.set_focus(None)
        await pilot.press("c")
        assert switcher.current == "chat"



@pytest.mark.asyncio
async def test_tui_chat_submit():
    """Test submitting a question and receiving a mock streamed answer."""
    mock_generator_data = [
        {"type": "diagnostics", "data": {"query_class": "General Question"}},
        {"type": "token", "content": "This is "},
        {"type": "token", "content": "a test RAG response."},
        {"type": "done", "answer": "This is a test RAG response.", "sources": ["source.txt"], "repositories": ["test_repo"], "confidence": 0.9}
    ]

    def mock_generator(question):
        for item in mock_generator_data:
            yield item

    with patch("cli.tui.app.run_hybrid_rag_stream", side_effect=mock_generator) as mock_rag:
        app = MemoryOSTUIApp()
        async with app.run_test() as pilot:
            # Find input box
            chat_input = app.query_one("#chat_input")
            chat_input.value = "What is Memory-OS?"
            
            # Press enter
            await pilot.press("enter")
            
            # Allow background workers to update UI
            await pilot.pause()
            
            # Verify RAG pipeline was invoked
            mock_rag.assert_called_once_with("What is Memory-OS?")
            
            # Verify input gets re-enabled after stream completion
            assert chat_input.disabled is False
