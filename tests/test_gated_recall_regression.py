"""gated hybrid 雙資料集回歸護欄。

測試開頭先探測 localhost Ollama embedding 是否可用；若不可用就 skip。
正式評估階段不捕捉例外，避免把真正的檢索 bug 誤判為離線退化。
"""

import json
from pathlib import Path

import pytest

from iso27001_advisor.core.hybrid_search import HybridSearcher
from iso27001_advisor.core.semantic_cache import EMBED_MODEL, OLLAMA_HOST, get_embedding


BASE_DIR = Path(__file__).resolve().parents[1]
ORIGINAL_DATASET = BASE_DIR / "data" / "eval_dataset.json"
PARAPHRASE_DATASET = BASE_DIR / "data" / "eval_dataset_paraphrase.json"


def _load_dataset(path):
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if isinstance(payload, dict) and "dataset" in payload:
        return payload["dataset"]
    return payload


def _assert_hit_count_floor(searcher, dataset_path, floor_hits, top_k=4):
    # 下限採「整數命中題數」而非百分比：v1.4 實測值為 59/60 與 46/60，
    # 百分比比較會因捨入（46/60=76.666..% vs 報表的 76.7%）產生永久紅燈。
    dataset = _load_dataset(dataset_path)
    failures = []
    hit_count = 0

    for item in dataset:
        expected = set(item["expected_clauses"])
        results = searcher.search(item["question"], limit=top_k)
        retrieved = [result["item"]["id"] for result in results]
        if expected.intersection(retrieved):
            hit_count += 1
        else:
            failures.append({
                "id": item["id"],
                "question": item["question"][:50],
                "expected": sorted(expected),
                "retrieved": retrieved,
            })

    assert hit_count >= floor_hits, (
        f"{dataset_path.name} gated Hit@{top_k} = {hit_count}/{len(dataset)} "
        f"< 下限 {floor_hits}/{len(dataset)}\n失敗題目: {failures}"
    )


@pytest.fixture(scope="module")
def gated_searcher():
    try:
        get_embedding("query: gated regression readiness probe", EMBED_MODEL, OLLAMA_HOST)
    except Exception as exc:
        pytest.skip(f"Ollama embedding 不可用，略過 gated 回歸測試: {exc}")
    return HybridSearcher(mode="gated")


def test_original_dataset_gated_hit_rate_floor(gated_searcher):
    """原 60 題：gated 命中題數不低於 v1.4 實測下限 59/60（98.3%）。"""
    _assert_hit_count_floor(gated_searcher, ORIGINAL_DATASET, floor_hits=59)


def test_paraphrase_dataset_gated_hit_rate_floor(gated_searcher):
    """改寫 60 題：gated 命中題數不低於 v1.4 實測下限 46/60（76.7%）。"""
    _assert_hit_count_floor(gated_searcher, PARAPHRASE_DATASET, floor_hits=46)
