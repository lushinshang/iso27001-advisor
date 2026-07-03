"""
tests/test_recall_regression.py
Recall@4 回歸測試 — ISO 27001 Advisor Agent v1.2
確保每次改動後，10 題評估資料集的 Hit Rate 不退化
注意：searcher 與 eval_dataset fixture 由 conftest.py 統一提供（scope=session）
"""
import sys
import os
import pytest


def get_top_k_ids(searcher, question, limit=4):
    results = searcher.search(question, limit=limit)
    return [r["item"]["id"] for r in results]


class TestRecallRegression:
    """
    Recall@4 回歸測試套件
    每個測試對應 eval_dataset.json 的一個問題
    成功標準：在 Top-4 結果中至少命中 expected_clauses 中的一個
    """

    def test_REG_q1_isms_scope(self, searcher):
        """REG-q1: 如何決定 ISMS 的適用範圍？"""
        question = "如何決定 ISMS 的適用範圍？我們需要考量哪些因素？"
        expected = {"clause_4.3", "clause_4.1", "clause_4.2"}
        ids = set(get_top_k_ids(searcher, question, limit=4))
        hits = expected & ids
        assert len(hits) > 0, \
            f"REG-q1 失敗: 期望 {expected}，但 top-4 只有 {ids}"

    def test_REG_q2_risk_assessment(self, searcher):
        """REG-q2: 如何進行資訊安全風險評鑑？"""
        question = "ISO 27001 要求我們如何進行資訊安全風險評鑑？"
        expected = {"clause_6.1.2"}
        ids = set(get_top_k_ids(searcher, question, limit=4))
        hits = expected & ids
        assert len(hits) > 0, \
            f"REG-q2 失敗: 期望 {expected}，但 top-4 只有 {ids}"

    def test_REG_q3_leadership(self, searcher):
        """REG-q3: 最高管理階層展現領導力"""
        question = "最高管理階層應如何展現對資訊安全管理系統的領導力與承諾？"
        expected = {"clause_5.1"}
        ids = set(get_top_k_ids(searcher, question, limit=4))
        hits = expected & ids
        assert len(hits) > 0, \
            f"REG-q3 失敗: 期望 {expected}，但 top-4 只有 {ids}"

    def test_REG_q4_threat_intelligence(self, searcher):
        """REG-q4: 威脅情資的收集"""
        question = "ISO 27001 對於威脅情資（Threat Intelligence）的收集有什麼具體要求？"
        expected = {"control_5.7"}
        ids = set(get_top_k_ids(searcher, question, limit=4))
        hits = expected & ids
        assert len(hits) > 0, \
            f"REG-q4 失敗: 期望 {expected}，但 top-4 只有 {ids}"

    def test_REG_q5_intellectual_property(self, searcher):
        """REG-q5: 保護智慧財產權"""
        question = "為了保護智慧財產權，我們在 ISO 27001 框架下需要注意什麼？"
        expected = {"control_5.32"}
        ids = set(get_top_k_ids(searcher, question, limit=4))
        hits = expected & ids
        assert len(hits) > 0, \
            f"REG-q5 失敗: 期望 {expected}，但 top-4 只有 {ids}"

    def test_REG_q6_internal_audit(self, searcher):
        """REG-q6: 內部稽核計畫"""
        question = "組織需要定期進行內部稽核嗎？稽核計畫該怎麼建立？"
        expected = {"clause_9.2", "clause_9.2.1", "clause_9.2.2"}
        ids = set(get_top_k_ids(searcher, question, limit=4))
        hits = expected & ids
        assert len(hits) > 0, \
            f"REG-q6 失敗: 期望 {expected}，但 top-4 只有 {ids}"

    def test_REG_q7_backup(self, searcher):
        """REG-q7: 資訊系統備份控制"""
        question = "對於資訊系統的備份，有什麼控制措施要求？稽核時需要提供什麼證據？"
        expected = {"control_8.13"}
        ids = set(get_top_k_ids(searcher, question, limit=4))
        hits = expected & ids
        assert len(hits) > 0, \
            f"REG-q7 失敗: 期望 {expected}，但 top-4 只有 {ids}"

    def test_REG_q8_clean_desk_screen(self, searcher):
        """REG-q8: 桌面淨空與螢幕淨空"""
        question = "我們該如何實施桌面淨空與螢幕淨空（Clean desk and clean screen）？"
        expected = {"control_7.7"}
        ids = set(get_top_k_ids(searcher, question, limit=4))
        hits = expected & ids
        assert len(hits) > 0, \
            f"REG-q8 失敗: 期望 {expected}，但 top-4 只有 {ids}"

    def test_REG_q9_management_review(self, searcher):
        """REG-q9: 管理審查的輸入項目"""
        question = "管理審查（Management Review）的輸入項目有哪些？"
        expected = {"clause_9.3", "clause_9.3.2"}
        ids = set(get_top_k_ids(searcher, question, limit=4))
        hits = expected & ids
        assert len(hits) > 0, \
            f"REG-q9 失敗: 期望 {expected}，但 top-4 只有 {ids}"

    def test_REG_q10_v10_at_least_one_hit(self, searcher):
        """REG-q10 v1.0 最低標準: 至少命中一個期望條款"""
        question = "公司要處理敏感性個資，ISO 27001 建議使用什麼控制措施來保護這些敏感資料？"
        expected = {"control_8.11", "control_8.12", "control_5.34"}
        ids = set(get_top_k_ids(searcher, question, limit=4))
        hits = expected & ids
        assert len(hits) > 0, \
            f"REG-q10 基本 Hit 失敗: 期望 {expected}，但 top-4 只有 {ids}"

    def test_REG_q10_v12_recall_data_masking(self, searcher):
        """REG-q10 v1.2 正式回歸: control_8.11 (資料遮罩) 必須在 top-4"""
        question = "公司要處理敏感性個資，ISO 27001 建議使用什麼控制措施來保護這些敏感資料？"
        ids = set(get_top_k_ids(searcher, question, limit=4))
        assert "control_8.11" in ids, \
            f"[v1.2 回歸] control_8.11 未在 top-4: {ids}"

    def test_REG_q10_v12_recall_dlp(self, searcher):
        """REG-q10 v1.2 正式回歸: control_8.12 (資料洩漏預防) 必須在 top-4"""
        question = "公司要處理敏感性個資，ISO 27001 建議使用什麼控制措施來保護這些敏感資料？"
        ids = set(get_top_k_ids(searcher, question, limit=4))
        assert "control_8.12" in ids, \
            f"[v1.2 回歸] control_8.12 未在 top-4: {ids}"


