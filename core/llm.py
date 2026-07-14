import os
import time
import logging
from groq import Groq
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

def inject_repository_summary_chunk(formatted_chunks: list, query_class: str) -> list:
    """If the query is a cross-repository query, pre-append a summary chunk listing all repos."""
    if query_class != "Cross Repository Question":
        return formatted_chunks

    try:
        from storage.db import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT repo_name, description, language FROM repositories")
        all_repos = cursor.fetchall()
        conn.close()
        
        if all_repos:
            repo_list_lines = ["All Connected Repositories:"]
            for r in all_repos:
                desc_str = f" - Description: {r[1]}" if r[1] else ""
                lang_str = f" (Language: {r[2]})" if r[2] else ""
                repo_list_lines.append(f"- {r[0]}{lang_str}{desc_str}")
            repo_list_str = "\n".join(repo_list_lines)
            
            # Pre-append to formatted_chunks with a high score to prevent trimming
            formatted_chunks.insert(0, {
                "text": repo_list_str,
                "score": 999.0,
                "type": "repository_summary"
            })
    except Exception as e:
        import logging
        logging.getLogger("llm").error(f"Failed to generate repository summary context chunk: {e}")
        
    return formatted_chunks

def run_hybrid_rag(question: str) -> dict:
    import time
    import logging
    import re
    logger = logging.getLogger("llm")
    
    logger.info(f"Starting RAG pipeline for question: '{question}'")
    start_time = time.perf_counter()
    
    from core.vector_store import run_semantic_search, detect_repo_in_query
    from storage.db import search_local_knowledge_ranked
    from core.context_builder import ContextBuilder
    
    # 1. Detect single repo mention
    detected_repo = detect_repo_in_query(question)
    
    # 2. Query Classification (Task 1)
    query_class = ContextBuilder.classify_query(question, detected_repo)
    
    # 3. Graph Guided Retrieval Filter (Task 6)
    repo_filter = detected_repo
    if query_class == "Technology Question":
        # Extract tech and query graph for repo list filter
        known_techs = ["python", "javascript", "typescript", "react", "node", "express", "mongodb", "fastapi", "postgresql", "tailwind", "docker", "kafka", "redis", "plotly", "gemini", "groq", "next.js", "firebase", "sqlite", "neo4j", "qdrant", "composio", "langchain", "sentence-transformer", "sentence-transformers"]
        query_lower = question.lower()
        matched_techs = []
        for tech in known_techs:
            patterns = [
                r'\b' + re.escape(tech) + r'\b',
                r'\b' + re.escape(tech.replace('.', '')) + r'\b',
                r'\b' + re.escape(tech.replace('-', '')) + r'\b'
            ]
            if any(re.search(pat, query_lower) for pat in patterns):
                matched_techs.append(tech)
                
        graph_repos = []
        if matched_techs:
            try:
                graph = GraphStore()
                for tech in matched_techs:
                    rels = graph.lookup_relationships(tech)
                    for r in rels:
                        if "Repository '" in r:
                            parts = r.split("Repository '")
                            if len(parts) > 1:
                                repo_name = parts[1].split("'")[0]
                                graph_repos.append(repo_name)
            except Exception as e:
                logger.error(f"Graph guided filtering query failed: {e}")
                
        if graph_repos:
            repo_filter = list(set(graph_repos))
            
    # 4. Perform Retrieval
    # Raw vector results from Qdrant
    vector_results = run_semantic_search(question, limit=20, source_filter=None, raw_scores=True, repo_filter=repo_filter)
    
    # Raw keyword results from SQLite
    keyword_results = search_local_knowledge_ranked(question, repo_filter=repo_filter)
    
    # Neo4j Graph Lookup
    graph = GraphStore()
    graph_results = graph.lookup_relationships(question)
    
    # 5. Context Builder logic (Task 3, 4, 5)
    builder = ContextBuilder()
    formatted_chunks, sources, repos, num_vector, num_keyword, num_graph, after_dedup = builder.build_context(
        question, vector_results, keyword_results, graph_results, repo_filter=repo_filter, query_class=query_class
    )
    formatted_chunks = inject_repository_summary_chunk(formatted_chunks, query_class)
    
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
    
    user_prompt_template = (
        "Retrieved Context:\n"
        "---------------------\n"
        "{context}\n"
        "---------------------\n\n"
        f"Question: {question}\n\n"
        "Format the output strictly as:\n"
        "Answer: [Provide the answer here]\n"
        "Sources: [Provide the sources here]\n"
        "Repositories Used: [Provide the repositories here]"
    )
    
    # Trim lowest ranked chunks if overall prompt exceeds token limits
    merged_context, final_chunks_count = builder.trim_context_to_limit(
        system_prompt, user_prompt_template, formatted_chunks
    )
    
    total_chars = len(merged_context)
    est_prompt_tokens = builder.estimate_tokens(system_prompt + user_prompt_template.replace("{context}", merged_context))
    
    # Print Retrieval Diagnostics in exact required format (Task 7)
    repo_filter_str = str(repo_filter) if repo_filter else "None"
    print("========================================")
    print("QUERY CLASS")
    print(query_class)
    print("Repository Filter")
    print(repo_filter_str)
    print("Vector Candidates")
    print(num_vector)
    print("Keyword Candidates")
    print(num_keyword)
    print("Graph Candidates")
    print(num_graph)
    print("After Deduplication")
    print(after_dedup)
    print("Final Context Chunks")
    print(final_chunks_count)
    print("Context Characters")
    print(total_chars)
    print("Estimated Tokens")
    print(est_prompt_tokens)
    print("========================================")
    
    # If context is completely empty, fail early to prevent hallucination
    if not merged_context.strip():
        logger.info("Empty RAG context. Skipping LLM query.")
        duration = time.perf_counter() - start_time
        print(f"Total RAG Pipeline Duration: {duration:.2f}s")
        return {
            "answer": "I couldn't find that information in the indexed knowledge.",
            "sources": [],
            "repositories": [],
            "confidence": 0.0
        }

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt_template.replace("{context}", merged_context)}
    ]

    try:
        llm_start = time.perf_counter()
        answer = query_llm_with_retry(messages).strip()
        llm_duration = time.perf_counter() - llm_start
        logger.info(f"Groq LLM generation finished in {llm_duration:.2f}s")
        print(f"LLM Generation Duration: {llm_duration:.2f}s")
    except Exception as e:
        answer = f"Error communicating with Groq: {e}"
        logger.error(f"Groq LLM generation failed: {e}")

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

    total_duration = time.perf_counter() - start_time
    logger.info(f"RAG pipeline complete for question: '{question}' in {total_duration:.2f}s")
    print(f"Total RAG Pipeline Duration: {total_duration:.2f}s")

    return {
        "answer": answer,
        "sources": sources,
        "repositories": repos,
        "confidence": confidence
    }


