"""
Command: memory-os ask

Queries the RAG pipeline with a question.
"""

import sys
import sqlite3
from core.llm import run_hybrid_rag
from storage.db import init_db


def run_and_print_ask(query: str):
    """Run RAG query pipeline and print the structured result blocks."""
    rag_res = run_hybrid_rag(query)
    
    print("========================================")
    print("ANSWER")
    print("========================================")
    print(rag_res["answer"])
    print("\n========================================")
    print("SOURCES")
    print("========================================")
    if rag_res.get("sources"):
        for s in rag_res["sources"]:
            print(f"- {s}")
    else:
        print("None")
    print("\n========================================")
    print("REPOSITORIES USED")
    print("========================================")
    if rag_res.get("repositories"):
        for r in rag_res["repositories"]:
            print(f"- {r}")
    else:
        print("None")
    print("\n========================================")
    confidence = rag_res.get("confidence", 0.0)
    print(f"Confidence: {confidence:.2f}")
    print("========================================")


def execute(args):
    """Run the ask command parser handler."""
    # Ensure database is initialized
    try:
        init_db()
    except sqlite3.OperationalError as e:
        print("----------------------------------")
        print("Workspace has not been initialized.")
        print("")
        print("Run:")
        print("memory-os init")
        print("----------------------------------")
        sys.exit(1)

    if not args.question:
        print("Usage: memory-os ask <question>")
        sys.exit(1)

    query = " ".join(args.question)
    
    try:
        run_and_print_ask(query)
    except Exception as e:
        print(f"❌ Error executing query: {e}")
        sys.exit(1)
