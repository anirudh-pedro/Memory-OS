from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import logging
import sqlite3
import json

from connectors.github import GitHubConnector
from connectors.gmail import GmailConnector
from connectors.notion import NotionConnector
from connectors.calendar import CalendarConnector

from core.models import Memory
from core.pipeline import IngestionPipeline

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


def create_router(
    agent_graph,
    session,
    db_manager,
    vector_store,
    embedder,
    graph_store,
    pipeline: IngestionPipeline,
    llm=None
) -> APIRouter:
    router = APIRouter()

    @router.post("/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest):
        """Send a message to the Memory-OS agent and get a stateful, memory-first reply."""
        try:
            inputs = {
                "messages": [("user", request.message)],
                "thread_id": request.session_id
            }
            config = {"configurable": {"thread_id": request.session_id}}
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
        """Trigger sync job using the new Ingestion Pipeline connector flow."""
        counts = {}
        try:
            apps = request.apps or ["github", "googlecalendar", "notion", "gmail"]
            memories_to_ingest = []

            if "github" in apps:
                github = GitHubConnector()
                github_mems = github.sync(session)
                memories_to_ingest.extend(github_mems)
                counts["github"] = len(github_mems)

            if "gmail" in apps:
                gmail = GmailConnector(llm=llm, graph_store=graph_store)
                gmail_mems = gmail.sync(session)
                memories_to_ingest.extend(gmail_mems)
                counts["gmail"] = len(gmail_mems)

            if "notion" in apps:
                notion = NotionConnector()
                notion_mems = notion.sync(session)
                memories_to_ingest.extend(notion_mems)
                counts["notion"] = len(notion_mems)

            if "googlecalendar" in apps:
                calendar = CalendarConnector()
                cal_mems = calendar.sync(session)
                memories_to_ingest.extend(cal_mems)
                counts["googlecalendar"] = len(cal_mems)

            # Push all fetched memory objects through Ingestion Pipeline
            if memories_to_ingest:
                pipeline.run_ingestion(memories_to_ingest)

            return SyncResponse(
                status="success",
                synced_counts=counts
            )
        except Exception as e:
            logger.error(f"Sync API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # --- ⚡ New Product Feature Endpoints ⚡ ---

    @router.get("/memory/project/{project_name}")
    async def get_project_brain(project_name: str):
        """Project Brain: Aggregates commits, notes, emails, and docs and synthesizes them using LLM."""
        try:
            # 1. Resolve Project Node in Graph Store
            node = graph_store.get_node(project_name)
            if not node:
                raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found in local Knowledge Graph.")

            # 2. Fetch Graph Relationships
            relationships = graph_store.get_multi_hop_relationships(project_name, depth=2)

            # 3. Retrieve Workspace cache entries matching project name
            conn = db_manager.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT source_app, title, content, last_synced FROM workspace_cache WHERE title LIKE ? OR content LIKE ?",
                (f"%{project_name}%", f"%{project_name}%")
            )
            rows = cursor.fetchall()
            conn.close()

            items = [
                {
                    "source": r["source_app"],
                    "title": r["title"],
                    "content": r["content"],
                    "timestamp": r["last_synced"]
                } for r in rows
            ]

            # 4. Generate LLM synthesized project brain summary
            synthesis_prompt = (
                f"You are the project intelligence synthesizer of Memory-OS.\n"
                f"Compile a detailed, synthesized, and highly readable dashboard for the Project: '{project_name}'\n\n"
                f"Project Type: {node.entity_type}\n"
                f"Primary Description: {node.description}\n"
                f"Properties: {node.properties}\n\n"
                f"Knowledge Graph Connections:\n"
                f"{json.dumps(relationships, indent=2)}\n\n"
                f"Related Workspace Documents/Logs:\n"
                f"{json.dumps(items[:10], indent=2)}\n\n"
                f"Structure your response strictly under these headers:\n"
                f"1. Overview (A synthetic description of the project state and relevance)\n"
                f"2. Technologies Used (A structured list of frame/languages/vector DBs and links)\n"
                f"3. Recent Activity Timeline (Chronological timeline of commits, emails, updates)\n"
                f"4. Related Knowledge & Open Issues (Action items, decisions, discussions, or bugs)\n"
                f"5. Dependencies & Links (Other projects, people, or orgs connected to it)\n"
            )
            
            synthesis_content = "LLM synthesis not available."
            if llm:
                try:
                    synthesis_resp = llm.invoke(synthesis_prompt)
                    synthesis_content = str(synthesis_resp.content)
                except Exception as ex:
                    synthesis_content = f"Synthesis run failed: {ex}"
            else:
                # Basic fallback text compilation
                synthesis_content = (
                    f"Overview:\n{node.description or 'No description available.'}\n\n"
                    f"Relations: {len(relationships)} connections found.\n"
                    f"Workspace matches: {len(items)} records retrieved."
                )

            return {
                "project": project_name,
                "type": node.entity_type,
                "description": node.description,
                "properties": node.properties,
                "relationships": relationships,
                "related_workspace_items": items,
                "synthesized_brain": synthesis_content
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Project Brain API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/memory/quality")
    async def get_graph_quality():
        """Retrieve metrics on Graph quality, candidates for resolution, placeholders, and noise."""
        try:
            conn = db_manager.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM entities")
            total_nodes = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM relationships")
            total_rels = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM entities WHERE entity_type = 'Project'")
            project_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM entities WHERE entity_type = 'Person'")
            people_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM entities WHERE entity_type = 'Technology'")
            tech_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT name, entity_type FROM entities")
            all_ents = cursor.fetchall()
            
            # Find duplicate candidates
            dup_candidates = []
            seen = set()
            for e1 in all_ents:
                n1 = e1["name"].lower()
                t1 = e1["entity_type"]
                for e2 in all_ents:
                    n2 = e2["name"].lower()
                    t2 = e2["entity_type"]
                    if n1 != n2 and t1 == t2:
                        pair = tuple(sorted([e1["name"], e2["name"]]))
                        if pair not in seen:
                            if n1 in n2 or n2 in n1:
                                dup_candidates.append(f"{e1['name']} <-> {e2['name']} ({t1})")
                                seen.add(pair)
                                
            # Placeholders
            placeholders_pattern = ["unknown", "null", "none", "test", "untitled", "<unknown_repository>", "<owner>/<repo>"]
            placeholders_found = [e["name"] for e in all_ents if any(p in e["name"].lower() for p in placeholders_pattern) or "<" in e["name"] or ">" in e["name"]]
            
            # Noise
            noise_found = [e["name"] for e in all_ents if e["name"].lower().startswith("create ") or e["name"].lower().startswith("run ") or "follow-up" in e["name"].lower() or "expected" in e["name"].lower()]
            
            conn.close()
            
            avg_node_degree = (total_rels / total_nodes) if total_nodes > 0 else 0.0
            
            return {
                "total_nodes": total_nodes,
                "total_relationships": total_rels,
                "average_node_degree": avg_node_degree,
                "project_count": project_count,
                "people_count": people_count,
                "technology_count": tech_count,
                "duplicate_candidates": dup_candidates,
                "duplicate_candidates_count": len(dup_candidates),
                "placeholder_nodes": placeholders_found,
                "placeholder_nodes_count": len(placeholders_found),
                "noise_nodes": noise_found,
                "noise_nodes_count": len(noise_found)
            }
        except Exception as e:
            logger.error(f"Quality Dashboard API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/graph-quality")
    async def get_graph_quality_alias():
        """Alias for /memory/quality to support first-class graph-quality checks."""
        return await get_graph_quality()

    @router.get("/memory/timeline")
    async def get_timeline(start: str, end: str):
        """Timeline View: Retrieves chronological logs of activities (commits, emails, events)."""
        try:
            # Check date formats
            try:
                datetime.fromisoformat(start)
                datetime.fromisoformat(end)
            except ValueError:
                raise HTTPException(status_code=400, detail="Dates must be in ISO format (YYYY-MM-DD).")

            conn = db_manager.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT source_app, title, content, last_synced FROM workspace_cache WHERE last_synced BETWEEN ? AND ? ORDER BY last_synced ASC",
                (start, end)
            )
            rows = cursor.fetchall()
            conn.close()

            timeline = [
                {
                    "source": r["source_app"],
                    "title": r["title"],
                    "content": r["content"],
                    "timestamp": r["last_synced"]
                } for r in rows
            ]

            return {
                "start_date": start,
                "end_date": end,
                "events_count": len(timeline),
                "timeline": timeline
            }
        except Exception as e:
            logger.error(f"Timeline API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/memory/explore")
    async def get_relationship_exploration(source: str, target: str):
        """Relationship Explorer: Exposes the CTE connection path path between two entities."""
        try:
            # Check source and target nodes exist
            src_node = graph_store.get_node(source)
            tgt_node = graph_store.get_node(target)
            
            if not src_node or not tgt_node:
                raise HTTPException(status_code=404, detail="Source or target entity not found in Knowledge Graph.")

            # Traverse 2-hop CTE paths matching both entities
            rels_src = graph_store.get_multi_hop_relationships(source, depth=2)
            
            # Filter connections that link source to target directly or via a 1-hop intermediary
            path_found = []
            for r in rels_src:
                if (r["source"].lower() == source.lower() and r["target"].lower() == target.lower()) or \
                   (r["source"].lower() == target.lower() and r["target"].lower() == source.lower()):
                    path_found.append(r)
                elif r["target"].lower() == target.lower() or r["source"].lower() == target.lower():
                    path_found.append(r)

            return {
                "source": source,
                "target": target,
                "relationship_paths": path_found if path_found else "No direct 1 or 2-hop relationship path found between entities."
            }
        except Exception as e:
            logger.error(f"Relationship Exploration API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/memory/graph")
    async def get_graph():
        """Retrieve the entire knowledge graph (entities and relationships)."""
        try:
            nodes = graph_store.get_all_nodes()
            edges = graph_store.get_all_relationships()
            return {
                "nodes": [n.model_dump() for n in nodes],
                "edges": edges
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.delete("/memory/session/{session_id}")
    async def clear_session(session_id: str):
        """Clear checkpointer checkpoints and conversation log details for session ID."""
        try:
            conn = db_manager.get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM messages WHERE thread_id = ?", (session_id,))
            cursor.execute("DELETE FROM checkpoints WHERE thread_id = ?", (session_id,))
            cursor.execute("DELETE FROM writes WHERE thread_id = ?", (session_id,))
            conn.commit()
            conn.close()
            return {"status": "success", "message": f"Cleared conversational memory for session '{session_id}'."}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/debug-retrieval")
    async def debug_retrieval(query: str):
        """Diagnostic route to inspect hybrid search hits and token budget counts."""
        try:
            from retrieval.search import HybridSearcher
            from retrieval.fusion import ReciprocalRankFusion
            from retrieval.context import ContextBuilder
            
            searcher = HybridSearcher(db_manager, vector_store, embedder, graph_store)
            
            fts_res = searcher.search_workspace_cache(query, limit=5)
            vector_res = searcher.search_vector_store(query, limit=5)
            graph_res = searcher.search_graph(query, limit=5)
            
            fusion = ReciprocalRankFusion()
            fused = fusion.fuse(fts_res, vector_res)
            
            context_builder = ContextBuilder(char_budget=10000)
            context = context_builder.build_context(fused, graph_res)
            
            token_count = len(context) // 4
            
            return {
                "query": query,
                "fts_hits": fts_res,
                "vector_hits": vector_res,
                "graph_hits": graph_res,
                "fused_hits": fused,
                "context": context,
                "token_count": token_count,
                "context_size_chars": len(context)
            }
        except Exception as e:
            logger.error(f"Debug retrieval error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return router
