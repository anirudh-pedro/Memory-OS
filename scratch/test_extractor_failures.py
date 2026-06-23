import os
import sys
import logging
import json
from dotenv import load_dotenv
from unittest.mock import MagicMock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.extractor import GraphRAGExtractor
from core.models import GraphExtractionResult

class MockResponse:
    def __init__(self, content):
        self.content = content

def test_failures_and_repair():
    logging.basicConfig(level=logging.INFO)
    
    # 1. Clean existing logs
    log_file = "logs/extraction_failures.log"
    if os.path.exists(log_file):
        os.remove(log_file)
        
    # Setup mock LLM
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = None
    
    # 3 mock responses
    responses = [
        MockResponse('{"entities": [{"name": "anirudh", "entity_type": "Person", "description": "dev"}]}'),
        MockResponse('Here is the JSON you requested:\n```json\n{"entities": [{"name": "pedro", "entity_type": "Person", "description": "co-dev"}]}\n```\nHope this helps!'),
        MockResponse('Sorry, I cannot help with that query. This is a generic response error.')
    ]
    
    call_index = 0
    def side_effect(*args, **kwargs):
        nonlocal call_index
        val = responses[call_index]
        return val

    mock_llm.side_effect = side_effect
    mock_llm.invoke.side_effect = side_effect
    
    # Make GraphRAGExtractor
    extractor = GraphRAGExtractor(mock_llm, None)
    # Ensure tool calling is disabled for raw JSON tests
    extractor.use_tool_calling = False
    
    # Test Case 1: Clean JSON
    print("\n--- Test Case 1: Clean JSON ---")
    res1 = extractor.extract("test 1")
    assert len(res1.entities) == 1
    assert res1.entities[0].name == "anirudh"
    print("Test Case 1 Passed!")
    
    # Increment call index for next test
    call_index += 1
    
    # Test Case 2: JSON with markdown formatting & repair
    print("\n--- Test Case 2: Markdown & Repair ---")
    res2 = extractor.extract("test 2")
    assert len(res2.entities) == 1
    assert res2.entities[0].name == "pedro"
    print("Test Case 2 Passed!")
    
    # Increment call index for next test
    call_index += 1
    
    # Test Case 3: Completely malformed JSON (should not retry, call_count should only increment by 1)
    print("\n--- Test Case 3: Malformed Response (No Retry) ---")
    initial_calls = call_index
    res3 = extractor.extract("test 3")
    assert len(res3.entities) == 0
    assert len(res3.relationships) == 0
    print("Test Case 3 Passed (No Retry occurred on parse failure)!")
    
    # Verify that logs/extraction_failures.log has been written to
    assert os.path.exists(log_file), "Log file should exist"
    with open(log_file, "r") as f:
        log_content = f.read()
    assert "Sorry, I cannot help with that query" in log_content
    print("Log file verified successfully!")
    print("\nAll unit tests passed successfully!")

if __name__ == "__main__":
    test_failures_and_repair()
