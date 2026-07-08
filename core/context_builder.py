import logging
import re

logger = logging.getLogger("context_builder")

class ContextBuilder:
    """Handles query classification, merging, deduplicating, scoring, and enforcing size constraints on RAG contexts."""
    
    def __init__(self, max_context_chars: int = 12000, max_doc_chars: int = 1000, max_graph_relationships: int = 10, max_prompt_tokens: int = 6000, max_chunks: int = 8):
        self.max_context_chars = max_context_chars
        self.max_doc_chars = max_doc_chars
        self.max_graph_relationships = max_graph_relationships
        self.max_prompt_tokens = max_prompt_tokens
        self.max_chunks = max_chunks

    @staticmethod
    def classify_query(query: str, repo_filter = None) -> str:
        """
        Classify the user query to optimize retrieval precision.
        Rule-based, no LLM required.
        """
        query_lower = query.lower()

        # 1. Email Question
        email_keywords = ["email", "emails", "inbox", "message", "messages", "sent from", "received from", "mail", "mails", "gmail"]
        if any(k in query_lower for k in email_keywords):
            return "Email Question"

        # 2. Technology Question
        tech_triggers = [
            "use", "uses", "using", "built with", "written in", "framework", "technology", "technologies", "tech stack",
            "database", "databases", "language", "languages", "library", "libraries", "techs"
        ]
        known_techs = ["python", "javascript", "typescript", "react", "node", "express", "mongodb", "fastapi", "postgresql", "tailwind", "docker", "kafka", "redis", "plotly", "gemini", "groq", "next.js", "firebase", "sqlite", "neo4j", "qdrant", "composio", "langchain", "sentence-transformer", "sentence-transformers"]
        
        has_tech_trigger = any(t in query_lower for t in tech_triggers)
        has_known_tech = any(re.search(r'\b' + re.escape(tech) + r'\b', query_lower) for tech in known_techs)

        if (has_tech_trigger or "which" in query_lower) and has_known_tech:
            if "repositories" in query_lower or "projects" in query_lower or "which" in query_lower or "what" in query_lower:
                return "Technology Question"

        # 3. Repository Question
        if repo_filter:
            return "Repository Question"

        # 4. Documentation Question
        doc_keywords = ["readme", "documentation", "document", "documents", "architecture", "design", "pyproject.toml", "package.json", "requirements.txt", "file", "files"]
        if any(dk in query_lower for dk in doc_keywords):
            return "Documentation Question"

        # 5. Cross Repository Question
        if "cross repository" in query_lower or "multiple repositories" in query_lower or "across all projects" in query_lower:
            return "Cross Repository Question"

        # Default
        return "General Knowledge Question"

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count of a string (heuristic: ~4 characters per token)."""
        return len(text) // 4

    def is_nearly_identical(self, text1: str, text2: str) -> bool:
        """Check if two chunks have high word overlap (>75% identical words) to filter out duplicates."""
        words1 = set(re.findall(r'\w+', text1.lower()))
        words2 = set(re.findall(r'\w+', text2.lower()))
        if not words1 or not words2:
            return False
        intersection = words1.intersection(words2)
        overlap1 = len(intersection) / len(words1)
        overlap2 = len(intersection) / len(words2)
        return overlap1 > 0.75 or overlap2 > 0.75

    def build_context(self, question: str, vector_results: list, keyword_results: list, graph_results: list, repo_filter = None, query_class: str = "General Knowledge Question") -> tuple:
        """
        Merge, deduplicate, score, and format context from vector, keyword, and graph sources.
        Returns (formatted_chunks, sources_list, repos_list, num_vector, num_keyword, num_graph, after_dedup_count)
        """
        query_lower = question.lower()
        stop_words = {"a", "an", "the", "in", "of", "and", "or", "to", "for", "with", "is", "at", "on", "by", "what", "which", "does", "use", "how", "tell", "me", "about"}
        query_terms = [t for t in query_lower.split() if t not in stop_words and len(t) > 1]
        if not query_terms:
            query_terms = [t for t in query_lower.split() if len(t) > 0]

        # Candidate Map to merge vector and keyword results
        candidates = {}

        # 1. Parse keyword results
        num_keyword_raw = len(keyword_results)
        for item in keyword_results:
            t = item["type"]
            if t == "repository":
                key = f"repository:{item['repo_name'].lower()}"
                candidates[key] = {
                    "type": "repository",
                    "repo_name": item["repo_name"],
                    "language": item.get("language") or "",
                    "description": item.get("description") or "",
                    "semantic_similarity": 0.0,
                    "keyword_match_val": 1.0
                }
            elif t == "document":
                key = f"document:{item['repo_name'].lower()}:{item['file_name'].lower()}"
                candidates[key] = {
                    "type": "document",
                    "repo_name": item["repo_name"],
                    "file_name": item["file_name"],
                    "content": item["content"] or "",
                    "semantic_similarity": 0.0,
                    "keyword_match_val": 1.0
                }
            elif t == "email":
                key = f"email:{item['subject'].lower()}"
                candidates[key] = {
                    "type": "email",
                    "subject": item["subject"],
                    "sender": item["sender"],
                    "snippet": item["snippet"] or "",
                    "semantic_similarity": 0.0,
                    "keyword_match_val": 1.0
                }

        # 2. Parse vector results
        num_vector_raw = len(vector_results)
        for sem in vector_results:
            source = sem["source_type"]
            if source == "repository":
                key = f"repository:{sem['repository_name'].lower()}"
                if key not in candidates:
                    candidates[key] = {
                        "type": "repository",
                        "repo_name": sem["repository_name"],
                        "description": sem["chunk_text"] or "",
                        "semantic_similarity": sem["score"],
                        "keyword_match_val": 0.0
                    }
                else:
                    candidates[key]["semantic_similarity"] = max(candidates[key]["semantic_similarity"], sem["score"])
            elif source == "document":
                key = f"document:{sem['repository_name'].lower()}:{sem['document_name'].lower()}"
                if key not in candidates:
                    candidates[key] = {
                        "type": "document",
                        "repo_name": sem["repository_name"],
                        "file_name": sem["document_name"],
                        "content": sem["chunk_text"] or "",
                        "semantic_similarity": sem["score"],
                        "keyword_match_val": 0.0
                    }
                else:
                    if sem["score"] > candidates[key]["semantic_similarity"]:
                        candidates[key]["content"] = sem["chunk_text"]
                    candidates[key]["semantic_similarity"] = max(candidates[key]["semantic_similarity"], sem["score"])
            elif source == "email":
                key = f"email:{sem['document_name'].lower()}"
                if key not in candidates:
                    candidates[key] = {
                        "type": "email",
                        "subject": sem["document_name"],
                        "sender": "Gmail Index",
                        "snippet": sem["chunk_text"] or "",
                        "semantic_similarity": sem["score"],
                        "keyword_match_val": 0.0
                    }
                else:
                    if sem["score"] > candidates[key]["semantic_similarity"]:
                        candidates[key]["snippet"] = sem["chunk_text"]
                    candidates[key]["semantic_similarity"] = max(candidates[key]["semantic_similarity"], sem["score"])

        # 3. Source Priority Checks (TASK 3)
        # Check if any documentation exists (either document or repository)
        has_documentation = any(cand["type"] in ["document", "repository"] for cand in candidates.values())
        
        # Discard emails if the query does NOT explicitly ask about emails AND documentation exists
        is_email_query = (query_class == "Email Question")
        if not is_email_query and has_documentation:
            # Remove all emails
            candidates = {k: v for k, v in candidates.items() if v["type"] != "email"}

        # 4. Calculate Hybrid Score for each candidate (TASK 4)
        scored_candidates = []
        for key, cand in candidates.items():
            sim = cand["semantic_similarity"]
            repo_name = cand.get("repo_name") or ""
            file_name = cand.get("file_name") or ""
            
            # Repository match boost (0.20)
            repo_match_val = 0.0
            if repo_filter:
                if isinstance(repo_filter, list):
                    if repo_name in repo_filter:
                        repo_match_val = 1.0
                elif repo_name.lower() == repo_filter.lower():
                    repo_match_val = 1.0

            # README Bonus (0.10)
            readme_bonus_val = 1.0 if "readme" in file_name.lower() else 0.0

            # Graph relevance boost (0.10)
            graph_relevance_val = 0.0
            if graph_results:
                for rel_desc in graph_results:
                    if repo_name and repo_name.lower() in rel_desc.lower():
                        graph_relevance_val = 1.0
                        break
                    if file_name and file_name.lower() in rel_desc.lower():
                        graph_relevance_val = 1.0
                        break

            # Keyword Match (0.05)
            keyword_match_val = cand.get("keyword_match_val", 0.0)
            if keyword_match_val == 0.0:
                text_to_search = ""
                if cand["type"] == "repository":
                    text_to_search = f"{cand.get('repo_name') or ''} {cand.get('description') or ''}"
                elif cand["type"] == "document":
                    text_to_search = f"{cand.get('file_name') or ''} {cand.get('content') or ''}"
                elif cand["type"] == "email":
                    text_to_search = f"{cand.get('subject') or ''} {cand.get('snippet') or ''}"
                text_to_search_lower = text_to_search.lower()
                if any(term in text_to_search_lower for term in query_terms):
                    keyword_match_val = 1.0

            # Documentation Bonus (0.05)
            doc_bonus_val = 0.0
            if cand["type"] == "document":
                file_lower = file_name.lower()
                if "readme" in file_lower:
                    doc_bonus_val = 1.0
                elif "architecture" in file_lower or "design" in file_lower or "structure" in file_lower:
                    doc_bonus_val = 1.0
                elif file_lower.endswith(".md"):
                    doc_bonus_val = 1.0
                elif file_name in ["pyproject.toml", "package.json", "requirements.txt"]:
                    doc_bonus_val = 0.6
                elif file_lower.endswith((".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp")):
                    doc_bonus_val = 0.2
            elif cand["type"] == "repository":
                doc_bonus_val = 0.5

            # Calculate final score
            # Semantic Similarity      0.50
            # Repository Match         0.20
            # README Bonus             0.10
            # Graph Relevance          0.10
            # Keyword Match            0.05
            # Documentation Bonus      0.05
            final_score = round(
                (0.50 * sim) + 
                (0.20 * repo_match_val) + 
                (0.10 * readme_bonus_val) + 
                (0.10 * graph_relevance_val) + 
                (0.05 * keyword_match_val) + 
                (0.05 * doc_bonus_val),
                4
            )

            cand["score"] = final_score
            scored_candidates.append(cand)

        # Sort candidates by score descending
        scored_candidates.sort(key=lambda x: (-x["score"], x.get("repo_name") or x.get("subject") or ""))

        # 5. Deduplication and Context Filtering (TASK 5)
        deduplicated_candidates = []
        for cand in scored_candidates:
            cand_text = ""
            if cand["type"] == "repository":
                cand_text = cand.get("description") or ""
            elif cand["type"] == "document":
                cand_text = cand.get("content") or ""
            elif cand["type"] == "email":
                cand_text = cand.get("snippet") or ""

            # Check if nearly identical to any already included chunk
            is_dup = False
            for doc in deduplicated_candidates:
                doc_text = ""
                if doc["type"] == "repository":
                    doc_text = doc.get("description") or ""
                elif doc["type"] == "document":
                    doc_text = doc.get("content") or ""
                elif doc["type"] == "email":
                    doc_text = doc.get("snippet") or ""
                
                if self.is_nearly_identical(cand_text, doc_text):
                    is_dup = True
                    break
            
            if not is_dup:
                deduplicated_candidates.append(cand)

        after_dedup_count = len(deduplicated_candidates)

        # Enforce context limits (max 8-10 chunks or max 12000 chars)
        limited_graph_results = graph_results[:self.max_graph_relationships]
        num_graph = len(limited_graph_results)

        formatted_chunks = []
        sources = []
        repos = []
        char_count = 0
        chunk_count = 0

        # Build final candidates checking both chunk limit and char limit
        # Always keep highest ranked chunks
        for cand in deduplicated_candidates:
            if chunk_count >= self.max_chunks:
                break
            
            # Format and truncate single chunk
            if cand["type"] == "repository":
                repo_name = cand["repo_name"]
                desc = cand.get("description") or ""
                if len(desc) > self.max_doc_chars:
                    desc = desc[:self.max_doc_chars] + "... [TRUNCATED]"
                chunk_str = f"Repository: {repo_name}\nDescription: {desc}\nLanguage: {cand.get('language') or ''}"
                
                repos.append(repo_name)
                sources.append(f"Repository metadata for '{repo_name}'")
            elif cand["type"] == "document":
                repo_name = cand["repo_name"]
                file_name = cand["file_name"]
                content = cand.get("content") or ""
                if len(content) > self.max_doc_chars:
                    content = content[:self.max_doc_chars] + "... [TRUNCATED]"
                chunk_str = f"Repository: {repo_name}\nDocument: {file_name}\nContent: {content}"
                
                repos.append(repo_name)
                sources.append(f"{repo_name}/{file_name}")
            elif cand["type"] == "email":
                subject = cand["subject"]
                sender = cand["sender"]
                snippet = cand.get("snippet") or ""
                if len(snippet) > self.max_doc_chars:
                    snippet = snippet[:self.max_doc_chars] + "... [TRUNCATED]"
                chunk_str = f"Email Subject: {subject}\nFrom: {sender}\nContent Snippet: {snippet}"
                
                sources.append(f"Email: {subject}")

            # Check if adding this chunk exceeds character limit
            projected_chars = char_count + len(chunk_str) + 4
            if projected_chars > self.max_context_chars and chunk_count > 0:
                # Character limit exceeded
                break

            formatted_chunks.append({
                "text": chunk_str,
                "score": cand["score"],
                "type": cand["type"]
            })
            char_count += len(chunk_str) + 4
            chunk_count += 1

        # Append limited graph results (max graph relationships)
        for rel_desc in limited_graph_results:
            chunk_str = f"Knowledge Graph Relationship: {rel_desc}"
            
            projected_chars = char_count + len(chunk_str) + 4
            if projected_chars > self.max_context_chars:
                break
                
            if "Repository '" in rel_desc:
                parts = rel_desc.split("Repository '")
                if len(parts) > 1:
                    r_name = parts[1].split("'")[0]
                    repos.append(r_name)
            sources.append("Knowledge Graph")
            formatted_chunks.append({
                "text": chunk_str,
                "score": 0.05,
                "type": "graph"
            })
            char_count += len(chunk_str) + 4

        sources = sorted(list(set(sources)))
        repos = sorted(list(set(repos)))

        return formatted_chunks, sources, repos, num_vector_raw, num_keyword_raw, num_graph, after_dedup_count

    def trim_context_to_limit(self, system_prompt: str, user_prompt_template: str, formatted_chunks: list) -> tuple:
        """Trims lowest-ranked context chunks iteratively if total estimated tokens exceed self.max_prompt_tokens."""
        active_chunks = list(formatted_chunks)

        while len(active_chunks) > 0:
            merged_context = "\n\n".join([c["text"] for c in active_chunks])
            full_prompt_text = system_prompt + user_prompt_template.replace("{context}", merged_context)
            est_tokens = self.estimate_tokens(full_prompt_text)

            if est_tokens <= self.max_prompt_tokens:
                return merged_context, len(active_chunks)

            # Over limit, remove lowest-ranked chunk
            min_idx = -1
            min_score = float('inf')
            for i, c in enumerate(active_chunks):
                if c["score"] < min_score:
                    min_score = c["score"]
                    min_idx = i
            
            if min_idx != -1:
                removed = active_chunks.pop(min_idx)
                logger.info(f"Context builder trimmed chunk of type '{removed['type']}' with score {removed['score']} due to token limit.")
            else:
                break

        return "", 0
