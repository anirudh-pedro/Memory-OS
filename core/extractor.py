import logging
import os
import json
import random
import time
from typing import Optional, Dict, Any, List
from langchain_core.prompts import ChatPromptTemplate
from core.models import GraphExtractionResult, Entity, Relationship
from core.graph_store import BaseGraphStore
from memory.quality import EntityValidator, TechnologyClassifier, ProjectClassifier
from ontology.entity_types import EntityType
from ontology.relationship_types import RelationshipType

logger = logging.getLogger(__name__)

class GraphRAGExtractor:
    def __init__(self, llm, graph_store: BaseGraphStore):
        self.llm = llm
        self.graph_store = graph_store
        self.project_classifier = ProjectClassifier(self.llm)
        
        # Make tool calling optional via config. Default is false.
        self.use_tool_calling = os.getenv("USE_TOOL_CALLING", "false").lower() == "true"
        
        # Prepare structured output model if configured
        self.structured_llm = None
        if self.use_tool_calling:
            try:
                self.structured_llm = self.llm.with_structured_output(GraphExtractionResult)
                logger.info("Structured tool calling enabled and initialized successfully.")
            except Exception as e:
                logger.warning(f"Structured output not supported directly on LLM: {e}. Falling back to raw JSON generation.")
                self.use_tool_calling = False

    def _is_retryable_error(self, err_msg: str) -> bool:
        err_msg_lower = err_msg.lower()
        # HTTP 429
        if "429" in err_msg or "rate limit" in err_msg_lower or "tpm" in err_msg_lower or "rpm" in err_msg_lower:
            return True
        # HTTP 503
        if "503" in err_msg or "service unavailable" in err_msg_lower or "overloaded" in err_msg_lower:
            return True
        # Connection errors
        if "connection" in err_msg_lower or "connect" in err_msg_lower or "dns" in err_msg_lower or "httpcore" in err_msg_lower or "httpx" in err_msg_lower or "socket" in err_msg_lower:
            return True
        # Timeout errors
        if "timeout" in err_msg_lower or "timed out" in err_msg_lower:
            return True
        return False

    def _parse_json_response(self, text: str) -> Optional[GraphExtractionResult]:
        """Strip code blocks and parse JSON response into GraphExtractionResult, attempting JSON repair if needed."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            first_newline = cleaned.find("\n")
            if first_newline != -1:
                cleaned = cleaned[first_newline:].strip()
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()

        try:
            data = json.loads(cleaned)
            return self._build_result_from_dict(data)
        except Exception as e:
            logger.warning(f"Initial JSON parse failed: {e}. Attempting JSON repair...")
            try:
                start_idx = cleaned.find("{")
                end_idx = cleaned.rfind("}")
                if start_idx != -1 and end_idx != -1:
                    repaired = cleaned[start_idx:end_idx+1]
                    data = json.loads(repaired)
                    return self._build_result_from_dict(data)
            except Exception as repair_err:
                logger.error(f"JSON repair failed: {repair_err}. Parse Failure Reason: {e}")
            return None

    def _build_result_from_dict(self, data: dict) -> GraphExtractionResult:
        """Helper to safely construct GraphExtractionResult from dictionary keys."""
        entities = []
        relationships = []
        
        raw_entities = data.get("entities", [])
        if isinstance(raw_entities, list):
            for ent in raw_entities:
                if isinstance(ent, dict) and "name" in ent and "entity_type" in ent:
                    entities.append(
                        Entity(
                            name=str(ent["name"]),
                            entity_type=str(ent["entity_type"]),
                            description=ent.get("description"),
                            aliases=ent.get("aliases", []),
                            properties=ent.get("properties", {})
                        )
                    )
                    
        raw_relationships = data.get("relationships", [])
        if isinstance(raw_relationships, list):
            for rel in raw_relationships:
                if isinstance(rel, dict) and "source_name" in rel and "target_name" in rel and "relation_type" in rel:
                    relationships.append(
                        Relationship(
                            source_name=str(rel["source_name"]),
                            target_name=str(rel["target_name"]),
                            relation_type=str(rel["relation_type"]),
                            properties=rel.get("properties", {})
                        )
                    )
                    
        return GraphExtractionResult(entities=entities, relationships=relationships)

    def extract(self, text: str) -> GraphExtractionResult:
        """Extract entities and relationships from a text block and return raw GraphExtractionResult."""
        if not text or not text.strip():
            return GraphExtractionResult(entities=[], relationships=[])

        logger.info("Extracting GraphRAG entities and relationships from text...")
        
        if self.use_tool_calling and self.structured_llm:
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
                "5. In each entity's 'properties' field, include an 'importance_score' integer from 1 to 10 (10 being crucial long-term knowledge, 1 being trivial conversational noise) and a brief 'importance_reason'.\n"
                "6. Keep descriptions concise (at most 1 sentence). Limit extraction to a maximum of 5 critical entities and 5 key relationships per text chunk to prevent token limit/truncation errors."
            )
        else:
            system_template = (
                "You are an expert knowledge graph extractor. Your job is to extract entities "
                "and their relationships from the provided text and return ONLY a valid JSON object matching the schema below.\n\n"
                "Return ONLY valid JSON.\n"
                "No markdown.\n"
                "No explanations.\n"
                "No code fences.\n"
                "No text before JSON.\n"
                "No text after JSON.\n\n"
                "JSON Schema:\n"
                "{{\n"
                '  "entities": [\n'
                "    {{\n"
                '      "name": "Normalized unique entity name (lowercase, no placeholders)",\n'
                '      "entity_type": "One of: Person, Project, Technology, Task, Document, Repository, Event, Organization, Decision, Skill",\n'
                '      "description": "Concise 1-sentence context of the entity",\n'
                '      "aliases": ["Alternative names"],\n'
                '      "properties": {{\n'
                '        "importance_score": 1-10 integer,\n'
                '        "importance_reason": "Brief reason"\n'
                "      }}\n"
                "    }}\n"
                "  ],\n"
                '  "relationships": [\n'
                "    {{\n"
                '      "source_name": "Source entity name",\n'
                '      "target_name": "Target entity name",\n'
                '      "relation_type": "One of: WORKS_ON, USES, DEPENDS_ON, MENTIONED_IN, CREATED, RELATED_TO, ATTENDS, IMPLEMENTS, CONTRIBUTES_TO, PART_OF, DISCUSSED_IN, DERIVED_FROM, MENTIONS",\n'
                '      "properties": {{}}\n'
                "    }}\n"
                "  ]\n"
                "}}\n\n"
                "Rules:\n"
                "1. ONLY extract long-term entities. Reject placeholders like '<unknown_repository>', '<owner>/<repo>', 'unknown', and conversational placeholders.\n"
                "2. Normalize names (lowercase and clean, e.g. 'kafka' instead of 'apache-kafka', 'anirudh-pedro/url-shortener' for repositories).\n"
                "3. Fill in the 'description' field with clear context detailing what the entity represents.\n"
                "4. Do not invent relationships unless clearly supported by the text.\n"
                "5. Keep descriptions concise (at most 1 sentence). Limit extraction to a maximum of 5 critical entities and 5 key relationships per text chunk to prevent token limit/truncation errors."
            )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_template),
            ("user", "Extract entities and relationships from the following text:\n\n{text}")
        ])

        if os.getenv("DEBUG", "false").lower() == "true":
            try:
                logger.info(f"DEBUG: Final Prompt:\n{prompt.format(text=text)}")
            except Exception as pe:
                logger.warning(f"Could not format/log prompt for debug: {pe}")

        if self.use_tool_calling and self.structured_llm:
            # Tool calling flow
            max_retries = 5
            base_backoff = 2.0
            result = None
            
            for attempt in range(1, max_retries + 1):
                try:
                    chain = prompt | self.structured_llm
                    result = chain.invoke({"text": text})
                    break
                except Exception as e:
                    err_msg = str(e)
                    if self._is_retryable_error(err_msg) and attempt < max_retries:
                        sleep_time = (base_backoff ** attempt) + random.uniform(0.5, 1.5)
                        logger.warning(
                            f"Groq API retryable error in tool calling (attempt {attempt}/{max_retries}): {e}. "
                            f"Retrying in {sleep_time:.2f} seconds..."
                        )
                        time.sleep(sleep_time)
                    else:
                        logger.error(f"Groq tool extraction failed after {attempt} attempts for content: {text[:100]}... Error: {e}")
                        logger.info("Extraction Success: False")
                        logger.info("Entity Count: 0")
                        logger.info("Relationship Count: 0")
                        logger.info(f"Parse Failure Reason: {err_msg}")
                        try:
                            log_dir = "logs"
                            os.makedirs(log_dir, exist_ok=True)
                            with open(os.path.join(log_dir, "extraction_failures.log"), "a", encoding="utf-8") as f:
                                f.write(f"=== FAILURE AT {time.strftime('%Y-%m-%d %H:%M:%S')} (Tool Calling) ===\n")
                                f.write(f"Parse Failure Reason: {err_msg}\n")
                                f.write("="*40 + "\n\n")
                        except Exception as log_err:
                            logger.error(f"Failed to write to extraction_failures.log: {log_err}")
                        return GraphExtractionResult(entities=[], relationships=[])
            
            if result is not None:
                logger.info("Extraction Success: True")
                logger.info(f"Entity Count: {len(result.entities)}")
                logger.info(f"Relationship Count: {len(result.relationships)}")
                logger.info("Parse Failure Reason: None")
                return result
            else:
                logger.info("Extraction Success: False")
                logger.info("Entity Count: 0")
                logger.info("Relationship Count: 0")
                logger.info("Parse Failure Reason: Empty result")
                return GraphExtractionResult(entities=[], relationships=[])

        else:
            # Raw JSON generation flow
            max_retries = 5
            base_backoff = 2.0
            raw_text = None
            
            for attempt in range(1, max_retries + 1):
                try:
                    chain = prompt | self.llm
                    resp = chain.invoke({"text": text})
                    raw_text = resp.content
                    break
                except Exception as e:
                    err_msg = str(e)
                    if self._is_retryable_error(err_msg) and attempt < max_retries:
                        sleep_time = (base_backoff ** attempt) + random.uniform(0.5, 1.5)
                        logger.warning(
                            f"Groq API retryable error (attempt {attempt}/{max_retries}): {e}. "
                            f"Retrying in {sleep_time:.2f} seconds..."
                        )
                        time.sleep(sleep_time)
                    else:
                        logger.error(f"Groq invocation failed after {attempt} attempts for content: {text[:100]}... Error: {e}")
                        logger.info("Extraction Success: False")
                        logger.info("Entity Count: 0")
                        logger.info("Relationship Count: 0")
                        logger.info(f"Parse Failure Reason: API invocation failed: {err_msg}")
                        return GraphExtractionResult(entities=[], relationships=[])
            
            if raw_text is None:
                logger.info("Extraction Success: False")
                logger.info("Entity Count: 0")
                logger.info("Relationship Count: 0")
                logger.info("Parse Failure Reason: No response content received")
                return GraphExtractionResult(entities=[], relationships=[])
                
            # Log the complete raw LLM response before parsing
            logger.info(f"RAW LLM RESPONSE:\n{raw_text}")
            
            # Parse flow
            parse_success = False
            parse_failure_reason = None
            result = None
            
            try:
                # Direct parse attempt
                data = json.loads(raw_text)
                result = self._build_result_from_dict(data)
                parse_success = True
            except Exception as e:
                # Attempt JSON repair
                parse_failure_reason = str(e)
                logger.warning(f"Initial JSON parse failed: {e}. Attempting JSON repair...")
                try:
                    cleaned = raw_text.strip()
                    # Strip markdown code blocks if present
                    if cleaned.startswith("```"):
                        first_newline = cleaned.find("\n")
                        if first_newline != -1:
                            cleaned = cleaned[first_newline:].strip()
                        if cleaned.endswith("```"):
                            cleaned = cleaned[:-3].strip()
                    
                    start_idx = cleaned.find("{")
                    end_idx = cleaned.rfind("}")
                    if start_idx != -1 and end_idx != -1:
                        repaired = cleaned[start_idx:end_idx+1]
                        data = json.loads(repaired)
                        result = self._build_result_from_dict(data)
                        parse_success = True
                        parse_failure_reason = None
                    else:
                        raise ValueError("Could not find matching curly braces for JSON repair.")
                except Exception as repair_err:
                    logger.error(f"JSON repair failed: {repair_err}. Parse Failure Reason: {e}")
                    parse_failure_reason = f"Initial: {e}; Repair: {repair_err}"
            
            if parse_success and result is not None:
                logger.info("Extraction Success: True")
                logger.info(f"Entity Count: {len(result.entities)}")
                logger.info(f"Relationship Count: {len(result.relationships)}")
                logger.info("Parse Failure Reason: None")
                return result
            else:
                # Log diagnostics for failure
                logger.info("Extraction Success: False")
                logger.info("Entity Count: 0")
                logger.info("Relationship Count: 0")
                logger.info(f"Parse Failure Reason: {parse_failure_reason}")
                
                # Save malformed responses to logs/extraction_failures.log
                try:
                    log_dir = "logs"
                    os.makedirs(log_dir, exist_ok=True)
                    with open(os.path.join(log_dir, "extraction_failures.log"), "a", encoding="utf-8") as f:
                        f.write(f"=== FAILURE AT {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                        f.write(f"Parse Failure Reason: {parse_failure_reason}\n")
                        f.write(f"Raw Response:\n{raw_text}\n")
                        f.write("="*40 + "\n\n")
                except Exception as log_err:
                    logger.error(f"Failed to write to extraction_failures.log: {log_err}")
                
                # Return empty extraction on repair fail, and do NOT retry
                return GraphExtractionResult(entities=[], relationships=[])

    def extract_and_merge(self, text: str) -> bool:
        """Extract entities and relationships from a text block and merge them into the graph store."""
        result = self.extract(text)
        if not result:
            return False

        try:
            # Upsert nodes to Graph Store
            for entity in result.entities:
                # 0. Enforce EntityType strictly
                try:
                    type_upper = str(entity.entity_type).upper()
                    if type_upper in EntityType.__members__:
                        entity.entity_type = EntityType[type_upper].value
                    else:
                        matched = False
                        for et in EntityType:
                            if et.value.lower() == str(entity.entity_type).lower():
                                entity.entity_type = et.value
                                matched = True
                                break
                        if not matched:
                            logger.info(f"Discarding entity with invalid type: '{entity.name}' ({entity.entity_type})")
                            continue
                except Exception as te:
                    logger.warning(f"Error mapping entity type '{entity.entity_type}': {te}")
                    continue

                # 1. Apply technology canonicalization
                tech_canonical = TechnologyClassifier.classify(entity.name)
                if tech_canonical:
                    entity.entity_type = EntityType.TECHNOLOGY.value
                    entity.name = tech_canonical

                # 2. Apply ProjectClassifier checks
                if entity.entity_type == EntityType.PROJECT.value:
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
                try:
                    rel_upper = str(rel.relation_type).upper()
                    if rel_upper in RelationshipType.__members__:
                        rel.relation_type = RelationshipType[rel_upper].value
                        self.graph_store.add_relationship(rel)
                    else:
                        matched = False
                        for rt in RelationshipType:
                            if rt.value.upper() == rel_upper:
                                rel.relation_type = rt.value
                                self.graph_store.add_relationship(rel)
                                matched = True
                                break
                        if not matched:
                            logger.info(f"Discarding invalid relationship type: '{rel.relation_type}' between '{rel.source_name}' and '{rel.target_name}'")
                except Exception as re:
                    logger.warning(f"Error validating relationship: {re}")
                
            logger.info(f"GraphRAG Extraction complete. Merged {len(result.entities)} entities and {len(result.relationships)} relationships.")
            return True
        except Exception as e:
            logger.error(f"Failed to extract or merge GraphRAG items: {e}")
            return False
