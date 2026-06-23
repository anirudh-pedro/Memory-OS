# Reference: Ontology

Memory-OS restricts the extraction of entities and relationships to a strict ontology to ensure a clean, queryable knowledge graph.

## Entity Types (`ontology/entity_types.py`)

*   **Person**: Names of people.
*   **Project**: Software projects, tools, systems.
*   **Technology**: Libraries, databases, frameworks, languages.
*   **Task**: Long-term action items or project tasks.
*   **Document**: Pages, notes, files, specifications.
*   **Repository**: Git repositories.
*   **Event**: Relevant meetings, milestones, schedules.
*   **Organization**: Companies or groups.
*   **Decision**: Design decisions, architectural choices.
*   **Skill**: Programming or operational skills.

## Relationship Types (`ontology/relationship_types.py`)

*   **WORKS_ON**: A Person works on a Project.
*   **USES**: A Project/Person uses a Technology or Document.
*   **DEPENDS_ON**: A Project/Task/Tech depends on another Project/Task/Tech.
*   **MENTIONED_IN**: An Entity is mentioned in a Document/Conversation.
*   **CREATED**: A Person or Organization created a Project/Document/Repository.
*   **RELATED_TO**: Generic association between two entities.
*   **ATTENDS**: A Person attends an Event.
*   **IMPLEMENTS**: A Project/Task implements a feature or Technology.
*   **CONTRIBUTES_TO**: A Person/Org contributes to a Repository/Project.
*   **PART_OF**: A Repository/Document is part of a larger Project.
*   **DISCUSSED_IN**: An Entity or topic was discussed in a Conversation/Meeting.
*   **DERIVED_FROM**: An Entity is derived from a parent Entity.
*   **MENTIONS**: A Document or Event mentions another Entity.
