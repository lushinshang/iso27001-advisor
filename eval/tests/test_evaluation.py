"""
tests/test_evaluation.py
evaluation.py 核心函式單元測試 — ISO 27001 Advisor Agent v1.2

測試對象：
  - compute_recall()：Recall 計算邏輯
  - compute_mrr()：MRR Reciprocal Rank 計算邏輯
  - evaluate_retrieval()：端對端整合（輸出格式驗證）
"""
import os
import json
import pytest

from eval.evaluation import compute_recall, compute_precision, compute_mrr


# ===========================================================
# compute_recall() 單元測試
# ===========================================================

class TestComputeRecall:

    def test_recall_all_hit(self):
        """全部期望條款都命中 → Recall = 1.0"""
        expected = ["clause_6.1.2", "clause_8.2"]
        retrieved = ["clause_6.1.2", "clause_8.2", "clause_4.1"]
        assert compute_recall(expected, retrieved) == 1.0

    def test_recall_partial_hit(self):
        """部分命中 → Recall = 命中數 / 期望總數"""
        expected = ["clause_4.3", "clause_4.1", "clause_4.2"]
        retrieved = ["clause_4.3", "clause_6.1.3", "clause_4.2", "clause_9.1"]
        result = compute_recall(expected, retrieved)
        assert abs(result - 2 / 3) < 1e-9, f"期望 2/3，但得到 {result}"

    def test_recall_no_hit(self):
        """完全沒命中 → Recall = 0.0"""
        expected = ["control_8.11", "control_8.12"]
        retrieved = ["clause_4.1", "clause_5.1", "clause_6.1.2", "clause_9.1"]
        assert compute_recall(expected, retrieved) == 0.0

    def test_recall_empty_expected(self):
        """期望清單為空 → Recall = 0.0（防呆）"""
        assert compute_recall([], ["clause_4.1"]) == 0.0

    def test_recall_empty_retrieved(self):
        """檢索結果為空 → Recall = 0.0"""
        assert compute_recall(["clause_4.1"], []) == 0.0

    def test_recall_both_empty(self):
        """期望與結果都為空 → Recall = 0.0"""
        assert compute_recall([], []) == 0.0

    def test_recall_single_expected_hit(self):
        """單一期望條款命中 → Recall = 1.0"""
        assert compute_recall(["control_5.7"], ["control_5.7", "clause_6.1.1"]) == 1.0

    def test_recall_single_expected_miss(self):
        """單一期望條款未命中 → Recall = 0.0"""
        assert compute_recall(["control_5.7"], ["control_5.1", "clause_6.1.1"]) == 0.0

    def test_recall_order_irrelevant(self):
        """Recall 不關心順序，只關心是否命中"""
        expected = ["a", "b", "c"]
        # c、b 命中（順序不同）
        assert compute_recall(expected, ["c", "x", "b"]) == pytest.approx(2 / 3)

    def test_recall_duplicate_in_retrieved_does_not_inflate(self):
        """retrieved 中有重複 ID 不應影響 Recall 計算（只算有沒有，不算幾個）"""
        expected = ["clause_4.1"]
        retrieved = ["clause_4.1", "clause_4.1", "clause_4.1"]
        assert compute_recall(expected, retrieved) == 1.0


# ===========================================================
# compute_precision() 單元測試
# ===========================================================
class TestComputePrecision:
    def test_precision_all_relevant(self):
        """retrieved 全部命中 → Precision = 1.0"""
        assert compute_precision(["a", "b"], ["a", "b"]) == 1.0

    def test_precision_partial(self):
        """retrieved 4 筆中 2 筆命中 → Precision = 0.5"""
        assert compute_precision(["a", "b"], ["a", "x", "b", "y"]) == pytest.approx(0.5)

    def test_precision_no_hit(self):
        """完全沒有命中 → Precision = 0.0"""
        assert compute_precision(["a"], ["x", "y"]) == 0.0

    def test_precision_empty_retrieved(self):
        """retrieved 為空 → Precision = 0.0（避免除零）"""
        assert compute_precision(["a"], []) == 0.0

    def test_precision_empty_expected(self):
        """expected 為空但 retrieved 有值 → Precision = 0.0"""
        assert compute_precision([], ["a", "b"]) == 0.0

    def test_precision_single_hit(self):
        """top-4 中只有 1 筆命中 → Precision = 0.25"""
        assert compute_precision(["a"], ["a", "x", "y", "z"]) == pytest.approx(0.25)


# ===========================================================
# compute_mrr() 單元測試
# ===========================================================

