"""
Core: Hybrid Ranking Engine.

Provides unified hybrid scoring across vector similarity, repository matching,
README priority, graph relationship relevance, keyword matches, and documentation bonuses.
"""

import logging

logger = logging.getLogger("core.ranking")


class RankingEngine:
    """Calculates weighted hybrid scores for retrieved candidates."""

    WEIGHT_SEMANTIC = 0.50
    WEIGHT_REPO_MATCH = 0.20
    WEIGHT_README_BONUS = 0.10
    WEIGHT_GRAPH_RELEVANCE = 0.10
    WEIGHT_KEYWORD_MATCH = 0.05
    WEIGHT_DOC_BONUS = 0.05

    @classmethod
    def calculate_score(
        cls,
        semantic_sim: float,
        repo_name: str | None = None,
        file_name: str | None = None,
        candidate_type: str = "document",
        repo_filter: str | list | None = None,
        graph_results: list | None = None,
        search_text: str = "",
        query_terms: list | None = None,
        is_repo_focused: bool = False
    ) -> float:
        """Calculate unified hybrid candidate score."""
        # 1. Repository Match
        repo_match_val = 0.0
        if repo_filter and repo_name:
            if isinstance(repo_filter, list):
                if any(repo_name.lower() == rf.lower() for rf in repo_filter):
                    repo_match_val = 1.0
            elif repo_name.lower() == str(repo_filter).lower():
                repo_match_val = 1.0

        # 2. README Bonus
        readme_bonus_val = 1.0 if file_name and "readme" in file_name.lower() else 0.0

        # 3. Graph Relevance
        graph_relevance_val = 0.0
        if graph_results:
            for rel_desc in graph_results:
                if repo_name and repo_name.lower() in rel_desc.lower():
                    graph_relevance_val = 1.0
                    break
                if file_name and file_name.lower() in rel_desc.lower():
                    graph_relevance_val = 1.0
                    break

        # 4. Keyword Match
        keyword_match_val = 0.0
        if query_terms and search_text:
            text_lower = search_text.lower()
            if any(term in text_lower for term in query_terms):
                keyword_match_val = 1.0

        # 5. Documentation Type Bonus
        doc_bonus_val = 0.0
        if candidate_type == "document" and file_name:
            file_lower = file_name.lower()
            if "readme" in file_lower or "architecture" in file_lower or "design" in file_lower or file_lower.endswith(".md"):
                doc_bonus_val = 1.0
            elif file_name in ["pyproject.toml", "package.json", "requirements.txt"]:
                doc_bonus_val = 0.6
            elif file_lower.endswith((".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp")):
                doc_bonus_val = 0.2
        elif candidate_type == "repository":
            doc_bonus_val = 0.5

        final_score = round(
            (cls.WEIGHT_SEMANTIC * semantic_sim) +
            (cls.WEIGHT_REPO_MATCH * repo_match_val) +
            (cls.WEIGHT_README_BONUS * readme_bonus_val) +
            (cls.WEIGHT_GRAPH_RELEVANCE * graph_relevance_val) +
            (cls.WEIGHT_KEYWORD_MATCH * keyword_match_val) +
            (cls.WEIGHT_DOC_BONUS * doc_bonus_val),
            4
        )

        if is_repo_focused and candidate_type == "email":
            final_score = round(final_score * 0.1, 4)

        return final_score
