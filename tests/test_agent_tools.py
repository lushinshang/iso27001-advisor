"""tests/test_agent_tools.py
deterministic tools 單元測試 — 不呼叫 LLM，不需要 Ollama。
"""
import json
import sys
import os

from iso27001_advisor.tools.iso_tools import search_iso, get_clause
from iso27001_advisor.tools.gap_analysis_tools import analyze_document_coverage
from iso27001_advisor.tools.evidence_tools import generate_audit_evidence_checklist
from iso27001_advisor.tools.draft_tools import draft_gap_remediation


# ──────────────────────────────────────────────
# search_iso
# ──────────────────────────────────────────────

def test_search_iso_returns_json_serializable():
    results = search_iso("備份", top_k=2)
    assert isinstance(results, list)
    assert len(results) > 0
    json.dumps(results)  # 不拋出例外
    first = results[0]
    for key in ["id", "type", "section", "subsection", "content", "score"]:
        assert key in first, f"結果缺少欄位: {key}"


def test_search_iso_top_k_respected():
    results = search_iso("備份", top_k=2)
    assert len(results) <= 2


def test_search_iso_score_is_float():
    results = search_iso("備份", top_k=1)
    assert len(results) >= 1
    assert isinstance(results[0]["score"], float)


def test_search_iso_intent_boost_log_management():
    results = search_iso("系統會記錄登入登出並集中到 SIEM，保存 12 個月", top_k=4)
    ids = [r["id"] for r in results]
    assert "control_8.15" in ids


def test_search_iso_intent_boost_internal_audit_parent():
    results = search_iso("年度內部稽核計畫由稽核委員會核定，稽核報告提呈管理階層", top_k=4)
    ids = [r["id"] for r in results]
    assert "clause_9.2" in ids


def test_search_iso_intent_boost_personal_data_protection():
    results = search_iso("個人資料保護的稽核證據要準備哪些？", top_k=4)
    ids = [r["id"] for r in results]
    assert "control_5.34" in ids


def test_search_iso_multi_scope_audit_evidence_keeps_supplier_scope():
    query = (
        "下個月要做內部稽核，範圍包含供應商管理、備份、弱點管理與事件通報。"
        "請幫我列出應準備的稽核證據與優先補強事項。"
    )
    results = search_iso(query, top_k=4)
    ids = [r["id"] for r in results]
    assert any(i in ids for i in ["control_5.19", "control_5.20", "control_5.21", "control_5.22"])
    assert "control_8.13" in ids
    assert "control_8.8" in ids
    assert any(i in ids for i in ["control_5.24", "control_6.8"])


# ──────────────────────────────────────────────
# get_clause
# ──────────────────────────────────────────────

def test_get_clause_backup():
    item = get_clause("control_8.13")
    assert item is not None
    # 條文名稱應含「備份」或 ID 應含 8.13
    assert "備份" in item.get("subsection", "") or "8.13" in item["id"]


def test_get_clause_case_insensitive():
    assert get_clause("CONTROL_8.13") is not None, "大寫 ID 應可查詢"
    assert get_clause("Control_8.13") is not None, "首字大寫 ID 應可查詢"


def test_get_clause_not_found():
    assert get_clause("nonexistent_99.99") is None


def test_get_clause_returns_json_serializable():
    item = get_clause("control_8.13")
    assert item is not None
    json.dumps(item)  # 不拋出例外


# ──────────────────────────────────────────────
# analyze_document_coverage
# ──────────────────────────────────────────────

def test_analyze_coverage_backup_missing_restore():
    doc = "我們公司每日凌晨自動備份資料庫，備份檔保存在 NAS，IT 每週檢查備份成功與否。"
    items = search_iso("備份", top_k=4)
    result = analyze_document_coverage(doc, items)
    assert "covered_signals" in result
    assert "missing_signals" in result
    assert "risk_level" in result
    themes = [s["theme"] for s in result["missing_signals"]]
    assert any("還原" in t for t in themes), f"期望找到還原測試缺口，實際: {themes}"


def test_analyze_coverage_json_serializable():
    doc = "我們有備份政策。"
    items = search_iso("備份", top_k=2)
    result = analyze_document_coverage(doc, items)
    json.dumps(result)  # 不拋出例外


def test_analyze_coverage_risk_level_values():
    doc = "我們有備份政策。"
    items = search_iso("備份", top_k=4)
    result = analyze_document_coverage(doc, items)
    assert result["risk_level"] in ("low", "medium", "high")


