import json

from iso27001_advisor.core.hybrid_search import HybridSearcher


class FakeSearcher:
    def __init__(self):
        self.items = [
            {"id": "control_a", "title": "A", "content": "A content"},
            {"id": "control_b", "title": "B", "content": "B content"},
            {"id": "control_c", "title": "C", "content": "C content"},
            {"id": "control_d", "title": "D", "content": "D content"},
        ]
        self._id_index = {item["id"]: item for item in self.items}

    def get_by_id(self, item_id):
        return self._id_index.get(item_id)

    def search(self, query, limit=5):
        return [
            {"item": self._id_index["control_a"], "score": 100.0},
            {"item": self._id_index["control_b"], "score": 90.0},
        ][:limit]


def _write_embeddings(path):
    payload = {
        "embed_model": "fake",
        "dimension": 2,
        "items": [
            {"id": "control_a", "embedding": [1.0, 0.0]},
            {"id": "control_b", "embedding": [0.8, 0.2]},
            {"id": "control_c", "embedding": [0.0, 1.0]},
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_kg(path):
    payload = {
        "edges": [
            {"from": "control_a", "to": "control_d", "similarity": 1.0},
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_hybrid_searcher_combines_keyword_and_vector_rankings(tmp_path, monkeypatch):
    emb_path = tmp_path / "embeddings.json"
    _write_embeddings(emb_path)
    monkeypatch.setattr(
        "iso27001_advisor.core.hybrid_search.get_embedding",
        lambda text, model, host: [0.0, 1.0],
    )

    searcher = HybridSearcher(searcher=FakeSearcher(), emb_path=emb_path)
    results = searcher.search("query", limit=3)

    assert "control_c" in [result["item"]["id"] for result in results]
    assert {result["source"] for result in results} == {"rrf"}


def test_hybrid_searcher_adds_kg_one_hop_with_dampened_score(tmp_path, monkeypatch):
    emb_path = tmp_path / "embeddings.json"
    kg_path = tmp_path / "knowledge_graph.json"
    _write_embeddings(emb_path)
    _write_kg(kg_path)
    monkeypatch.setattr(
        "iso27001_advisor.core.hybrid_search.get_embedding",
        lambda text, model, host: [0.0, 1.0],
    )

    searcher = HybridSearcher(searcher=FakeSearcher(), emb_path=emb_path, kg_path=kg_path)
    results = searcher.search("query", limit=4)
    by_id = {result["item"]["id"]: result for result in results}

    assert by_id["control_d"]["source"] == "kg_1hop"
    assert by_id["control_d"]["score"] == by_id["control_a"]["score"] * 0.5


def test_hybrid_searcher_falls_back_to_keyword_when_embedding_unavailable(tmp_path):
    missing_path = tmp_path / "missing_embeddings.json"

    searcher = HybridSearcher(
        searcher=FakeSearcher(),
        emb_path=missing_path,
        host="http://127.0.0.1:9",
    )
    results = searcher.search("query", limit=2)

    assert [result["item"]["id"] for result in results] == ["control_a", "control_b"]
    assert {result["source"] for result in results} == {"keyword_fallback"}
    assert searcher.is_hybrid_ready is False


def test_hybrid_searcher_ablation_modes(tmp_path, monkeypatch):
    emb_path = tmp_path / "embeddings.json"
    kg_path = tmp_path / "knowledge_graph.json"
    _write_embeddings(emb_path)
    _write_kg(kg_path)
    monkeypatch.setattr(
        "iso27001_advisor.core.hybrid_search.get_embedding",
        lambda text, model, host: [0.0, 1.0],
    )

    # 1. 測試 mode='keyword'
    s_keyword = HybridSearcher(searcher=FakeSearcher(), emb_path=emb_path, kg_path=kg_path, mode="keyword")
    res_keyword = s_keyword.search("query", limit=4)
    assert [r["item"]["id"] for r in res_keyword] == ["control_a", "control_b"]
    assert {r["source"] for r in res_keyword} == {"keyword"}

    # 2. 測試 mode='keyword+KG'
    s_keyword_kg = HybridSearcher(searcher=FakeSearcher(), emb_path=emb_path, kg_path=kg_path, mode="keyword+KG")
    res_keyword_kg = s_keyword_kg.search("query", limit=4)
    # control_a -> control_d 關聯
    assert "control_d" in [r["item"]["id"] for r in res_keyword_kg]
    assert {r["source"] for r in res_keyword_kg} == {"keyword", "kg_1hop"}

    # 3. 測試 mode='keyword+RRF'
    s_keyword_rrf = HybridSearcher(searcher=FakeSearcher(), emb_path=emb_path, kg_path=kg_path, mode="keyword+RRF")
    res_keyword_rrf = s_keyword_rrf.search("query", limit=4)
    # 應包含向量相似的 control_c (因為 embedding 是 [0.0, 1.0])
    assert "control_c" in [r["item"]["id"] for r in res_keyword_rrf]
    # 不應包含由 KG 擴展產生的 control_d
    assert "control_d" not in [r["item"]["id"] for r in res_keyword_rrf]
    assert {r["source"] for r in res_keyword_rrf} == {"rrf"}

    # 4. 測試 mode='full'
    s_full = HybridSearcher(searcher=FakeSearcher(), emb_path=emb_path, kg_path=kg_path, mode="full")
    res_full = s_full.search("query", limit=4)
    # 應包含向量相關的 control_c 與 KG 擴展的 control_d
    ids = [r["item"]["id"] for r in res_full]
    assert "control_c" in ids
    assert "control_d" in ids
    assert {r["source"] for r in res_full} == {"rrf", "kg_1hop"}

