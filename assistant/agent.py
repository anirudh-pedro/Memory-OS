from typing import TypedDict, Annotated, Sequence, Optional
import logging
import copy
import json
from pydantic import BaseModel
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from core.graph_store import BaseGraphStore
from core.models import Entity, Relationship
from core.extractor import GraphRAGExtractor
from retrieval.search import HybridSearcher
from retrieval.fusion import ReciprocalRankFusion
from retrieval.context import ContextBuilder
from assistant.prompts import SYSTEM_TEMPLATE
from assistant.actions import STATE_CHANGING_TOOLS, get_action_description

logger = logging.getLogger(__name__)

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    thread_id: str
    pending_action: Optional[dict]


class PersonalAssistantBuilder:
    def __init__(
        self,
        llm,
        tools: list[BaseTool],
        graph_store: BaseGraphStore,
        searcher: HybridSearcher,
        extractor: GraphRAGExtractor,
        db_path: str = "memory.db"
    ):
        self.llm = llm
        self.tools = tools
        self.graph_store = graph_store
        self.searcher = searcher
        self.extractor = extractor
        self.db_path = db_path
        self.fusion = ReciprocalRankFusion()
        self.context_builder = ContextBuilder(char_budget=10000, llm=self.llm)

    def _get_relevant_tools(self, query: str) -> list:
        if not query:
            return []
        query_lower = query.lower()
        
        has_github = any(w in query_lower for w in ["github", "repo", "repository", "pr", "pull", "issue", "commit", "git", "fork", "clone"])
        has_calendar = any(w in query_lower for w in ["calendar", "event", "meeting", "schedule", "date", "appointment", "cal", "schedule"])
        has_notion = any(w in query_lower for w in ["notion", "page", "database", "doc", "document", "notes", "note"])
        has_gmail = any(w in query_lower for w in ["gmail", "email", "mail", "send", "inbox", "message"])
        
        selected_tools = []
        for t in self.tools:
            name_upper = t.name.upper()
            if has_github and name_upper.startswith("GITHUB_"):
                selected_tools.append(t)
            elif has_calendar and name_upper.startswith("GOOGLECALENDAR_"):
                selected_tools.append(t)
            elif has_notion and name_upper.startswith("NOTION_"):
                selected_tools.append(t)
            elif has_gmail and name_upper.startswith("GMAIL_"):
                selected_tools.append(t)
                
        logger.info(f"Dynamic Tool Selection: Selected {len(selected_tools)} tools for query: '{query}'")
        return selected_tools

    def _should_continue(self, state: AgentState):
        last_message = state["messages"][-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return "extract_and_save"

    def _call_model(self, state: AgentState):
        messages = state["messages"]
        thread_id = state.get("thread_id", "default")
        pending = state.get("pending_action")

        # 1. Handle user response to pending action proposal if present
        if pending:
            user_msg = ""
            for msg in reversed(messages):
                if isinstance(msg, HumanMessage):
                    user_msg = str(msg.content).strip().lower().strip(".,!?;:")
                    break
            
            confirm_words = {"yes", "proceed", "confirm", "do it", "go ahead", "sure", "okay"}
            cancel_words = {"no", "cancel", "stop", "never mind"}
            
            if user_msg in confirm_words:
                tool_call = {
                    "name": pending["tool_name"],
                    "args": pending["args"],
                    "id": pending["id"],
                    "type": "tool_call"
                }
                ai_msg = AIMessage(
                    content=f"Executing {pending['tool_name']}...",
                    tool_calls=[tool_call]
                )
                logger.info(f"User confirmed action. Executing pending action: {pending['tool_name']}")
                return {
                    "messages": [ai_msg],
                    "pending_action": None
                }
            elif user_msg in cancel_words:
                ai_msg = AIMessage(content="❌ Action cancelled.")
                logger.info(f"User cancelled action: {pending['tool_name']}")
                return {
                    "messages": [ai_msg],
                    "pending_action": None
                }
            else:
                action_desc = get_action_description(pending["tool_name"])
                ai_msg = AIMessage(
                    content=(
                        f"There is a pending action:\n"
                        f"Proposed Action:\n"
                        f"{action_desc}\n\n"
                        f"Please reply with 'yes' to proceed, or 'no' to cancel."
                    )
                )
                return {
                    "messages": [ai_msg]
                }

        # 2. Hybrid context retrieval
        last_user_query = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_user_query = str(msg.content)
                break

        retrieved_context = "No relevant context found in local memory."
        if last_user_query:
            query_lower = last_user_query.lower()
            is_project_tech_query = (
                "project" in query_lower and 
                ("tech" in query_lower or "use" in query_lower or "work" in query_lower or "stack" in query_lower)
            )
            
            if is_project_tech_query:
                try:
                    from retrieval.project_aggregator import ProjectAggregator
                    aggregator = ProjectAggregator(self.db_path)
                    summary = aggregator.get_project_summary()
                    
                    context_lines = ["=== STRUCTURED PROJECTS & TECHNOLOGIES CONTEXT ==="]
                    for p in summary:
                        context_lines.append(f"\nProject: {p['project_name']}")
                        context_lines.append(f"Description: {p['description']}")
                        context_lines.append(f"Technologies: {', '.join(p['technologies']) if p['technologies'] else 'None detected'}")
                        context_lines.append(f"Repositories: {', '.join(p['repositories']) if p['repositories'] else 'None'}")
                        context_lines.append(f"Recent Activity:")
                        if p['recent_activity']:
                            for act in p['recent_activity']:
                                context_lines.append(f"  - {act}")
                        else:
                            context_lines.append("  - No recent activity recorded.")
                    
                    retrieved_context = "\n".join(context_lines)
                except Exception as e:
                    logger.error(f"Failed to compile aggregated projects summary: {e}")
                    is_project_tech_query = False

            if not is_project_tech_query:
                # Query all retrieval paths
                fts_res = self.searcher.search_workspace_cache(last_user_query, limit=5)
                vector_res = self.searcher.search_vector_store(last_user_query, limit=5)
                graph_res = self.searcher.search_graph(last_user_query, limit=5)

                # Perform Reciprocal Rank Fusion
                fused = self.fusion.fuse(fts_res, vector_res)
                # Assemble markdown prompt context block
                retrieved_context = self.context_builder.build_context(fused, graph_res)

        # 3. Dynamic chat prompt setup
        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_TEMPLATE),
            MessagesPlaceholder(variable_name="messages")
        ])

        # Truncate content of any history message to preserve context window limit
        truncated_messages = []
        for msg in messages[-5:]:
            content_str = str(msg.content) if msg.content else ""
            if len(content_str) > 1000:
                msg_copy = copy.copy(msg)
                msg_copy.content = content_str[:1000] + "\n... [truncated] ..."
                truncated_messages.append(msg_copy)
            else:
                truncated_messages.append(msg)

        relevant_tools = self._get_relevant_tools(last_user_query)
        if relevant_tools:
            chain = prompt | self.llm.bind_tools(relevant_tools)
        else:
            chain = prompt | self.llm
            
        response = chain.invoke({
            "messages": truncated_messages,
            "retrieved_context": retrieved_context
        })

        # 4. Intercept state-changing tool calls
        has_state_changing_tool = False
        target_tool_call = None
        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                if tc["name"] in STATE_CHANGING_TOOLS:
                    has_state_changing_tool = True
                    target_tool_call = tc
                    break
                    
        if has_state_changing_tool:
            action_desc = get_action_description(target_tool_call["name"])
            args_desc = ""
            for k, v in target_tool_call["args"].items():
                k_display = k.replace("_", " ").title()
                args_desc += f"{k_display}: {v}\n"
                
            prop_content = (
                f"Proposed Action:\n"
                f"{action_desc}\n\n"
                f"{args_desc.strip()}\n\n"
                f"Would you like me to proceed?"
            )
            
            prop_msg = AIMessage(content=prop_content)
            pending_action_data = {
                "tool_name": target_tool_call["name"],
                "args": target_tool_call["args"],
                "id": target_tool_call["id"]
            }

            logger.info(f"Intercepted state-changing tool call '{target_tool_call['name']}'. Proposing action to user.")
            return {
                "messages": [prop_msg],
                "pending_action": pending_action_data
            }

        return {"messages": [response]}

    def _extract_and_save_node(self, state: AgentState):
        messages = state["messages"]
        thread_id = state.get("thread_id", "default")
        
        # 1. Save messages to database (conversational log)
        try:
            import sqlite3
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Save any new messages
            for msg in messages:
                if msg.content:
                    role = "user" if isinstance(msg, HumanMessage) else "assistant"
                    cursor.execute(
                        "INSERT INTO messages (thread_id, role, content, metadata_json) VALUES (?, ?, ?, ?)",
                        (thread_id, role, str(msg.content), json.dumps({"class": msg.__class__.__name__}))
                    )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to save message to repo: {e}")

        # 2. Extract Entities and Relationships using LLM GraphRAG Extractor
        last_turn_text = ""
        user_msgs = [m for m in messages if isinstance(m, HumanMessage)]
        ai_msgs = [m for m in messages if isinstance(m, AIMessage)]
        if user_msgs:
            last_turn_text += f"User: {user_msgs[-1].content}\n"
        if ai_msgs:
            last_turn_text += f"Assistant: {ai_msgs[-1].content}\n"

        if last_turn_text:
            self.extractor.extract_and_merge(last_turn_text)

        return state

    def build_graph(self):
        """Assembles the LangGraph StateGraph agent."""
        workflow = StateGraph(AgentState)

        # Register nodes
        workflow.add_node("agent", self._call_model)
        workflow.add_node("tools", ToolNode(self.tools))
        workflow.add_node("extract_and_save", self._extract_and_save_node)

        # Setup edges
        workflow.set_entry_point("agent")
        
        # Routing conditional edge
        workflow.add_conditional_edges(
            "agent",
            self._should_continue,
            {
                "tools": "tools",
                "extract_and_save": "extract_and_save"
            }
        )
        
        workflow.add_edge("tools", "agent")
        workflow.add_edge("extract_and_save", END)

        return workflow.compile()
