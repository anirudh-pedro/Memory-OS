from enum import Enum

class EntityType(str, Enum):
    PERSON = "Person"
    PROJECT = "Project"
    REPOSITORY = "Repository"
    TECHNOLOGY = "Technology"
    DOCUMENT = "Document"
    TASK = "Task"
    ORGANIZATION = "Organization"
    EVENT = "Event"
