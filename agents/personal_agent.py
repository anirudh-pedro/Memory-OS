from typing import TypedDict, Annotated, Sequence
import logging
import json
from pydantic import BaseModel, Field
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from memory.graph_manager import BaseGraphManager
from memory.retrieval_engine import RetrievalEngine
from memory.memory_manager import MessageRepository

logger = logging.getLogger(__name__)

# 1. GraphRAG Extraction Schemas
class EntityUpdate(BaseModel):
    name: str = Field(description="Unique name of the entity (e.g. 'Anirudh', 'Memory-OS', 'Rust'). Keep names concise and clean.")
    entity_type: str = Field(description="One of: Person, Project, Skill, Task, Event, Email, Repository, Document")
    properties: dict = Field(default_factory=dict, description="Any extra metadata context like URL, date, description, etc.")

class RelationshipUpdate(BaseModel):
    source_name: str = Field(description="Exact name of the source entity node")
    target_name: str = Field(description="Exact name of the target entity node")
    relation_type: str = Field(description="One of: OWNS, USES, CREATED, ATTENDS, RELATED_TO, DEPENDS_ON, WORKS_ON")

class GraphExtraction(BaseModel):
    entities: list[EntityUpdate] = Field(default_factory=list, description="List of entities to upsert")
    relationships: list[RelationshipUpdate] = Field(default_factory=list, description="List of graph connections to link")


# 2. Agent State Definitions
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    thread_id: str


# 3. Agent Builder Class
class MemoryAgentBuilder:
    def __init__(self, llm, tools: list[BaseTool], message_repo: MessageRepository, graph_manager: BaseGraphManager, retrieval_engine: RetrievalEngine):
        self.llm = llm
        self.tools = tools
        self.message_repo = message_repo
        self.graph_manager = graph_manager
        self.retrieval_engine = retrieval_engine
        
        # Prepare structured output model for extraction
        try:
            self.extractor_llm = self.llm.with_structured_output(GraphExtraction)
        except Exception as e:
            logger.warning(f"Structured output not supported directly on LLM: {e}. Fallback extraction template will be used.")
            self.extractor_llm = None

    def _should_continue(self, state: AgentState):
        """Routing logic: determine if tools need to be called, or if execution can end."""
        last_message = state["messages"][-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return "extract_and_save"

    def _call_model(self, state: AgentState):
        """Pre-processes inputs, retrieves relevant local memory, and invokes the chat model."""
        messages = state["messages"]
        thread_id = state.get("thread_id", "default")

        # 1. Find the last user input text to build local retrieval context
        last_user_query = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_user_query = str(msg.content)
                break

        # 2. Build local context block from FTS and SQLite Graph database
        retrieved_context = "No relevant context found in local memory."
        if last_user_query:
            retrieved_context = self.retrieval_engine.build_context(last_user_query)

        # 3. Define dynamic system prompt containing the retrieved memory context placeholder
        system_template = (
            "You are Memory-OS, a proactive personal assistant digital brain with access to the user's workspace caches "
            "(GitHub, Notion, Google Calendar) and semantic memories.\n\n"
            "Here is the RETRIEVED CONTEXT from your local database matches:\n"
            "--------------------------------------------------\n"
            "{retrieved_context}\n"
            "--------------------------------------------------\n\n"
            "GUIDELINES:\n"
            "- Be extremely proactive! If the user asks about repositories, issues, projects, or calendar events and you do not have the info in the RETRIEVED CONTEXT, do NOT ask the user for details (such as username, owner, or repository name) right away. Instead, immediately call the tools (e.g. GITHUB_GET_THE_AUTHENTICATED_USER, GITHUB_LIST_REPOSITORIES_FOR_THE_AUTHENTICATED_USER) to discover the details automatically.\n"
            "- Once you discover the authenticated user's name or repositories, use them as the default arguments for any subsequent actions (like listing projects or creating issues) without asking the user.\n"
            "- For any actions that modify state on external platforms (such as creating issues, creating repositories, or sending emails), ALWAYS ask the user for explicit confirmation (e.g. 'Shall I proceed with creating this issue?') before invoking the tool, unless the user has already explicitly instructed you to proceed.\n"
            "- Answer using the retrieved context when possible. If the context contains details about a repository, user, or event, leverage it.\n"
            "- When executing tool calls: IMPORTANT - Do NOT pass 'null' or null values for optional tool parameters in JSON schema. Omit them entirely if not set.\n"
            "- Keep your answers concise, clean, and helpful."
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_template),
            MessagesPlaceholder(variable_name="messages")
        ])

        # Truncate content of any history message (especially ToolMessages with huge JSON payloads) to max 1000 chars
        import copy
        truncated_messages = []
        for msg in messages[-5:]:
            content_str = str(msg.content) if msg.content else ""
            if len(content_str) > 1000:
                msg_copy = copy.copy(msg)
                msg_copy.content = content_str[:1000] + "\n... [truncated due to length context limit] ..."
                truncated_messages.append(msg_copy)
            else:
                truncated_messages.append(msg)

        # Invoke model using the safe conversation history window
        chain = prompt | self.llm.bind_tools(self.tools)
        response = chain.invoke({
            "messages": truncated_messages,
            "retrieved_context": retrieved_context
        })
        
        return {"messages": [response]}

    def _extract_and_save_node(self, state: AgentState):
        """Post-processes conversational turns, extracts entities/relations, and persists messages and graph nodes."""
        messages = state["messages"]
        thread_id = state.get("thread_id", "default")
        
        # 1. Save messages to messages database (conversational log)
        # Find new messages that aren't already logged
        logged_msgs = self.message_repo.get_messages(thread_id)
        logged_contents = {m["content"] for m in logged_msgs}
        
        for msg in messages:
            if msg.content and str(msg.content) not in logged_contents:
                role = "user" if isinstance(msg, HumanMessage) else "assistant"
                self.message_repo.save_message(
                    thread_id=thread_id,
                    role=role,
                    content=str(msg.content),
                    metadata={"class": msg.__class__.__name__}
                )

        # 2. Extract Entities and Relationships using LLM Structured Output
        last_turn_text = ""
        # Get last user message and assistant reply to extract context
        user_msgs = [m for m in messages if isinstance(m, HumanMessage)]
        ai_msgs = [m for m in messages if isinstance(m, AIMessage)]
        if user_msgs:
            last_turn_text += f"User: {user_msgs[-1].content}\n"
        if ai_msgs:
            last_turn_text += f"Assistant: {ai_msgs[-1].content}\n"

        if last_turn_text:
            try:
                if self.extractor_llm:
                    extraction_prompt = (
                        "Extract key entities and relationships from the following conversation turn.\n"
                        "Entities should belong to: Person, Project, Skill, Task, Event, Email, Repository, Document.\n"
                        "Relationships should belong to: OWNS, USES, CREATED, ATTENDS, RELATED_TO, DEPENDS_ON, WORKS_ON.\n\n"
                        f"{last_turn_text}"
                    )
                    extraction = self.extractor_llm.invoke(extraction_prompt)
                    
                    # Persist nodes
                    for ent in extraction.entities:
                        self.graph_manager.add_node(
                            entity_type=ent.entity_type,
                            name=ent.name,
                            properties=ent.properties
                        )
                        
                    # Persist edges
                    for rel in extraction.relationships:
                        self.graph_manager.add_relationship(
                            source_name=rel.source_name,
                            target_name=rel.target_name,
                            relation_type=rel.relation_type
                        )
            except Exception as e:
                logger.error(f"Failed during entity extraction: {e}")

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
