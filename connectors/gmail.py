import logging
from typing import List, Optional
from pydantic import BaseModel, Field
from connectors.base import BaseConnector
from core.models import Memory, Entity, Relationship

logger = logging.getLogger(__name__)

class EmailExtraction(BaseModel):
    sender: str = Field(description="Name or email address of the sender")
    topic: str = Field(description="Main topic or subject of the email")
    intent: str = Field(description="Intent of the email (e.g., status update, task request, meeting invite)")
    action_items: List[str] = Field(default_factory=list, description="Action items, tasks, or follow-ups requested")
    project_references: List[str] = Field(default_factory=list, description="Names of projects referenced (e.g. Memory-OS, DataCue)")
    people_mentioned: List[str] = Field(default_factory=list, description="Names of individuals mentioned in the email")


class GmailConnector(BaseConnector):
    def __init__(self, llm=None, graph_store=None):
        self.llm = llm
        self.graph_store = graph_store
        self.structured_llm = None
        if self.llm:
            try:
                self.structured_llm = self.llm.with_structured_output(EmailExtraction)
            except Exception as e:
                logger.warning(f"Could not initialize structured email parser: {e}")

    def sync(self, session) -> List[Memory]:
        """Fetch and normalize Gmail emails into high-value structured Memory objects."""
        logger.info("Starting Gmail memory sync...")
        memories = []
        
        try:
            # Check connection first
            toolkits_info = session.toolkits()
            gmail_tk = next((t for t in toolkits_info.items if t.slug == "gmail"), None)
            if not gmail_tk or not (gmail_tk.connection and gmail_tk.connection.is_active):
                logger.warning("Gmail connection is not active. Skipping Gmail sync.")
                return []

            response = session.execute(
                tool_slug="gmail_fetch_emails",
                arguments={"max_results": 5, "include_payload": True}
            )
            
            if not response or response.error:
                logger.error(f"Gmail sync API error: {response.error if response else 'No response'}")
                return []
                
            data = response.data or {}
            emails = data.get("messages", [])
            if not isinstance(emails, list):
                emails = data.get("response_data", {}).get("messages", [])
                if not isinstance(emails, list):
                    emails = []

            for email in emails:
                if not isinstance(email, dict):
                    continue
                msg_id = str(email.get("messageId", ""))
                if not msg_id:
                    msg_id = str(email.get("id", ""))
                    
                subject = email.get("subject", "No Subject")
                sender = email.get("sender", "") or email.get("from", "")
                date = email.get("date", "")
                body = email.get("body", "") or email.get("snippet", "")
                
                raw_content = f"From: {sender}\nDate: {date}\nSubject: {subject}\n\n{body}"
                
                # If LLM is available, perform structured metadata extraction to enrich the memory
                if self.structured_llm:
                    try:
                        logger.info(f"Running LLM email extraction for message: '{subject}'")
                        extraction: EmailExtraction = self.structured_llm.invoke(
                            f"Analyze the following email and extract structured details:\n\n{raw_content}"
                        )
                        
                        action_bullets = "\n".join([f"- [ ] {item}" for item in extraction.action_items]) if extraction.action_items else "None"
                        projects_str = ", ".join(extraction.project_references) if extraction.project_references else "None"
                        people_str = ", ".join(extraction.people_mentioned) if extraction.people_mentioned else "None"
                        
                        enriched_content = (
                            f"=== STRUCTURED EMAIL DETAILS ===\n"
                            f"From: {extraction.sender}\n"
                            f"Topic: {extraction.topic}\n"
                            f"Intent: {extraction.intent}\n"
                            f"Associated Projects: {projects_str}\n"
                            f"People: {people_str}\n"
                            f"Action Items:\n{action_bullets}\n\n"
                            f"=== EMAIL BODY ===\n"
                            f"{body}"
                        )
                        
                        metadata = email.copy()
                        metadata.update({
                            "extracted_sender": extraction.sender,
                            "extracted_topic": extraction.topic,
                            "extracted_intent": extraction.intent,
                            "extracted_action_items": extraction.action_items,
                            "extracted_projects": extraction.project_references
                        })
                        
                        # Graph updates if graph store is available
                        if self.graph_store:
                            try:
                                # 1. Create/Ensure Project nodes exist
                                for proj_name in extraction.project_references:
                                    if proj_name and proj_name.strip():
                                        proj_node = Entity(
                                            name=proj_name.strip(),
                                            entity_type="Project",
                                            description=f"Project referenced in email: '{subject}'"
                                        )
                                        self.graph_store.add_node(proj_node)

                                # 2. Create/Ensure Person nodes exist
                                if extraction.sender and extraction.sender.strip():
                                    sender_node = Entity(
                                        name=extraction.sender.strip(),
                                        entity_type="Person",
                                        description=f"Email sender from Gmail sync"
                                    )
                                    self.graph_store.add_node(sender_node)

                                for person in extraction.people_mentioned:
                                    if person and person.strip():
                                        p_node = Entity(
                                            name=person.strip(),
                                            entity_type="Person",
                                            description=f"Person mentioned in email: '{subject}'"
                                        )
                                        self.graph_store.add_node(p_node)

                                # 3. Create Task entities and links
                                for action_item in extraction.action_items:
                                    if action_item and action_item.strip():
                                        task_entity = Entity(
                                            name=action_item.strip(),
                                            entity_type="Task",
                                            description=f"Action item from email: '{extraction.topic}' (From: {extraction.sender})",
                                            properties={"status": "pending", "source": "gmail", "email_topic": extraction.topic}
                                        )
                                        self.graph_store.add_node(task_entity)

                                        # Establish relationship: Task -> PART_OF -> Project
                                        for proj_name in extraction.project_references:
                                            if proj_name and proj_name.strip():
                                                self.graph_store.add_relationship(
                                                    Relationship(
                                                        source_name=action_item.strip(),
                                                        target_name=proj_name.strip(),
                                                        relation_type="PART_OF"
                                                    )
                                                )
                                        
                                        # Establish relationship: Task -> RELATED_TO -> Sender
                                        if extraction.sender and extraction.sender.strip():
                                            self.graph_store.add_relationship(
                                                Relationship(
                                                    source_name=action_item.strip(),
                                                    target_name=extraction.sender.strip(),
                                                    relation_type="RELATED_TO"
                                                )
                                            )
                            except Exception as ge:
                                logger.warning(f"Failed to add structured email entities to graph: {ge}")

                        memories.append(
                            Memory(
                                source_app="gmail",
                                external_id=msg_id,
                                title=f"Email: {extraction.topic}",
                                content=enriched_content,
                                metadata_json=metadata
                            )
                        )
                        continue
                    except Exception as e:
                        logger.warning(f"Structured email extraction failed: {e}. Falling back to raw sync.")
                
                # Fallback to raw sync
                memories.append(
                    Memory(
                        source_app="gmail",
                        external_id=msg_id,
                        title=subject,
                        content=raw_content,
                        metadata_json=email
                    )
                )
        except Exception as e:
            logger.error(f"Failed to sync Gmail: {e}")

        logger.info(f"Successfully normalized {len(memories)} Gmail memories.")
        return memories
