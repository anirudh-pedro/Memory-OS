# Development & Contributing

## Coding Conventions

*   **Python Version**: Code is written for Python >= 3.12.
*   **Type Hinting**: Use standard Python type hinting (`from typing import List, Dict, Optional, Any`) on all function signatures.
*   **Dependency Management**: Use `uv` for managing dependencies. Add dependencies via `uv add <package>` and sync via `uv sync`.
*   **Error Handling**: Wrap external API calls (LLMs, Databases, Connectors) in `try/except` blocks and log errors using the standard `logging` module. Do not use `print()` for errors.

## Testing

Currently, Memory-OS does not have a formal `pytest` suite configured in a standard `tests/` directory.

Testing is primarily done via ad-hoc scripts located in the `scratch/` directory:
*   `scratch/test_extractor.py`: Tests the live Groq API extraction flow.
*   `scratch/test_extractor_failures.py`: Uses `unittest.mock` to simulate and test the JSON repair logic against malformed LLM responses.

*Note: Implementing a full `pytest` suite is a known piece of technical debt.*

## Debugging

*   **Logs**: Check `logs/extraction_failures.log` if GraphRAG extraction is missing entities. This file records the raw LLM responses that failed JSON parsing and repair.
*   **Database Inspection**: Use a standard SQLite viewer (like `sqlite3` CLI or DBeaver) to inspect `metadata.db` (specifically the `entities`, `relationships`, and `events` tables).
*   **Debug Mode**: Set the `DEBUG=true` environment variable to log full system prompts and LLM inputs during extraction.
