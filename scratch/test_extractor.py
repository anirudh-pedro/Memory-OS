import os
import sys
from dotenv import load_dotenv

# Adjust Python path to load modules from root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import DatabaseConnectionManager
from core.graph_store import SQLiteGraphStore
from core.extractor import GraphRAGExtractor
from langchain_groq import ChatGroq

def extract_entities(content: str):
    """Wrapper matching user request to test extraction completes without throwing."""
    load_dotenv()
    db_manager = DatabaseConnectionManager(db_path="metadata.db")
    graph_store = SQLiteGraphStore("metadata.db")
    llm = ChatGroq(
        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.0
    )
    extractor = GraphRAGExtractor(llm, graph_store)
    
    # Enable debug logging of prompt
    os.environ["DEBUG"] = "true"
    # Test tool-calling disabled flow
    os.environ["USE_TOOL_CALLING"] = "false"
    
    logger = logging.getLogger("test_extractor")
    logger.setLevel(logging.INFO)
    
    print(f"Running extract_entities on: '{content}'")
    result = extractor.extract(content)
    print("Successful extraction run!")
    print(f"Entities extracted: {len(result.entities)}")
    print(f"Relationships extracted: {len(result.relationships)}")
    return result

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    extract_entities("Anirudh is a developer working on Memory-OS system using React.")
