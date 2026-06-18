from typing import List, Dict, Any

class ReciprocalRankFusion:
    def __init__(self, k: int = 60):
        self.k = k

    def fuse(self, fts_results: List[Dict[str, Any]], vector_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Fuse and rank results from FTS and vector searches using RRF.
        Returns a sorted list of matches with combined scores.
        """
        scores = {}
        items_map = {}

        # 1. Process FTS results
        for rank, item in enumerate(fts_results):
            # Unique key for workspace cache items: source_app + external_id
            item_key = f"{item['source_app']}_{item['external_id']}"
            if item_key not in scores:
                scores[item_key] = 0.0
                items_map[item_key] = item
            scores[item_key] += 1.0 / (self.k + (rank + 1))

        # 2. Process Vector results
        for rank, hit in enumerate(vector_results):
            payload = hit.get("payload", {})
            if not payload or payload.get("type") != "workspace_cache":
                continue
                
            item_key = f"{payload.get('source_app')}_{payload.get('external_id')}"
            if item_key not in scores:
                scores[item_key] = 0.0
                items_map[item_key] = {
                    "source_app": payload.get("source_app"),
                    "external_id": payload.get("external_id"),
                    "title": payload.get("title"),
                    "content": payload.get("text", "")
                }
            scores[item_key] += 1.0 / (self.k + (rank + 1))

        # 3. Sort by combined RRF score descending
        sorted_keys = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        
        fused_results = []
        for key in sorted_keys:
            fused_results.append({
                "score": scores[key],
                "item": items_map[key]
            })
            
        return fused_results
