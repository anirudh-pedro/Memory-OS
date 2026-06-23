from enum import Enum

class RelationshipType(str, Enum):
    CREATED = "CREATED"
    USES = "USES"
    WORKS_ON = "WORKS_ON"
    PART_OF = "PART_OF"
    DEPENDS_ON = "DEPENDS_ON"
    RELATED_TO = "RELATED_TO"
    CONTRIBUTES_TO = "CONTRIBUTES_TO"
    MENTIONS = "MENTIONS"
