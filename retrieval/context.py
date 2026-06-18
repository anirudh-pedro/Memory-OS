import json
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class ContextBuilder:
    def __init__(self, char_budget: int = 10000, llm=None):
        self.char_budget = char_budget
        self.llm = llm

    def _summarize_document(self, title: str, content: str) -> str:
        """Uses LLM to summarize large documents to keep context compact."""
        if not self.llm:
            return content[:800] + "\n... [truncated] ..."
            
        try:
            prompt = (
                f"Summarize the following document briefly in 2-3 sentences to preserve token budget.\n"
                f"Document Title: {title}\n"
                f"Content:\n{content[:4000]}\n"
            )
            res = self.llm.invoke(prompt)
            return res.content.strip()
        except Exception as e:
            logger.warning(f"Dynamic summarization failed: {e}")
            return content[:800] + "\n... [truncated] ..."

    def build_context(self, fused_results: List[Dict[str, Any]], graph_results: Dict[str, Any]) -> str:
        """Assembles structured prompt context block with deduplication, project limiting, and summarization."""
        context_lines = []
        budget = self.char_budget

        # 1. Deduplicate and filter matches
        seen_ids = set()
        deduped_fused = []
        for wrapper in fused_results:
            item = wrapper["item"]
            item_id = item.get("id")
            if item_id not in seen_ids:
                seen_ids.add(item_id)
                deduped_fused.append(wrapper)

        # Limit chunks per project (max 2 chunks per project)
        project_counts = {}
        limited_fused = []
        for wrapper in deduped_fused:
            item = wrapper["item"]
            title = item.get("title", "")
            content = item.get("content", "")
            
            # Identify associated project
            associated_project = "unknown"
            for proj in ["AgriChain", "Memory-OS", "DataCue", "Bug Tracker", "BlogSphere", "Aniru-AI", "Anirudh-Portfolio", "FlashChat", "NeetCode", "PageForge", "ParkFree"]:
                if proj.lower() in title.lower() or proj.lower() in content.lower():
                    associated_project = proj
                    break
                    
            if associated_project != "unknown":
                count = project_counts.get(associated_project, 0)
                if count >= 2:
                    continue  # Skip if we already have 2 chunks for this project
                project_counts[associated_project] = count + 1
            limited_fused.append(wrapper)

        # 2. Process workspace cache fused matches
        if limited_fused:
            section_lines = ["=== WORKSPACE MEMORY MATCHES ==="]
            for item_wrapper in limited_fused:
                item = item_wrapper["item"]
                score = item_wrapper["score"]
                content = item.get("content", "")
                
                # Summarize if too large
                if len(content) > 1500:
                    logger.info(f"Summarizing large document '{item['title']}' (length {len(content)})...")
                    content = self._summarize_document(item['title'], content)
                
                item_lines = [
                    f"[{item['source_app'].upper()} (score: {score:.4f})] {item['title']}",
                    f"Content: {content}",
                    "-" * 20
                ]
                section_lines.extend(item_lines)
            
            section_text = "\n".join(section_lines)
            if len(section_text) > budget:
                section_text = section_text[:budget] + "\n... [Workspace matches truncated] ..."
            context_lines.append(section_text)
            budget -= len(section_text)

        # 3. Process Knowledge Graph Nodes & Relationships
        if budget > 500 and (graph_results.get("entities") or graph_results.get("relationships")):
            section_lines = ["\n=== KNOWLEDGE GRAPH MEMORY ==="]
            if graph_results.get("entities"):
                section_lines.append("Entities:")
                for ent in graph_results["entities"]:
                    # Reject low-importance entities (importance score < 3)
                    properties = ent.get("properties", {})
                    importance_score = properties.get("importance_score")
                    if importance_score is not None:
                        try:
                            if int(importance_score) < 3:
                                continue  # Skip low importance entity
                        except (ValueError, TypeError):
                            pass
                            
                    desc = f" - Description: {ent['description']}" if ent.get("description") else ""
                    section_lines.append(f"- {ent['name']} ({ent['entity_type']}){desc} - Details: {json.dumps(properties)}")
            if graph_results.get("relationships"):
                section_lines.append("Relationships:")
                for rel in graph_results["relationships"]:
                    section_lines.append(f"- ({rel['source']}) -- {rel['relation_type']} --> ({rel['target']})")
            
            section_text = "\n".join(section_lines)
            if len(section_text) > budget:
                section_text = section_text[:budget] + "\n... [Graph matches truncated] ..."
            context_lines.append(section_text)

        return "\n".join(context_lines) if context_lines else "No relevant context found in memory."
