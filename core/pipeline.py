import logging
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from core.models import Memory, MemoryChunk, Entity, Relationship
from core.db import DatabaseConnectionManager
from core.embeddings import BaseEmbedder
from core.vector_store import QdrantVectorStore
from core.graph_store import BaseGraphStore, Neo4jGraphStore
from memory.events import EventStore, EventType
from memory.quality import MemoryQualityPipeline, EntityValidator, TechnologyClassifier

logger = logging.getLogger(__name__)

class IngestionPipeline:
    def __init__(self, db_manager: DatabaseConnectionManager, vector_store: QdrantVectorStore, embedder: BaseEmbedder, graph_store: BaseGraphStore = None, extractor = None):
        self.db_manager = db_manager
        self.vector_store = vector_store
        self.embedder = embedder
        self.graph_store = graph_store
        self.extractor = extractor

    @staticmethod
    def _score_memory(title: str, content: str) -> tuple[int, str]:
        """Simple inline memory importance scorer replacing deprecated memory/importance.py."""
        title_lower = title.lower()
        content_lower = content.lower()

        if "created memory-os" in title_lower or "created memory-os" in content_lower:
            return 10, "Core PKOS system creation milestone"
        if "architecture decision" in title_lower or "design decision" in title_lower or "architecture decision" in content_lower:
            return 9, "Critical system architectural or design decision"
        if "milestone" in title_lower or "milestone" in content_lower or "release" in title_lower:
            return 8, "Key project development milestone or release"
        if "repository created" in title_lower or "repo created" in title_lower or "create repo" in title_lower:
            return 7, "Repository creation metadata"
        if "github" in title_lower or "pull request" in title_lower or "pr #" in title_lower or "issue #" in title_lower:
            return 6, "Git version control PR, issue, or code change"
        if "notion" in title_lower:
            return 4, "Workspace documentation page"
        if "calendar" in title_lower or "appointment" in title_lower or "meeting" in title_lower:
            return 3, "Calendar meeting/event schedule"
        if "email" in title_lower or "gmail" in title_lower or "from:" in content_lower:
            return 2, "General communication context"
        if "reminder" in title_lower or "todo" in title_lower:
            return 1, "Generic task reminder"
        return 2, "Workspace memory metadata"

    def chunk_text(self, text: str, chunk_size: int = 800, overlap: int = 100) -> List[str]:
        """Split text into overlapping chunks of rough size."""
        if not text:
            return []
            
        paragraphs = text.split("\n\n")
        chunks = []
        current_chunk = ""
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            if len(current_chunk) + len(para) <= chunk_size:
                current_chunk += ("\n\n" if current_chunk else "") + para
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                # If paragraph itself is too large, split it by characters
                if len(para) > chunk_size:
                    start = 0
                    while start < len(para):
                        end = start + chunk_size
                        chunks.append(para[start:end])
                        start += chunk_size - overlap
                    current_chunk = ""
                else:
                    current_chunk = para
                    
        if current_chunk:
            chunks.append(current_chunk)
            
        return chunks

    def upsert_memory_to_db(self, memory: Memory) -> int:
        """Saves memory to SQLite workspace_cache table, triggers event logging, and returns the rowid."""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        # Calculate memory importance score
        score, reason = self._score_memory(memory.title, memory.content)
        memory.metadata_json["importance_score"] = score
        memory.metadata_json["importance_reason"] = reason

        # Log event sourcing layer event
        try:
            event_store = EventStore(self.db_manager.db_path)
            event_store.log_event(
                EventType.MEMORY_INGESTED,
                memory.title,
                {"source_app": memory.source_app, "importance_score": score, "importance_reason": reason}
            )
        except Exception as ee:
            logger.warning(f"Failed to log memory ingestion event: {ee}")

        try:
            cursor.execute(
                """
                INSERT INTO workspace_cache (source_app, external_id, title, content, metadata_json, last_synced, importance_score, importance_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_app, external_id) DO UPDATE SET
                    title = excluded.title,
                    content = excluded.content,
                    metadata_json = excluded.metadata_json,
                    last_synced = excluded.last_synced,
                    importance_score = excluded.importance_score,
                    importance_reason = excluded.importance_reason
                RETURNING id
                """,
                (
                    memory.source_app,
                    memory.external_id,
                    memory.title,
                    memory.content,
                    json.dumps(memory.metadata_json),
                    memory.last_synced.isoformat(),
                    score,
                    reason
                )
            )
            row = cursor.fetchone()
            if row:
                row_id = row[0]
            else:
                # Fallback if RETURNING is not supported or returning empty
                cursor.execute(
                    "SELECT id FROM workspace_cache WHERE source_app = ? AND external_id = ?",
                    (memory.source_app, memory.external_id)
                )
                row_id = cursor.fetchone()[0]
            conn.commit()
            return row_id
        except Exception as e:
            logger.error(f"Failed to upsert memory {memory.title} to database: {e}")
            raise e
        finally:
            conn.close()

    def run_ingestion(self, memories: List[Memory], rebuild: bool = False) -> int:
        """Run standard pipeline for a list of normalized Memory objects:
        1. Save to SQLite database first
        2. Fit embedder (only if rebuild=True) and initialize Qdrant collection
        3. Extract graph entities using GraphRAGExtractor (if available)
        4. Validate and resolve entities via SQLite Quality Pipeline
        5. Sync resolved entities and relationships into Neo4j (if Neo4j is configured)
        6. Chunk text content, embed, and upsert chunks into Qdrant
        7. Run quality consolidation
        Returns the number of memories ingested.
        """
        if not memories:
            logger.info("No memories provided for ingestion.")
            return 0

        logger.info(f"Starting pipeline ingestion for {len(memories)} memories...")
        
        # 1. Save/Update all memories in SQLite DB & compute importance scores
        memory_ids = []
        for memory in memories:
            try:
                memory_id = self.upsert_memory_to_db(memory)
                memory_ids.append((memory, memory_id))
            except Exception as e:
                logger.error(f"Failed to save memory '{memory.title}' to DB: {e}")

        # 2. Fit embedder if rebuild is True
        if rebuild:
            all_docs = []
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT title, content FROM workspace_cache")
            for row in cursor.fetchall():
                all_docs.append(f"{row['title']} {row['content']}")
            conn.close()

            logger.info(f"Fitting TF-IDF embedder on combined database corpus of {len(all_docs)} documents...")
            self.embedder.fit(all_docs)
        else:
            logger.info("Reusing existing embedder vocabulary (rebuild=False).")
        
        vocab_size = len(self.embedder.vocabulary)
        dimension = vocab_size if vocab_size > 0 else 1
        
        # Initialize vector collection to match updated vocabulary dimension
        self.vector_store.initialize_collection(dimension=dimension, embedder=self.embedder)

        # 3. Process extraction and semantic indexing for the memories
        ingested_count = 0
        all_chunks = []
        
        # Prepare quality pipeline
        quality_pipeline = MemoryQualityPipeline(self.db_manager, self.graph_store)

        for memory, memory_id in memory_ids:
            try:
                # Step A: Run GraphRAG extractor to parse entities/relationships
                if self.extractor and self.graph_store:
                    try:
                        logger.info(f"Running GraphRAG extraction on content of '{memory.title}'")
                        extraction_res = self.extractor.extract(memory.content)
                        if extraction_res:
                            # Validate, resolve and merge in SQLite first
                            resolved_names_map = {}
                            for entity in extraction_res.entities:
                                # Apply basic type check / canonical type validation before passing to quality pipeline
                                from ontology.entity_types import EntityType
                                try:
                                    type_upper = str(entity.entity_type).upper()
                                    if type_upper in EntityType.__members__:
                                        entity.entity_type = EntityType[type_upper].value
                                except Exception:
                                    pass

                                # Apply importance threshold
                                imp_score = entity.properties.get("importance_score")
                                if imp_score is not None:
                                    try:
                                        if int(imp_score) < 3:
                                            continue
                                    except (ValueError, TypeError):
                                        pass

                                original_name = entity.name
                                # Run validation / resolution
                                sqlite_id = quality_pipeline.process_entity(entity, source=memory.source_app)
                                if sqlite_id != -1:
                                    # Entity was successfully validated and resolved (its name might have been updated/canonicalized)
                                    resolved_names_map[original_name] = entity.name
                                    
                                    # Write/Sync resolved node to Neo4j if graph_store is Neo4j
                                    if isinstance(self.graph_store, Neo4jGraphStore):
                                        entity.properties["last_synced"] = memory.last_synced.isoformat()
                                        self.graph_store.add_node(entity)

                            # Resolve and add relationships
                            for rel in extraction_res.relationships:
                                # Update relationship source/target names based on resolved entity names
                                if rel.source_name in resolved_names_map:
                                    rel.source_name = resolved_names_map[rel.source_name]
                                if rel.target_name in resolved_names_map:
                                    rel.target_name = resolved_names_map[rel.target_name]

                                # Verify relationship types
                                from ontology.relationship_types import RelationshipType
                                try:
                                    rel_upper = str(rel.relation_type).upper()
                                    if rel_upper in RelationshipType.__members__:
                                        rel.relation_type = RelationshipType[rel_upper].value
                                except Exception:
                                    continue

                                # Write relationship to graph stores
                                self.graph_store.add_relationship(rel)

                    except Exception as ge:
                        logger.warning(f"GraphRAG extraction/merging failed for '{memory.title}': {ge}")

                # Step B: Segment content into chunks
                text_chunks = self.chunk_text(memory.content)
                if not text_chunks:
                    text_chunks = [memory.title]

                # Step C: Prepare chunks and embed them
                vectors = self.embedder.embed_documents(text_chunks)
                for i, text in enumerate(text_chunks):
                    all_chunks.append(
                        MemoryChunk(
                            chunk_id=f"wc_{memory_id}_{i}",
                            memory_id=memory_id,
                            text=text,
                            vector=vectors[i],
                            metadata={
                                "source_app": memory.source_app,
                                "external_id": memory.external_id,
                                "type": "workspace_cache",
                                "title": memory.title,
                                "importance_score": memory.metadata_json.get("importance_score", 1),
                                "importance_reason": memory.metadata_json.get("importance_reason", ""),
                                "last_synced": memory.last_synced.isoformat()
                            }
                        )
                    )
                ingested_count += 1
            except Exception as e:
                logger.error(f"Failed to ingest memory '{memory.title}': {e}")

        # Step D: Bulk upsert to Qdrant vector store
        if all_chunks:
            logger.info(f"Upserting {len(all_chunks)} semantic chunks to Qdrant vector store...")
            self.vector_store.upsert_chunks(all_chunks)

        # Step E: Trigger memory consolidation & project auto-detection
        if self.graph_store:
            try:
                logger.info("Executing MemoryQualityPipeline service checks...")
                quality_pipeline.run_full_consolidation()
            except Exception as ex:
                logger.error(f"Failed to run memory consolidations: {ex}")

        logger.info(f"Ingestion pipeline run completed. Successfully processed {ingested_count} memories.")
        return ingested_count
