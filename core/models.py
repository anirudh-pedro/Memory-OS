from datetime import datetime
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

class Memory(BaseModel):
    id: Optional[int] = None
    source_app: str = Field(..., description="E.g., github, gmail, notion, googlecalendar, conversation")
    external_id: str = Field(..., description="Unique ID in the source system")
    title: str = Field(..., description="Standardized title summarizing the memory")
    content: str = Field(..., description="Raw text or formatted markdown of the resource content")
    metadata_json: Dict[str, Any] = Field(default_factory=dict, description="Original API response or raw properties")
    last_synced: datetime = Field(default_factory=datetime.now)

class MemoryChunk(BaseModel):
    chunk_id: str
    memory_id: int
    text: str
    vector: Optional[List[float]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class Entity(BaseModel):
    name: str = Field(..., description="Unique, normalized name of the entity")
    entity_type: str = Field(..., description="One of: Person, Project, Task, Technology, Document, Conversation, Event, Organization, Repository")
    description: Optional[str] = Field(None, description="Extracted brief summary or context")
    aliases: List[str] = Field(default_factory=list, description="Alternative names for this entity used for resolution")
    properties: Dict[str, Any] = Field(default_factory=dict)

class Relationship(BaseModel):
    source_name: str
    target_name: str
    relation_type: str = Field(..., description="One of: WORKS_ON, USES, DEPENDS_ON, MENTIONED_IN, CREATED, RELATED_TO, ATTENDS")
    properties: Dict[str, Any] = Field(default_factory=dict)

class GraphExtractionResult(BaseModel):
    entities: List[Entity] = Field(default_factory=list)
    relationships: List[Relationship] = Field(default_factory=list)
