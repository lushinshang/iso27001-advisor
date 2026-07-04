"""Hybrid Search 元件。"""

import json
from pathlib import Path

from iso27001_advisor.core.kg_gates import cosine_similarity
from iso27001_advisor.core.search_tool import ISO27001Searcher
from iso27001_advisor.core.semantic_cache import (
    EMBED_MODEL,
    OLLAMA_HOST,
    _QUERY_INSTRUCTION,
    get_embedding,
)

BASE_DIR = Path(__file__).resolve().parents[3]
DEFAULT_EMB_PATH = BASE_DIR / "data" / "clause_embeddings.json"
DEFAULT_KG_PATH = BASE_DIR / "data" / "knowledge_graph.json"


def _extract_id(entry):
    """支援測試與檢索結果常見格式，統一取出條文 ID。"""
    if isinstance(entry, str):
        return entry
    if "id" in entry:
        return entry["id"]
    if "item" in entry and "id" in entry["item"]:
        return entry["item"]["id"]
    raise KeyError("RRF ranking item 缺少 id")


def rrf_fuse(rankings, k=60):
    """以 Reciprocal Rank Fusion 融合多路排名。

    rank 從 1 開始；只出現在單一路徑的項目只累加該路分數。
    回傳 ``[(item_id, score), ...]``，依分數高到低排序；同分時保留先出現者。
    """
    scores = {}
    first_seen = {}
    order = 0

    for ranking in rankings:
        for rank, entry in enumerate(ranking, start=1):
            item_id = _extract_id(entry)
            if item_id not in first_seen:
                first_seen[item_id] = order
                order += 1
            scores[item_id] = scores.get(item_id, 0.0) + (1.0 / (k + rank))

    return sorted(scores.items(), key=lambda item: (-item[1], first_seen[item[0]]))


class HybridSearcher:
    """關鍵字 + 向量 RRF + KG 1-hop 的包裝式檢索器。"""

    def __init__(
        self,
        searcher=None,
        emb_path=None,
        kg_path=None,
        host=OLLAMA_HOST,
        rrf_k=60,
        kg_damp=0.5,
        mode="gated",
    ):
        self.searcher = searcher or ISO27001Searcher()
        self.emb_path = Path(emb_path) if emb_path is not None else DEFAULT_EMB_PATH
        self.kg_path = Path(kg_path) if kg_path is not None else DEFAULT_KG_PATH
        self.host = host
        self.rrf_k = rrf_k
        self.kg_damp = kg_damp
        self.mode = mode
        self._emb_index = []
        self._embed_model = EMBED_MODEL
        self._kg_neighbors = {}
        self._hybrid_ready = False
        self._load_embeddings()
        self._load_kg()

    @property
    def is_hybrid_ready(self):
        return self._hybrid_ready

    def _load_embeddings(self):
        try:
            with self.emb_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            self._hybrid_ready = False
            return

        self._embed_model = payload.get("embed_model", EMBED_MODEL)
        self._emb_index = [
            {"id": item["id"], "embedding": item["embedding"]}
            for item in payload.get("items", [])
            if "id" in item and "embedding" in item
        ]
        self._hybrid_ready = len(self._emb_index) > 0

    def _load_kg(self):
        try:
            with self.kg_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return

        for edge in payload.get("edges", []):
            from_id = edge.get("from")
            to_id = edge.get("to")
            if not from_id or not to_id:
                continue
            self._kg_neighbors.setdefault(from_id, set()).add(to_id)
            self._kg_neighbors.setdefault(to_id, set()).add(from_id)

    def _keyword_fallback(self, query, limit):
        return [
            {"item": result["item"], "score": result["score"], "source": "keyword_fallback"}
            for result in self.searcher.search(query, limit=limit)
        ]

    def _vector_ranking(self, query):
        query_emb = get_embedding(
            _QUERY_INSTRUCTION + query,
            self._embed_model,
            self.host,
        )
        scored = []
        for entry in self._emb_index:
            scored.append(
                {
                    "id": entry["id"],
                    "score": cosine_similarity(query_emb, entry["embedding"]),
                }
            )
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:20]

    def _get_item(self, item_id):
        if hasattr(self.searcher, "get_by_id"):
            return self.searcher.get_by_id(item_id)
        return None

    def _apply_kg_one_hop(self, results, limit):
        candidates = list(results[:limit])
        present = {result["item"]["id"] for result in candidates}
        for result in results[:limit]:
            source_id = result["item"]["id"]
            for neighbor_id in sorted(self._kg_neighbors.get(source_id, [])):
                if neighbor_id in present:
                    continue
                item = self._get_item(neighbor_id)
                if item is None:
                    continue
                candidates.append(
                    {
                        "item": item,
                        "score": result["score"] * self.kg_damp,
                        "source": "kg_1hop",
                    }
                )
                present.add(neighbor_id)
        candidates.sort(key=lambda item: item["score"], reverse=True)
        return candidates[:limit]

    def search(self, query, limit=4):
        if limit <= 0:
            return []

        # keyword 模式直接走關鍵字結果且標記 source
        if self.mode == "keyword":
            return [
                {"item": result["item"], "score": result["score"], "source": "keyword"}
                for result in self.searcher.search(query, limit=limit)
            ]

        keyword_results = self.searcher.search(query, limit=20)

        # gated 模式判斷
        if self.mode == "gated":
            top_score = keyword_results[0]["score"] if keyword_results else 0.0
            if top_score >= 100.0:
                return [
                    {"item": result["item"], "score": result["score"], "source": "keyword"}
                    for result in keyword_results[:limit]
                ]

        # keyword+KG 模式：對關鍵字結果直接做 KG 擴展，跳過向量 RRF 融合
        if self.mode == "keyword+KG":
            results = [
                {"item": result["item"], "score": result["score"], "source": "keyword"}
                for result in keyword_results
            ]
            if self._kg_neighbors:
                return self._apply_kg_one_hop(results, limit)
            return results[:limit]

        # 向量融合相關模式 (keyword+RRF, full, 以及 gated 低信心題)
        if not self._hybrid_ready:
            return [
                {"item": result["item"], "score": result["score"], "source": "keyword_fallback"}
                for result in keyword_results[:limit]
            ]

        try:
            vector_results = self._vector_ranking(query)
        except Exception:
            return self._keyword_fallback(query, limit)

        fused = rrf_fuse([keyword_results, vector_results], k=self.rrf_k)
        results = []
        for item_id, score in fused:
            item = self._get_item(item_id)
            if item is None:
                continue
            results.append({"item": item, "score": score, "source": "rrf"})

        # keyword+RRF 模式：跳過 KG 擴展
        if self.mode == "keyword+RRF":
            return results[:limit]

        # full 模式與 gated 低信心題：套用 KG 擴展
        if (self.mode == "full" or self.mode == "gated") and self._kg_neighbors:
            return self._apply_kg_one_hop(results, limit)
        return results[:limit]