def test_analyze_coverage_no_relevant_items():
    """matched_items 無對應 GAP_THEMES 時，應回傳 low risk 並帶 notes。"""
    doc = "任意文件。"
    # 傳入不存在於 GAP_THEMES 的條文
    items = [{"id": "clause_4.1", "type": "clause", "section": "4", "subsection": "組織環境", "content": ""}]
    result = analyze_document_coverage(doc, items)
    assert result["risk_level"] == "low"
    assert len(result["notes"]) > 0


def test_analyze_coverage_full_match_low_risk():
    """提供涵蓋所有備份關鍵字的文件，missing_signals 應為空。"""
    doc = (
        "我們公司每日凌晨自動備份資料庫，備份檔保存在 NAS，IT 每週檢查備份成功與否。"
        "每季執行還原測試，還原記錄存檔。"
        "備份資料保存期限為 90 天，備份檔使用 AES-256 加密，同時維持異地備份。"
        "備份失敗時系統自動告警通知管理員。"
    )
    items = search_iso("備份", top_k=1)
    result = analyze_document_coverage(doc, items)
    assert result["risk_level"] == "low"
    assert len(result["missing_signals"]) == 0


def test_analyze_coverage_detects_insufficient_log_retention():
    doc = "系統日誌自動保存 30 天，到期後自動刪除。每週由 IT 人員查看是否有異常。"
    items = [{"id": "control_8.15"}]
    result = analyze_document_coverage(doc, items)
    themes = [s["theme"] for s in result["missing_signals"]]
    assert "日誌保存期限" in themes


def test_analyze_coverage_detects_account_deactivation_gap():
    doc = "我們有帳號申請與核准流程，採最小權限原則，每年做一次覆核。但人員異動很頻繁，沒有明確規定離職後多久要停用帳號。"
    items = [{"id": "control_5.15"}]
    result = analyze_document_coverage(doc, items)
    themes = [s["theme"] for s in result["missing_signals"]]
    assert "帳號停用程序" in themes


# ──────────────────────────────────────────────
# generate_audit_evidence_checklist
# ──────────────────────────────────────────────

def test_evidence_checklist_backup():
    result = generate_audit_evidence_checklist(["control_8.13"])
    assert len(result) == 1
    assert result[0]["clause_id"] == "control_8.13"
    evidence_text = " ".join(result[0]["evidence"])
    assert "還原" in evidence_text, f"期望含還原測試，實際: {evidence_text}"


def test_evidence_checklist_unknown_id():
    result = generate_audit_evidence_checklist(["nonexistent_99.99"])
    assert result == []


def test_evidence_checklist_case_insensitive():
    """clause_id 大小寫不敏感（generate_audit_evidence_checklist 內部做 lower()）。"""
    result_lower = generate_audit_evidence_checklist(["control_8.13"])
    result_upper = generate_audit_evidence_checklist(["CONTROL_8.13"])
    assert len(result_lower) == len(result_upper)
    assert result_lower[0]["evidence"] == result_upper[0]["evidence"]


def test_evidence_checklist_multiple_ids():
    ids = ["control_8.13", "control_8.8", "nonexistent_99.99"]
    result = generate_audit_evidence_checklist(ids)
    returned_ids = [r["clause_id"] for r in result]
    assert "control_8.13" in returned_ids
    assert "control_8.8" in returned_ids
    assert "nonexistent_99.99" not in returned_ids


def test_evidence_checklist_json_serializable():
    result = generate_audit_evidence_checklist(["control_8.13"])
    json.dumps(result)  # 不拋出例外


# ──────────────────────────────────────────────
# draft_gap_remediation
# ──────────────────────────────────────────────

def test_draft_gap_remediation_with_gaps():
    doc = "我們公司每日自動備份資料庫。"
    items = search_iso("備份", top_k=4)
    gap_result = analyze_document_coverage(doc, items)
    clause_ids = [r["id"] for r in items]
    bullets = draft_gap_remediation(gap_result, clause_ids)
    assert isinstance(bullets, list)
    assert len(bullets) > 0
    assert all(isinstance(b, str) for b in bullets)


def test_draft_gap_remediation_no_gaps():
    gap_result = {
        "covered_signals": [],
        "missing_signals": [],
        "risk_level": "low",
        "notes": [],
    }
    bullets = draft_gap_remediation(gap_result, [])
    assert isinstance(bullets, list)
    assert len(bullets) > 0


def test_draft_gap_remediation_contains_restore_suggestion():
    """missing_signals 含還原測試時，建議清單應含對應補強文字。"""
    gap_result = {
        "covered_signals": [],
        "missing_signals": [{"theme": "還原測試", "reason": "文件未描述還原測試"}],
        "risk_level": "high",
        "notes": [],
    }
    bullets = draft_gap_remediation(gap_result, ["control_8.13"])
    combined = " ".join(bullets)
    assert "還原" in combined, f"期望含還原相關建議，實際: {bullets}"
