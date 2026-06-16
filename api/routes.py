from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
import logging

# Sync methods
from integrations.github_sync import sync_github
from integrations.gmail_sync import sync_gmail
from integrations.notion_sync import sync_notion
from integrations.calendar_sync import sync_calendar

logger = logging.getLogger(__name__)

# Request & Response Schemas
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default_session"

class ChatResponse(BaseModel):
    reply: str
    session_id: str

class SyncRequest(BaseModel):
    apps: Optional[List[str]] = ["github", "googlecalendar", "notion", "gmail"]

class SyncResponse(BaseModel):
    status: str
    synced_counts: dict


def create_router(agent_graph, session, db_path, message_repo, cache_repo, graph_manager, retrieval_engine=None) -> APIRouter:
    router = APIRouter()

    @router.post("/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest):
        """Send a message to the Memory-OS agent and get a stateful reply."""
        try:
            inputs = {
                "messages": [("user", request.message)],
                "thread_id": request.session_id
            }
            # Config containing thread_id for LangGraph checkpointer
            config = {"configurable": {"thread_id": request.session_id}}
            
            # Execute LangGraph execution
            output = agent_graph.invoke(inputs, config=config)
            
            messages = output.get("messages", [])
            if not messages:
                raise HTTPException(status_code=500, detail="No reply returned by agent.")
                
            last_msg = messages[-1]
            return ChatResponse(
                reply=str(last_msg.content),
                session_id=request.session_id
            )
        except Exception as e:
            logger.error(f"Chat API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/sync", response_model=SyncResponse)
    async def sync(request: SyncRequest):
        """Trigger sync job for selected applications and cache records locally."""
        counts = {}
        try:
            apps = request.apps or ["github", "googlecalendar", "notion", "gmail"]
            
            if "github" in apps:
                counts["github"] = sync_github(session, cache_repo)
            if "gmail" in apps:
                counts["gmail"] = sync_gmail(session, cache_repo)
            if "notion" in apps:
                counts["notion"] = sync_notion(session, cache_repo)
            if "googlecalendar" in apps:
                counts["googlecalendar"] = sync_calendar(session, cache_repo)
                
            # Trigger Vector DB re-indexing dynamically after sync completes
            if retrieval_engine:
                logger.info("Sync complete. Re-indexing vector store...")
                retrieval_engine.initialize_vector_index()
                
            return SyncResponse(
                status="success",
                synced_counts=counts
            )
        except Exception as e:
            logger.error(f"Sync API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/memory/graph")
    async def get_graph():
        """Retrieve the entire knowledge graph (entities and relationships)."""
        try:
            nodes = graph_manager.get_all_nodes()
            edges = graph_manager.get_all_relationships()
            return {
                "nodes": nodes,
                "edges": edges
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.delete("/memory/session/{session_id}")
    async def clear_session(session_id: str):
        """Clear message history and SQLite checkpoints for the specified session ID."""
        try:
            message_repo.clear_thread(session_id)
            
            # Also clean LangGraph SQLite checkpointer tables
            import sqlite3
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM checkpoints WHERE thread_id = ?", (session_id,))
            cursor.execute("DELETE FROM writes WHERE thread_id = ?", (session_id,))
            conn.commit()
            conn.close()
            
            return {"status": "success", "message": f"Cleared conversational memory for session '{session_id}'."}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return router