class TestComputeMrr:

    def test_mrr_first_position(self):
        """期望條款排第 1 → RR = 1.0"""
        expected = ["control_5.7"]
        retrieved = ["control_5.7", "clause_6.1.1", "clause_4.1"]
        assert compute_mrr(expected, retrieved) == 1.0

    def test_mrr_second_position(self):
        """期望條款排第 2 → RR = 0.5"""
        expected = ["clause_5.1"]
        retrieved = ["clause_4.3", "clause_5.1", "clause_6.1.2"]
        assert compute_mrr(expected, retrieved) == pytest.approx(1 / 2)

    def test_mrr_third_position(self):
        """期望條款排第 3 → RR = 1/3"""
        expected = ["clause_5.1"]
        retrieved = ["clause_4.3", "clause_4.4", "clause_5.1", "clause_6.1.2"]
        assert compute_mrr(expected, retrieved) == pytest.approx(1 / 3)

    def test_mrr_no_hit(self):
        """完全沒命中 → RR = 0.0"""
        expected = ["control_8.11"]
        retrieved = ["clause_4.1", "clause_5.1", "clause_6.1.2"]
        assert compute_mrr(expected, retrieved) == 0.0

    def test_mrr_empty_retrieved(self):
        """檢索結果為空 → RR = 0.0"""
        assert compute_mrr(["clause_4.1"], []) == 0.0

    def test_mrr_empty_expected(self):
        """期望清單為空 → RR = 0.0（無法命中任何）"""
        assert compute_mrr([], ["clause_4.1", "clause_5.1"]) == 0.0

    def test_mrr_multiple_expected_first_hit_wins(self):
        """多個期望條款，以最先命中的那個計算 RR"""
        expected = ["clause_4.1", "clause_5.1"]
        # clause_5.1 在第 2 位，clause_4.1 在第 4 位
        retrieved = ["clause_6.1.2", "clause_5.1", "clause_9.1", "clause_4.1"]
        # 最先命中的是 clause_5.1（rank=2），RR = 0.5
        assert compute_mrr(expected, retrieved) == pytest.approx(1 / 2)

    def test_mrr_value_range(self):
        """RR 值域應在 [0, 1] 之間"""
        expected = ["clause_4.1"]
        retrieved = ["x", "y", "z", "clause_4.1"]
        rr = compute_mrr(expected, retrieved)
        assert 0.0 <= rr <= 1.0

    def test_mrr_is_reciprocal_of_rank(self):
        """RR 精確等於 1/rank_of_first_hit"""
        expected = ["target"]
        for rank in range(1, 6):
            retrieved = [f"irrelevant_{i}" for i in range(rank - 1)] + ["target"]
            expected_rr = 1.0 / rank
            assert compute_mrr(expected, retrieved) == pytest.approx(expected_rr), \
                f"rank={rank} 時 RR 應為 {expected_rr}"


# ===========================================================
# evaluate_retrieval() 整合測試（驗證輸出格式，不驗證具體數值）
# ===========================================================

class TestEvaluateRetrieval:

    @pytest.fixture
    def run_eval(self, searcher, tmp_path):
        """Helper fixture 用來動態執行 evaluate_retrieval"""
        import shutil
        from eval.evaluation import evaluate_retrieval

        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        orig_dataset = os.path.join(base_dir, "data", "eval_dataset.json")
        
        dataset_path = tmp_path / "eval_dataset.json"
        shutil.copy(orig_dataset, dataset_path)
        results_path = tmp_path / "eval_results.json"
        
        evaluate_retrieval(
            top_k=4,
            dataset_path=str(dataset_path),
            results_path=str(results_path),
            searcher=searcher
        )
        
        with open(results_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_eval_results_json_schema(self, run_eval):
        """eval_results.json 應包含所有必要欄位（v1.2 schema）"""
        r = run_eval

        # 頂層欄位
        required_top = {"top_k", "total_questions", "retrieval_success_count",
                        "hit_rate_percent", "avg_recall_percent", "avg_precision_percent", "mrr", "details"}
        missing = required_top - set(r.keys())
        assert not missing, f"eval_results.json 缺少欄位: {missing}"

        # 每筆 detail 欄位
        required_detail = {"id", "category", "question", "expected_clauses",
                           "retrieved_clauses", "recall", "precision", "reciprocal_rank", "success"}
        for detail in r["details"]:
            missing_d = required_detail - set(detail.keys())
            assert not missing_d, f"detail {detail.get('id')} 缺少欄位: {missing_d}"

    def test_eval_mrr_in_valid_range(self, run_eval):
        """eval_results.json 的 MRR 值應在 (0, 1] 之間"""
        r = run_eval
        assert 0 < r["mrr"] <= 1.0, f"MRR 應在 (0,1]，但得到 {r['mrr']}"

    def test_eval_hit_rate_100_percent(self, run_eval):
        """Hit Rate 應維持在 100%（回歸保護）"""
        r = run_eval
        assert r["hit_rate_percent"] == 100.0, \
            f"Hit Rate 應為 100%，但得到 {r['hit_rate_percent']}%"

    def test_eval_recall_and_rr_consistency(self, run_eval):
        """若 recall=0 則 reciprocal_rank 也應為 0（邏輯一致性）"""
        r = run_eval
        for d in r["details"]:
            if d["recall"] == 0.0:
                assert d["reciprocal_rank"] == 0.0, \
                    f"{d['id']}: recall=0 但 rr={d['reciprocal_rank']}，邏輯不一致"