class TestFullDatasetHitRate:
    """全資料集命中率測試：確保整體 Hit Rate = 100%"""

    def test_all_10_questions_at_least_one_hit(self, searcher, eval_dataset):
        """10 題全部 Hit Rate@4 ≥ 100%（每題至少命中一個期望條款）"""
        failures = []
        for item in eval_dataset:
            question = item["question"]
            expected = set(item["expected_clauses"])
            ids = set(get_top_k_ids(searcher, question, limit=4))
            hits = expected & ids
            if len(hits) == 0:
                failures.append({
                    "id": item["id"],
                    "question": question[:40],
                    "expected": list(expected),
                    "got": list(ids)
                })

        assert len(failures) == 0, \
            f"以下問題 Recall@4 = 0 (完全未命中):\n" + \
            "\n".join([f"  [{f['id']}] {f['question']}... | 期望: {f['expected']} | 得到: {f['got']}"
                       for f in failures])

    def test_recall_metrics_report(self, searcher, eval_dataset):
        """產出 Recall 詳細報表（資訊性測試，不會 FAIL）"""
        print("\n\n📊 Recall@4 詳細報表:")
        print("=" * 70)
        total_recall = 0
        for item in eval_dataset:
            question = item["question"]
            expected = set(item["expected_clauses"])
            ids_list = get_top_k_ids(searcher, question, limit=4)
            ids = set(ids_list)
            hits = expected & ids
            recall = len(hits) / len(expected)
            total_recall += recall
            status = "✅" if recall > 0 else "❌"
            print(f"{status} [{item['id']}] Recall={recall:.2f} | {question[:35]}...")
        avg_recall = total_recall / len(eval_dataset)
        print("=" * 70)
        print(f"📈 平均 Recall@4: {avg_recall:.3f} ({avg_recall*100:.1f}%)")
        # 這個測試永遠通過，只是輸出報表
        assert True
