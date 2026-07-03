"""tests/test_level3_tools.py
Level 3 tools 的 deterministic 測試 — 不呼叫 LLM，不需要 Ollama。
"""
import json
import os
import sys
import tempfile
from pathlib import Path


from iso27001_advisor.tools.soa_tools import draft_soa_statement, build_soa_matrix
from iso27001_advisor.tools.audit_report_tools import build_audit_readiness_report, build_audit_question_pack
from iso27001_advisor.tools.action_plan_tools import build_remediation_roadmap
from iso27001_advisor.tools.export_tools import export_markdown_report


# ──────────────────────────────────────────────
# draft_soa_statement
# ──────────────────────────────────────────────

def test_soa_statement_json_serializable():
    row = draft_soa_statement("control_8.13")
    json.dumps(row)  # 若不可序列化則拋 TypeError


def test_soa_statement_has_required_fields():
    row = draft_soa_statement("control_8.13")
    for key in ["control_id", "control_name", "applicability", "applicability_reason",
                "implementation_status", "implementation_summary", "gaps", "evidence", "recommendation"]:
        assert key in row, f"缺少欄位: {key}"


def test_soa_statement_with_gaps_is_partial():
    gap_result = {
        "covered_signals": [{"keyword": "備份"}],
        "missing_signals": [{"theme": "還原測試"}, {"theme": "備份保存期限"}],
        "risk_level": "high",
        "notes": [],
    }
    row = draft_soa_statement("control_8.13", gap_result=gap_result)
    assert row["implementation_status"] == "部分實作"
    assert "還原測試" in row["gaps"]


def test_soa_statement_without_gaps_is_verified():
    gap_result = {
        "covered_signals": [{"keyword": "備份"}],
        "missing_signals": [],
        "risk_level": "low",
        "notes": [],
    }
    row = draft_soa_statement("control_8.13", implementation_summary="每日備份", gap_result=gap_result)
    assert row["implementation_status"] == "已實作待驗證"


def test_soa_statement_no_description_is_pending():
    row = draft_soa_statement("control_8.13")
    assert row["implementation_status"] == "待確認"


def test_soa_statement_applicability_default():
    row = draft_soa_statement("control_8.13")
    assert row["applicability"] == "適用"


# ──────────────────────────────────────────────
# build_soa_matrix
# ──────────────────────────────────────────────

def test_soa_matrix_returns_list():
    rows = build_soa_matrix(["control_8.13", "control_5.15"])
    assert isinstance(rows, list)
    assert len(rows) == 2


def test_soa_matrix_json_serializable():
    rows = build_soa_matrix(["control_8.13", "control_5.15", "clause_9.2"])
    json.dumps(rows)


def test_soa_matrix_with_document():
    doc = "我們每日備份資料庫，保存在 NAS，但沒有還原測試。"
    rows = build_soa_matrix(["control_8.13"], document_text=doc)
    assert len(rows) == 1
    row = rows[0]
    # 有文件且有缺口
    assert row["implementation_status"] in ("部分實作", "已實作待驗證", "待確認")


def test_soa_matrix_handles_unknown_control():
    rows = build_soa_matrix(["control_99.99"])
    assert len(rows) == 1
    assert rows[0]["implementation_status"] == "待確認"


# ──────────────────────────────────────────────
# build_audit_readiness_report
# ──────────────────────────────────────────────

def _make_gap_result(missing_count=3):
    return {
        "covered_signals": [{"keyword": "備份"}],
        "missing_signals": [{"theme": f"缺口{i}"} for i in range(missing_count)],
        "risk_level": "high" if missing_count > 2 else "medium",
        "notes": [],
    }


def test_audit_readiness_has_summary():
    matched = [{"id": "control_8.13", "subsection": "資訊備份", "score": 0.9}]
    gap = _make_gap_result(3)
    report = build_audit_readiness_report("備份現況", matched, gap, [], [])
    assert "summary" in report
    assert "risk_level" in report["summary"]
    assert "matched_control_count" in report["summary"]
    assert "gap_count" in report["summary"]


def test_audit_readiness_has_control_matrix():
    matched = [{"id": "control_8.13", "subsection": "資訊備份", "score": 0.9}]
    gap = _make_gap_result(2)
    report = build_audit_readiness_report("備份現況", matched, gap, [], [])
    assert "control_matrix" in report
    assert isinstance(report["control_matrix"], list)


def test_audit_readiness_json_serializable():
    matched = [{"id": "control_8.13", "subsection": "資訊備份", "score": 0.9}]
    gap = _make_gap_result(2)
    report = build_audit_readiness_report("備份現況", matched, gap, [], [])
    json.dumps(report)


