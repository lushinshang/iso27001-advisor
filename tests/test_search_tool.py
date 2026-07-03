"""
tests/test_search_tool.py
搜尋引擎核心邏輯單元測試 — ISO 27001 Advisor Agent v1.2
注意：searcher fixture 由 conftest.py 統一提供（scope=session）
"""
import sys
import os
import pytest

from iso27001_advisor.core.search_tool import ISO27001Searcher



# ===========================================================
# ST-01 ~ ST-04 初始化與精確查詢
# ===========================================================

class TestInitialization:
    def test_ST01_load_success(self, searcher):
        """ST-01: 正常載入，items 非空"""
        assert len(searcher.items) > 0, "items 不應為空"

    def test_ST01_has_clauses_and_controls(self, searcher):
        """ST-01 延伸: 應同時包含 clause 與 control 類型"""
        types = {item["type"] for item in searcher.items}
        assert "clause" in types, "應包含 clause 類型"
        assert "control" in types, "應包含 control 類型"

    def test_init_file_not_found(self):
        """載入不存在的 JSON 路徑應拋出 FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            ISO27001Searcher(json_path="/tmp/nonexistent_12345.json")


class TestGetById:
    def test_ST02_exact_id_found(self, searcher):
        """ST-02: 精確 ID 查詢應回傳正確 item"""
        item = searcher.get_by_id("control_8.11")
        assert item is not None, "control_8.11 應存在"
        assert "資料遮罩" in item.get("title", "") or "資料遮罩" in item.get("subsection", ""), \
            "control_8.11 應為資料遮罩"

    def test_ST03_case_insensitive(self, searcher):
        """ST-03: 大小寫不敏感"""
        item_lower = searcher.get_by_id("control_8.11")
        item_upper = searcher.get_by_id("CONTROL_8.11")
        assert item_lower is not None
        assert item_upper is not None
        assert item_lower["id"] == item_upper["id"]

    def test_ST04_not_found(self, searcher):
        """ST-04: 不存在的 ID 應回傳 None"""
        item = searcher.get_by_id("control_99.99")
        assert item is None

    def test_control_5_34_pii(self, searcher):
        """control_5.34 應為隱私及 PII 保護"""
        item = searcher.get_by_id("control_5.34")
        assert item is not None
        assert "隱私" in item.get("title", "") or "PII" in item.get("title", "").upper()

    def test_control_8_12_dlp(self, searcher):
        """control_8.12 應為資料洩漏預防"""
        item = searcher.get_by_id("control_8.12")
        assert item is not None
        assert "洩漏" in item.get("title", "") or "洩漏" in item.get("subsection", "")

    def test_clause_6_1_2_risk_assessment(self, searcher):
        """clause_6.1.2 應存在且相關風險評鑑"""
        item = searcher.get_by_id("clause_6.1.2")
        assert item is not None


# ===========================================================
# ST-05 ~ ST-06 搜尋邊界條件
# ===========================================================

class TestSearchBoundary:
    def test_ST05_limit_respected(self, searcher):
        """ST-05: 搜尋結果數量不超過 limit"""
        results = searcher.search("風險評鑑", limit=4)
        assert len(results) <= 4

    def test_ST06_empty_query_returns_empty_list(self, searcher):
        """ST-06: 空字串查詢應回傳空 list"""
        results = searcher.search("")
        assert results == []

    def test_limit_zero(self, searcher):
        """limit=0 應回傳空 list"""
        results = searcher.search("風險", limit=0)
        assert results == []

    def test_limit_negative_returns_empty(self, searcher):
        """limit=-1 應回傳空 list，防禦 Python slice [-1] 造成除最後一筆外的所有結果"""
        results = searcher.search("風險", limit=-1)
        assert results == []

    def test_limit_one(self, searcher):
        """limit=1 應只回傳最高分的一筆"""
        results = searcher.search("備份", limit=1)
        assert len(results) <= 1

    def test_ST12_type_filter_control(self, searcher):
        """ST-12: item_type='control' 篩選後，結果全為 control 類型"""
        results = searcher.search("存取控制", item_type="control", limit=5)
        for r in results:
            assert r["item"]["type"] == "control", f"期望 control 類型，但得到 {r['item']['type']}"

    def test_ST12_type_filter_clause(self, searcher):
        """ST-12 延伸: item_type='clause' 篩選後，結果全為 clause 類型"""
        results = searcher.search("管理審查", item_type="clause", limit=5)
        for r in results:
            assert r["item"]["type"] == "clause", f"期望 clause 類型，但得到 {r['item']['type']}"


# ===========================================================
# ST-07 ~ ST-10 同義詞擴充與 Soul-Word 加權
# ===========================================================

class TestSynonymExpansionAndSoulWords:
    def _get_top_k_ids(self, searcher, query, limit=4):
        results = searcher.search(query, limit=limit)
        return [r["item"]["id"] for r in results]

    def test_ST07_synonym_pii(self, searcher):
        """ST-07: 查詢「個資保護」，control_5.34 應在 top-4"""
        ids = self._get_top_k_ids(searcher, "個資保護", limit=4)
        assert "control_5.34" in ids, f"control_5.34 未在 top-4: {ids}"

    def test_ST08_synonym_encryption(self, searcher):
        """ST-08: 查詢「系統加密要求」，control_8.24 應在 top-4"""
        ids = self._get_top_k_ids(searcher, "系統加密要求", limit=4)
        assert "control_8.24" in ids, f"control_8.24 未在 top-4: {ids}"

    def test_ST09_soul_word_backup(self, searcher):
        """ST-09: 查詢「備份策略與要求」，control_8.13 應在 top-3"""
        ids = self._get_top_k_ids(searcher, "備份策略與要求", limit=3)
        assert "control_8.13" in ids, f"control_8.13 未在 top-3: {ids}"

    def test_ST10_soul_word_data_masking(self, searcher):
        """ST-10: 查詢「資料遮罩控制」，control_8.11 應在 top-3"""
        ids = self._get_top_k_ids(searcher, "資料遮罩控制", limit=3)
        assert "control_8.11" in ids, f"control_8.11 未在 top-3: {ids}"

    def test_soul_word_threat_intelligence(self, searcher):
        """查詢「威脅情資」，control_5.7 應在 top-4"""
        ids = self._get_top_k_ids(searcher, "威脅情資的收集", limit=4)
        assert "control_5.7" in ids, f"control_5.7 未在 top-4: {ids}"

    def test_soul_word_clean_desk(self, searcher):
        """查詢「桌面淨空」，control_7.7 應在 top-3"""
        ids = self._get_top_k_ids(searcher, "桌面淨空螢幕淨空政策", limit=3)
        assert "control_7.7" in ids, f"control_7.7 未在 top-3: {ids}"


# ===========================================================
# ST-11 大章節降權測試
# ===========================================================

class TestSectionHeaderPenalty:
    def test_ST11_parent_section_has_lower_score(self, searcher):
        """ST-11: 父章節（不含小數點的 ID）得分應低於子條文"""
        results = searcher.search("風險評鑑準則識別", limit=10)
        # clause_6 (父章節) 分數應低於 clause_6.1.2 (子條文)
        scores = {r["item"]["id"]: r["score"] for r in results}

        # clause_6 可能分數很低甚至不出現，這是預期行為
        if "clause_6" in scores and "clause_6.1.2" in scores:
            assert scores["clause_6"] < scores["clause_6.1.2"], \
                "父章節 clause_6 分數應低於子條文 clause_6.1.2"

    def test_parent_section_not_in_top3(self, searcher):
        """父章節不應出現在高度具體問題的 top-3 結果中"""
        results = searcher.search("資料遮罩控制措施", limit=3)
        ids = [r["item"]["id"] for r in results]
        # control_8（父章節，無小數）不應在精確問題的 top-3
        assert "control_8" not in ids, f"父章節 control_8 不應在 top-3: {ids}"


# ===========================================================
# 分數合理性測試
# ===========================================================

class TestScoreRationality:
    def test_scores_are_positive(self, searcher):
        """所有回傳結果的分數應為正數"""
        results = searcher.search("風險評鑑", limit=5)
        for r in results:
            assert r["score"] > 0, f"分數應為正數，但得到 {r['score']}"

    def test_results_sorted_by_score(self, searcher):
        """結果應依分數由高到低排序"""
        results = searcher.search("內部稽核計畫", limit=5)
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True), "結果應依分數降序排列"

    def test_v11_sensitive_pii_recalls_data_masking(self, searcher):
        """v1.1 新需求：查詢「敏感性個資保護」應能找到 control_8.11 (資料遮罩)"""
        results = searcher.search("敏感性個資保護控制措施", limit=5)
        ids = [r["item"]["id"] for r in results]
        assert "control_8.11" in ids, \
            f"[v1.1 目標] control_8.11 (資料遮罩) 未在 top-5 結果中。當前結果: {ids}"

    def test_v11_sensitive_pii_recalls_dlp(self, searcher):
        """v1.1 新需求：查詢「敏感性個資保護」應能找到 control_8.12 (資料洩漏預防)"""
        results = searcher.search("敏感性個資保護控制措施", limit=5)
        ids = [r["item"]["id"] for r in results]
        assert "control_8.12" in ids, \
            f"[v1.1 目標] control_8.12 (資料洩漏預防) 未在 top-5 結果中。當前結果: {ids}"
