import os
import time
import logging
from groq import Groq
from core.vector_store import hybrid_search
from storage.graph import GraphStore

logger = logging.getLogger("llm")

_current_key_idx = 0

def get_groq_client_and_key():
    global _current_key_idx
    keys = []
    
    key1 = os.getenv("GROQ_API_KEY_1")
    key2 = os.getenv("GROQ_API_KEY_2")
    if key1:
        keys.append(key1)
    if key2:
        keys.append(key2)
        
    if not keys:
        fallback = os.getenv("GROQ_API_KEY")
        if fallback:
            keys.append(fallback)
            
    if not keys:
        raise ValueError("No Groq API keys found. Please set GROQ_API_KEY_1, GROQ_API_KEY_2, or GROQ_API_KEY.")
        
    selected_key = keys[_current_key_idx % len(keys)]
    return Groq(api_key=selected_key), selected_key

def rotate_groq_key():
    global _current_key_idx
    _current_key_idx += 1
    logger.info("Rotated Groq API key.")

def query_llm_with_retry(messages: list, model: str = None, max_retries: int = 3) -> str:
    if not model:
        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    # Map legacy/unsupported model names to supported ones on Groq
    mapped_model = model
    if "/" in model:
        mapped_model = model.split("/")[-1]
    
    # Groq does not host gpt-oss-120b. Map it to a supported model.
    if mapped_model in ["gpt-oss-120b", "openai/gpt-oss-120b", "openai-gpt-oss-120b"]:
        mapped_model = "llama-3.3-70b-versatile"

    # Make sure we don't crash if the mapped model is completely invalid
    fallback_models = ["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "llama-3.1-8b-instant"]

    for attempt in range(max_retries):
        try:
            client, key = get_groq_client_and_key()
            response = client.chat.completions.create(
                model=mapped_model,
                messages=messages,
                temperature=0.0
            )
            return response.choices[0].message.content
        except Exception as e:
            err_str = str(e)
            is_429 = "429" in err_str or "rate limit" in err_str.lower() or "tpm" in err_str.lower()
            
            # If rate limited, rotate key and sleep
            if is_429 and attempt < max_retries - 1:
                print(f"[Warning] Groq rate limit hit. Rotating key and retrying (Attempt {attempt+1}/{max_retries})...")
                rotate_groq_key()
                time.sleep(1.0)
                continue
                
            # If the model is not found, try a fallback model
            is_model_error = "model" in err_str.lower() or "not found" in err_str.lower()
            if is_model_error and attempt < len(fallback_models):
                old_model = mapped_model
                mapped_model = fallback_models[attempt % len(fallback_models)]
                print(f"[Warning] Model '{old_model}' failed. Trying fallback model '{mapped_model}'...")
                time.sleep(0.5)
                continue

            # Re-raise on last attempt
            if attempt == max_retries - 1:
                raise e
            time.sleep(0.5)
    return ""

def run_hybrid_rag(question: str) -> dict:
    # 1. Retrieve hybrid search results (includes base semantic + SQLite)
    # We pass the question directly as query
    search_results = hybrid_search(question, source_filter=None)
    
    # 2. Neo4j Graph Lookup
    graph = GraphStore()
    graph_results = graph.lookup_relationships(question)
    
    # Build RAG Context
    context_chunks = []
    sources = []
    repos = []
    
    # Extract top search results
    top_search_results = search_results[:6]
    for idx, item in enumerate(top_search_results):
        t = item["type"]
        if t == "repository":
            repo_name = item["repo_name"]
            repos.append(repo_name)
            sources.append(f"Repository metadata for '{repo_name}'")
            context_chunks.append(
                f"Repository: {repo_name}\n"
                f"Description: {item.get('description') or ''}\n"
                f"Language: {item.get('language') or ''}"
            )
        elif t == "document":
            repo_name = item["repo_name"]
            file_name = item["file_name"]
            repos.append(repo_name)
            sources.append(f"{repo_name}/{file_name}")
            context_chunks.append(
                f"Repository: {repo_name}\n"
                f"Document: {file_name}\n"
                f"Content: {item.get('content') or ''}"
            )
        elif t == "email":
            subject = item["subject"]
            sender = item["sender"]
            sources.append(f"Email: {subject}")
            context_chunks.append(
                f"Email Subject: {subject}\n"
                f"From: {sender}\n"
                f"Content Snippet: {item.get('snippet') or ''}"
            )

    # Extract Graph Context
    for rel_desc in graph_results[:10]:
        context_chunks.append(f"Knowledge Graph Relationship: {rel_desc}")
        # Parse repositories from graph relationship if possible
        if "Repository '" in rel_desc:
            parts = rel_desc.split("Repository '")
            if len(parts) > 1:
                r_name = parts[1].split("'")[0]
                repos.append(r_name)
        sources.append("Knowledge Graph")

    # Clean duplicates
    sources = sorted(list(set(sources)))
    repos = sorted(list(set(repos)))
    
    merged_context = "\n\n".join(context_chunks)
    
    # If context is completely empty, fail early to prevent hallucination
    if not merged_context.strip():
        return {
            "answer": "I couldn't find that information in the indexed knowledge.",
            "sources": [],
            "repositories": [],
            "confidence": 0.0
        }

    # Enforce strict system prompt instructions
    system_prompt = (
        "You are an assistant answering ONLY from the supplied retrieved context.\n\n"
        "Never use external knowledge.\n\n"
        "If the question specifies a repository, answer ONLY from chunks belonging to that repository.\n"
        "Ignore unrelated repositories.\n\n"
        "If the answer cannot be found in the supplied context, respond exactly:\n"
        "\"I couldn't find that information in the indexed knowledge.\"\n\n"
        "Do not invent information.\n\n"
        "Mention technologies exactly as written.\n\n"
        "Return:\n"
        "Answer\n"
        "Sources\n"
        "Repositories Used"
    )
    
    user_prompt = (
        f"Retrieved Context:\n"
        f"---------------------\n"
        f"{merged_context}\n"
        f"---------------------\n\n"
        f"Question: {question}\n\n"
        "Format the output strictly as:\n"
        "Answer: [Provide the answer here]\n"
        "Sources: [Provide the sources here]\n"
        "Repositories Used: [Provide the repositories here]"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    try:
        answer = query_llm_with_retry(messages).strip()
    except Exception as e:
        answer = f"Error communicating with Groq: {e}"

    # Calculate basic confidence based on whether the standard fallback text is returned
    confidence = 0.9
    if "i couldn't find that information" in answer.lower():
        answer = "I couldn't find that information in the indexed knowledge."
        confidence = 0.0
        sources = []
        repos = []
    else:
        # Try to parse the structured output
        parsed_answer = ""
        parsed_sources = []
        parsed_repos = []
        
        answer_marker = "Answer:"
        sources_marker = "Sources:"
        repos_marker = "Repositories Used:"
        
        try:
            if answer_marker in answer:
                ans_start = answer.find(answer_marker) + len(answer_marker)
                ans_end = answer.find(sources_marker) if sources_marker in answer else len(answer)
                parsed_answer = answer[ans_start:ans_end].strip()
                
                if sources_marker in answer:
                    src_start = answer.find(sources_marker) + len(sources_marker)
                    src_end = answer.find(repos_marker) if repos_marker in answer else len(answer)
                    srcs_str = answer[src_start:src_end].strip()
                    if srcs_str.lower() != "none" and srcs_str:
                        parsed_sources = [s.strip() for s in srcs_str.split(",") if s.strip()]
                        
                if repos_marker in answer:
                    rep_start = answer.find(repos_marker) + len(repos_marker)
                    rep_str = answer[rep_start:].strip()
                    if rep_str.lower() != "none" and rep_str:
                        parsed_repos = [r.strip() for r in rep_str.split(",") if r.strip()]
            else:
                parsed_answer = answer
        except Exception:
            parsed_answer = answer

        if parsed_answer:
            answer = parsed_answer
        if parsed_sources:
            sources = sorted(list(set(parsed_sources)))
        if parsed_repos:
            repos = sorted(list(set(parsed_repos)))

    return {
        "answer": answer,
        "sources": sources,
        "repositories": repos,
        "confidence": confidence
    }
