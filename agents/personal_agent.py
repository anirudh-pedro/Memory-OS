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
from typing import Optional

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    thread_id: str
    pending_action: Optional[dict]


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

        # Check if there is a pending action in the state
        pending = state.get("pending_action")
        if pending:
            # Find the user's latest response to the pending action proposal
            user_msg = ""
            for msg in reversed(messages):
                if isinstance(msg, HumanMessage):
                    user_msg = str(msg.content).strip().lower().strip(".,!?;:")
                    break
            
            confirm_words = {"yes", "proceed", "confirm", "do it", "go ahead", "sure", "okay"}
            cancel_words = {"no", "cancel", "stop", "never mind"}
            
            action_mapping = {
                "github_create_an_issue": "Create a GitHub issue",
                "GITHUB_CREATE_AN_ISSUE": "Create a GitHub issue",
                "notion_create_notion_page": "Create a Notion page",
                "NOTION_CREATE_NOTION_PAGE": "Create a Notion page",
                "googlecalendar_create_event": "Create a Calendar event",
                "GOOGLECALENDAR_CREATE_EVENT": "Create a Calendar event",
                "googlecalendar_quick_add": "Quick add a Calendar event",
                "GOOGLECALENDAR_QUICK_ADD": "Quick add a Calendar event",
                "gmail_send_email": "Send an email",
                "GMAIL_SEND_EMAIL": "Send an email",
                "notion_append_text_blocks": "Append content to Notion page",
                "NOTION_APPEND_TEXT_BLOCKS": "Append content to Notion page"
            }
            
            if user_msg in confirm_words:
                from langchain_core.messages import AIMessage
                # Construct tool call message using the pending action details
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
                from langchain_core.messages import AIMessage
                ai_msg = AIMessage(content="❌ Action cancelled.")
                logger.info(f"User cancelled action: {pending['tool_name']}")
                return {
                    "messages": [ai_msg],
                    "pending_action": None
                }
            else:
                from langchain_core.messages import AIMessage
                action_desc = action_mapping.get(pending["tool_name"], pending["tool_name"])
                ai_msg = AIMessage(
                    content=(
                        f"⚠️ There is a pending action:\n"
                        f"Proposed Action:\n"
                        f"{action_desc}\n\n"
                        f"Please reply with 'yes' to proceed, or 'no' to cancel."
                    )
                )
                return {
                    "messages": [ai_msg]
                }

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
            "You are Memory-OS, an intelligent personal memory assistant. Your primary responsibility is to help "
            "the user retrieve, organize, connect, and reason over their personal knowledge.\n\n"
            "Here is the RETRIEVED CONTEXT from your local database matches:\n"
            "--------------------------------------------------\n"
            "{retrieved_context}\n"
            "--------------------------------------------------\n\n"
            "CORE PRINCIPLES:\n"
            "1. Memory First: Before answering, always reason using available memories, retrieved documents, graph relationships, and conversation history.\n"
            "2. Knowledge Synthesis: Do not simply repeat retrieved information. Combine information from multiple memories to provide concise and useful answers.\n"
            "3. Relationship Awareness: Understand relationships between projects, technologies, tasks, people, organizations, and documents. Explain connections when relevant.\n"
            "4. Retrieval Preference: Use info in this order: (a) retrieved memory context, (b) knowledge graph, (c) current conversation, (d) general world knowledge. Never ignore relevant memory context.\n"
            "5. Proactive Discovery: If required information is missing, do not immediately ask the user if tools are available to search/fetch it (e.g. GITHUB_GET_THE_AUTHENTICATED_USER, GITHUB_LIST_REPOSITORIES_FOR_THE_AUTHENTICATED_USER).\n"
            "6. Action Safety & Confirmation Rules:\n"
            "   - Before performing any action that changes state (Notion pages, GitHub repositories/issues, emails, calendar events, tasks, etc.):\n"
            "     a) Gather all required parameters.\n"
            "     b) Generate a structured pending action.\n"
            "     c) Ask the user for confirmation. DO NOT call any tool in this turn. ALWAYS use this format:\n\n"
            "Proposed Action:\n"
            "[action description]\n\n"
            "Would you like me to proceed?\n\n"
            "   - After a pending action exists, if the user's next message is a confirmation (e.g., 'yes', 'proceed', 'confirm', 'do it', 'go ahead', 'sure', 'okay'):\n"
            "     * DO NOT start a new conversation, perform memory retrieval, perform unrelated reasoning, or ask unrelated questions.\n"
            "     * Instead, immediately execute the exact pending action using the appropriate tool.\n"
            "     * Wait for the tool result and report success/failure.\n"
            "   - If the user replies with a cancellation (e.g., 'no', 'cancel', 'stop', 'never mind'):\n"
            "     * Cancel and clear the pending action.\n"
            "     * Inform the user that the action was cancelled.\n"
            "   - A confirmation response must always be interpreted as a response to the current pending action if one exists.\n"
            "   - A confirmation response must never trigger unrelated memory retrieval or tool usage.\n"
            "   - Pending actions have higher priority than all other instructions.\n"
            "7. Context Management: Focus on high-signal information. Avoid overwhelming raw data. Summarize when appropriate.\n"
            "8. Transparency: Distinguish memory-based facts from assumptions. If no memory exists or info is uncertain, state that explicitly.\n"
            "9. Tool Execution Rules: Do NOT pass 'null' or null values for optional tool parameters in JSON schema. Omit them entirely.\n"
            "10. Response Style: Concise, organized, analytical, using bullet points and structured reasoning."
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
        
        # Intercept state-changing tool calls
        STATE_CHANGING_TOOLS = {
            "github_create_an_issue", "GITHUB_CREATE_AN_ISSUE",
            "github_create_a_repository_for_the_authenticated_user", "GITHUB_CREATE_A_REPOSITORY_FOR_THE_AUTHENTICATED_USER",
            "googlecalendar_create_event", "GOOGLECALENDAR_CREATE_EVENT",
            "googlecalendar_quick_add", "GOOGLECALENDAR_QUICK_ADD",
            "notion_create_notion_page", "NOTION_CREATE_NOTION_PAGE",
            "notion_append_text_blocks", "NOTION_APPEND_TEXT_BLOCKS",
            "gmail_send_email", "GMAIL_SEND_EMAIL"
        }
        
        has_state_changing_tool = False
        target_tool_call = None
        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                if tc["name"] in STATE_CHANGING_TOOLS:
                    has_state_changing_tool = True
                    target_tool_call = tc
                    break
                    
        if has_state_changing_tool:
            from langchain_core.messages import AIMessage
            action_mapping = {
                "github_create_an_issue": "Create a GitHub issue",
                "GITHUB_CREATE_AN_ISSUE": "Create a GitHub issue",
                "notion_create_notion_page": "Create a Notion page",
                "NOTION_CREATE_NOTION_PAGE": "Create a Notion page",
                "googlecalendar_create_event": "Create a Calendar event",
                "GOOGLECALENDAR_CREATE_EVENT": "Create a Calendar event",
                "googlecalendar_quick_add": "Quick add a Calendar event",
                "GOOGLECALENDAR_QUICK_ADD": "Quick add a Calendar event",
                "gmail_send_email": "Send an email",
                "GMAIL_SEND_EMAIL": "Send an email",
                "notion_append_text_blocks": "Append content to Notion page",
                "NOTION_APPEND_TEXT_BLOCKS": "Append content to Notion page"
            }
            
            action_desc = action_mapping.get(target_tool_call["name"], f"Execute {target_tool_call['name']}")
            
            # Format parameters
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