# ──────────────────────────────────────────────
# build_audit_question_pack
# ──────────────────────────────────────────────

def test_question_pack_returns_list():
    packs = build_audit_question_pack(["control_8.13"])
    assert isinstance(packs, list)
    assert len(packs) == 1


def test_question_pack_min_three_questions():
    packs = build_audit_question_pack(["control_8.13"])
    assert len(packs[0]["questions"]) >= 3


def test_question_pack_has_required_fields():
    packs = build_audit_question_pack(["control_5.15"])
    pack = packs[0]
    for key in ["control_id", "control_name", "questions", "answer_points", "common_followups", "evidence"]:
        assert key in pack, f"缺少欄位: {key}"


def test_question_pack_json_serializable():
    packs = build_audit_question_pack(["control_8.13", "control_5.15", "control_8.15"])
    json.dumps(packs)


def test_question_pack_unknown_control_returns_generic():
    packs = build_audit_question_pack(["control_99.99"])
    assert len(packs) == 1
    assert len(packs[0]["questions"]) >= 3


def test_question_pack_multiple_controls():
    packs = build_audit_question_pack(["control_8.13", "control_5.15", "clause_9.2"])
    assert len(packs) == 3


# ──────────────────────────────────────────────
# build_remediation_roadmap
# ──────────────────────────────────────────────

def test_roadmap_has_30_60_90():
    gap = _make_gap_result(3)
    roadmap = build_remediation_roadmap(gap, ["control_8.13"])
    for key in ["days_30", "days_60", "days_90", "owners", "summary"]:
        assert key in roadmap, f"缺少欄位: {key}"


def test_roadmap_json_serializable():
    gap = {
        "covered_signals": [],
        "missing_signals": [
            {"theme": "還原測試"},
            {"theme": "備份保存期限"},
            {"theme": "日誌審查週期"},
        ],
        "risk_level": "high",
        "notes": [],
    }
    roadmap = build_remediation_roadmap(gap, ["control_8.13", "control_8.15"])
    json.dumps(roadmap)


def test_roadmap_high_priority_in_30_days():
    gap = {
        "covered_signals": [],
        "missing_signals": [{"theme": "還原測試"}],
        "risk_level": "high",
        "notes": [],
    }
    roadmap = build_remediation_roadmap(gap, ["control_8.13"])
    # 還原測試 → days_30
    day30_text = " ".join(roadmap["days_30"])
    assert "還原測試" in day30_text


def test_roadmap_empty_gap_still_returns_plan():
    gap = {"covered_signals": [], "missing_signals": [], "risk_level": "low", "notes": []}
    roadmap = build_remediation_roadmap(gap, ["control_8.13"])
    # 無缺口時應有通用計畫
    total = len(roadmap["days_30"]) + len(roadmap["days_60"]) + len(roadmap["days_90"])
    assert total > 0


# ──────────────────────────────────────────────
# export_markdown_report
# ──────────────────────────────────────────────

def test_export_soa_writes_file(tmp_path):
    output = str(tmp_path / "soa.md")
    report = {
        "report_type": "soa",
        "organization_context": "測試組織",
        "soa_rows": [draft_soa_statement("control_8.13")],
        "evidence_section": [],
    }
    result = export_markdown_report(report, output)
    assert result == output
    assert Path(output).exists()
    content = Path(output).read_text(encoding="utf-8")
    assert "SoA" in content
    assert "免責" in content


def test_export_roadmap_writes_file(tmp_path):
    output = str(tmp_path / "roadmap.md")
    roadmap = build_remediation_roadmap(
        {"covered_signals": [], "missing_signals": [{"theme": "還原測試"}], "risk_level": "high", "notes": []},
        ["control_8.13"],
    )
    report = {"report_type": "roadmap", "roadmap": roadmap}
    result = export_markdown_report(report, output)
    assert Path(output).exists()
    content = Path(output).read_text(encoding="utf-8")
    assert "改善路線圖" in content or "改善計畫" in content


def test_export_creates_parent_dir(tmp_path):
    output = str(tmp_path / "outputs" / "nested" / "report.md")
    report = {"report_type": "generic", "data": "test"}
    export_markdown_report(report, output)
    assert Path(output).exists()


def test_export_no_auto_write_without_path():
    # 不提供 output_path 時不能自動寫檔 — 此測試驗證函式需要明確路徑
    # 傳入空字串時應拋例外而不是靜默寫到工作目錄
    import pytest
    with pytest.raises(Exception):
        export_markdown_report({"report_type": "generic"}, "")