def stream_llm_with_retry(messages: list, model: str = None, max_retries: int = 3):
    if not model:
        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    # Map legacy/unsupported model names to supported ones on Groq
    mapped_model = model
    if "/" in model:
        mapped_model = model.split("/")[-1]
    if mapped_model in ["gpt-oss-120b", "openai/gpt-oss-120b", "openai-gpt-oss-120b"]:
        mapped_model = "llama-3.3-70b-versatile"

    fallback_models = ["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "llama-3.1-8b-instant"]

    for attempt in range(max_retries):
        try:
            client, key = get_groq_client_and_key()
            response = client.chat.completions.create(
                model=mapped_model,
                messages=messages,
                temperature=0.0,
                stream=True
            )
            for chunk in response:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
            return
        except Exception as e:
            err_str = str(e)
            is_429 = "429" in err_str or "rate limit" in err_str.lower() or "tpm" in err_str.lower()
            if is_429 and attempt < max_retries - 1:
                rotate_groq_key()
                time.sleep(1.0)
                continue
            is_model_error = "model" in err_str.lower() or "not found" in err_str.lower()
            if is_model_error and attempt < len(fallback_models):
                mapped_model = fallback_models[attempt % len(fallback_models)]
                time.sleep(0.5)
                continue
            if attempt == max_retries - 1:
                raise e
            time.sleep(0.5)


def run_hybrid_rag_stream(question: str):
    import time
    import logging
    import re
    logger = logging.getLogger("llm")
    
    logger.info(f"Starting streaming RAG pipeline for question: '{question}'")
    start_time = time.perf_counter()
    
    from core.vector_store import run_semantic_search, detect_repo_in_query
    from storage.db import search_local_knowledge_ranked
    from core.context_builder import ContextBuilder
    
    # 1. Detect single repo mention
    detected_repo = detect_repo_in_query(question)
    
    # 2. Query Classification (Task 1)
    query_class = ContextBuilder.classify_query(question, detected_repo)
    
    # 3. Graph Guided Retrieval Filter (Task 6)
    repo_filter = detected_repo
    if query_class == "Technology Question":
        known_techs = ["python", "javascript", "typescript", "react", "node", "express", "mongodb", "fastapi", "postgresql", "tailwind", "docker", "kafka", "redis", "plotly", "gemini", "groq", "next.js", "firebase", "sqlite", "neo4j", "qdrant", "composio", "langchain", "sentence-transformer", "sentence-transformers"]
        query_lower = question.lower()
        matched_techs = []
        for tech in known_techs:
            patterns = [
                r'\b' + re.escape(tech) + r'\b',
                r'\b' + re.escape(tech.replace('.', '')) + r'\b',
                r'\b' + re.escape(tech.replace('-', '')) + r'\b'
            ]
            if any(re.search(pat, query_lower) for pat in patterns):
                matched_techs.append(tech)
                
        graph_repos = []
        if matched_techs:
            try:
                graph = GraphStore()
                for tech in matched_techs:
                    rels = graph.lookup_relationships(tech)
                    for r in rels:
                        if "Repository '" in r:
                            parts = r.split("Repository '")
                            if len(parts) > 1:
                                repo_name = parts[1].split("'")[0]
                                graph_repos.append(repo_name)
            except Exception as e:
                logger.error(f"Graph guided filtering query failed: {e}")
                
        if graph_repos:
            repo_filter = list(set(graph_repos))
            
    # 4. Perform Retrieval
    vector_results = run_semantic_search(question, limit=20, source_filter=None, raw_scores=True, repo_filter=repo_filter)
    keyword_results = search_local_knowledge_ranked(question, repo_filter=repo_filter)
    
    graph = GraphStore()
    graph_results = graph.lookup_relationships(question)
    
    # 5. Context Builder logic
    builder = ContextBuilder()
    formatted_chunks, sources, repos, num_vector, num_keyword, num_graph, after_dedup = builder.build_context(
        question, vector_results, keyword_results, graph_results, repo_filter=repo_filter, query_class=query_class
    )
    formatted_chunks = inject_repository_summary_chunk(formatted_chunks, query_class)
    
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
    
    user_prompt_template = (
        "Retrieved Context:\n"
        "---------------------\n"
        "{context}\n"
        "---------------------\n\n"
        f"Question: {question}\n\n"
        "Format the output strictly as:\n"
        "Answer: [Provide the answer here]\n"
        "Sources: [Provide the sources here]\n"
        "Repositories Used: [Provide the repositories here]"
    )
    
    merged_context, final_chunks_count = builder.trim_context_to_limit(
        system_prompt, user_prompt_template, formatted_chunks
    )
    
    total_chars = len(merged_context)
    est_prompt_tokens = builder.estimate_tokens(system_prompt + user_prompt_template.replace("{context}", merged_context))
    
    diagnostics = {
        "query_class": query_class,
        "repo_filter": repo_filter,
        "num_vector": num_vector,
        "num_keyword": num_keyword,
        "num_graph": num_graph,
        "after_dedup": after_dedup,
        "final_chunks_count": final_chunks_count,
        "total_chars": total_chars,
        "est_prompt_tokens": est_prompt_tokens
    }
    
    yield {
        "type": "diagnostics",
        "data": diagnostics
    }
    
    if not merged_context.strip():
        yield {
            "type": "token",
            "content": "I couldn't find that information in the indexed knowledge."
        }
        yield {
            "type": "done",
            "answer": "I couldn't find that information in the indexed knowledge.",
            "sources": [],
            "repositories": [],
            "confidence": 0.0
        }
        return
        
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt_template.replace("{context}", merged_context)}
    ]
    
    full_response = ""
    try:
        for chunk in stream_llm_with_retry(messages):
            full_response += chunk
            yield {
                "type": "token",
                "content": chunk
            }
    except Exception as e:
        error_msg = f"Error communicating with Groq: {e}"
        yield {
            "type": "token",
            "content": error_msg
        }
        yield {
            "type": "done",
            "answer": error_msg,
            "sources": [],
            "repositories": [],
            "confidence": 0.0
        }
        return
        
    # Calculate confidence and parse response
    confidence = 0.9
    answer = full_response
    sources = []
    repos = []
    
    if "i couldn't find that information" in answer.lower():
        answer = "I couldn't find that information in the indexed knowledge."
        confidence = 0.0
    else:
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

    total_duration = time.perf_counter() - start_time
    logger.info(f"Streaming RAG pipeline complete in {total_duration:.2f}s")
    
    yield {
        "type": "done",
        "answer": answer,
        "sources": sources,
        "repositories": repos,
        "confidence": confidence
    }

