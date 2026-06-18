import logging
from typing import Optional
from langchain_core.prompts import ChatPromptTemplate
from core.models import GraphExtractionResult, Entity, Relationship
from core.graph_store import BaseGraphStore
from memory.quality import EntityValidator, TechnologyClassifier, ProjectClassifier

logger = logging.getLogger(__name__)

class GraphRAGExtractor:
    def __init__(self, llm, graph_store: BaseGraphStore):
        self.llm = llm
        self.graph_store = graph_store
        self.project_classifier = ProjectClassifier(self.llm)
        
        # Prepare structured output model
        try:
            self.structured_llm = self.llm.with_structured_output(GraphExtractionResult)
        except Exception as e:
            logger.warning(f"Structured output not supported directly on LLM: {e}. Fallback logic will be needed.")
            self.structured_llm = None

    def extract_and_merge(self, text: str) -> bool:
        """Extract entities and relationships from a text block and merge them into the graph store."""
        if not text or not text.strip():
            return False

        if not self.structured_llm:
            logger.warning("Structured output LLM not initialized. Skipping GraphRAG extraction.")
            return False

        logger.info("Extracting GraphRAG entities and relationships from text...")
        
        system_template = (
            "You are an expert knowledge graph extractor. Your job is to extract HIGH-QUALITY long-term entities "
            "and their relationships from the provided text. Reject short-term conversational artifacts, prompt structures, "
            "dialog instructions, greetings, and generic responses.\n\n"
            "Entity Types must belong strictly to:\n"
            "- Person: Names of people (e.g. 'Anirudh', 'Pedro')\n"
            "- Project: Software projects, tools, systems (e.g. 'DataCue', 'Memory-OS')\n"
            "- Technology: Libraries, frame/vector DBs, languages (e.g. 'Rust', 'Kafka', 'Qdrant')\n"
            "- Task: Long-term action items or project tasks\n"
            "- Document: Pages, notes, files, specifications\n"
            "- Repository: Git repositories (e.g. 'memory-os-api')\n"
            "- Event: Relevant meetings, milestones, schedules\n"
            "- Organization: Companies or groups\n"
            "- Decision: Design decisions, architectural choices\n"
            "- Skill: Programming or operational skills\n\n"
            "Relationship Types must belong strictly to:\n"
            "- WORKS_ON: A Person works on a Project\n"
            "- USES: A Project/Person uses a Technology or Document\n"
            "- DEPENDS_ON: A Project/Task/Tech depends on another Project/Task/Tech\n"
            "- MENTIONED_IN: An Entity is mentioned in a Document/Conversation\n"
            "- CREATED: A Person or Organization created a Project/Document/Repository\n"
            "- RELATED_TO: Generic association between two entities\n"
            "- ATTENDS: A Person attends an Event\n"
            "- IMPLEMENTS: A Project/Task implements a feature or Technology\n"
            "- CONTRIBUTES_TO: A Person/Org contributes to a Repository/Project\n"
            "- PART_OF: A Repository/Document is part of a larger Project\n"
            "- DISCUSSED_IN: An Entity or topic was discussed in a Conversation/Meeting\n"
            "- DERIVED_FROM: An Entity is derived from a parent Entity\n"
            "- MENTIONS: A Document or Event mentions another Entity\n\n"
            "Rules:\n"
            "1. ONLY extract long-term entities. Reject placeholders like '<unknown_repository>', '<owner>/<repo>', 'unknown', and conversational placeholders.\n"
            "2. Normalize names (lowercase and clean, e.g. 'kafka' instead of 'apache-kafka', 'anirudh-pedro/url-shortener' for repositories).\n"
            "3. Fill in the 'description' field with clear context detailing what the entity represents.\n"
            "4. Do not invent relationships unless clearly supported by the text.\n"
            "5. In each entity's 'properties' field, include an 'importance_score' integer from 1 to 10 (10 being crucial long-term knowledge, 1 being trivial conversational noise) and a brief 'importance_reason'."
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_template),
            ("user", "Extract entities and relationships from the following text:\n\n{text}")
        ])

        try:
            chain = prompt | self.structured_llm
            result: GraphExtractionResult = chain.invoke({"text": text})
            
            # Upsert nodes to Graph Store
            for entity in result.entities:
                # 1. Apply technology canonicalization
                tech_canonical = TechnologyClassifier.classify(entity.name)
                if tech_canonical:
                    entity.entity_type = "Technology"
                    entity.name = tech_canonical

                # 2. Apply ProjectClassifier checks
                if entity.entity_type == "Project":
                    if not self.project_classifier.is_valid_project(entity.name, entity.description or ""):
                        logger.info(f"Discarding invalid project entity during GraphRAG: '{entity.name}'")
                        continue

                # 3. Apply EntityValidator checks
                if not EntityValidator.is_valid(entity):
                    logger.info(f"Discarding invalid/conversational entity during GraphRAG: '{entity.name}' ({entity.entity_type})")
                    continue
                
                # 4. Check importance score threshold
                imp_score = entity.properties.get("importance_score")
                if imp_score is not None:
                    try:
                        if int(imp_score) < 3:
                            logger.info(f"Discarding low-importance entity: '{entity.name}' (Score: {imp_score})")
                            continue
                    except (ValueError, TypeError):
                        pass
                
                self.graph_store.add_node(entity)
                
            # Upsert relationships/edges to Graph Store, only after all valid nodes are inserted
            for rel in result.relationships:
                self.graph_store.add_relationship(rel)
                
            logger.info(f"GraphRAG Extraction complete. Merged {len(result.entities)} entities and {len(result.relationships)} relationships.")
            return True
        except Exception as e:
            logger.error(f"Failed to extract or merge GraphRAG items: {e}")
            return False
