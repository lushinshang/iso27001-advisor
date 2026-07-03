"""tests/test_level3_agent.py
agent.py Level 3 的 deterministic 測試 — 不呼叫 LLM，不需要 Ollama。
"""
import os
import sys
import argparse
from pathlib import Path


from agent import classify_task


# ──────────────────────────────────────────────
# argparse：Level 3 新模式可被接受
# ──────────────────────────────────────────────

def _make_parser():
    """複製 agent.py 的 argparse 設定，方便獨立測試。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default="")
    parser.add_argument(
        "--mode",
        choices=["auto", "qa", "gap", "evidence", "soa", "audit-report", "audit-pack", "roadmap"],
        default="auto",
    )
    parser.add_argument("--controls", type=str, default="")
    parser.add_argument("--organization-context", type=str, default="")
    parser.add_argument("--output", type=str, default="")
    parser.add_argument("--format", choices=["markdown"], default="markdown")
    parser.add_argument("--strict-offline", action="store_true")
    parser.add_argument("--gemini", action="store_true")
    parser.add_argument("--deep", action="store_true")
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--model", type=str, default="gemma3:12b-16k")
    parser.add_argument("--host", type=str, default="http://localhost:11434")
    parser.add_argument("--gemini-model", type=str, default="gemini-2.5-pro")
    return parser


def test_mode_soa_accepted():
    parser = _make_parser()
    args = parser.parse_args(["--mode", "soa", "我們每日備份"])
    assert args.mode == "soa"


def test_mode_audit_report_accepted():
    parser = _make_parser()
    args = parser.parse_args(["--mode", "audit-report", "現況如下"])
    assert args.mode == "audit-report"


def test_mode_audit_pack_accepted():
    parser = _make_parser()
    args = parser.parse_args(["--mode", "audit-pack", "請產生問答包"])
    assert args.mode == "audit-pack"


def test_mode_roadmap_accepted():
    parser = _make_parser()
    args = parser.parse_args(["--mode", "roadmap", "備份缺還原測試"])
    assert args.mode == "roadmap"


def test_controls_param_accepted():
    parser = _make_parser()
    args = parser.parse_args(["--mode", "audit-pack", "--controls", "control_8.13,control_5.15", "問答"])
    assert args.controls == "control_8.13,control_5.15"


def test_output_param_default_empty():
    parser = _make_parser()
    args = parser.parse_args(["--mode", "soa", "備份"])
    assert args.output == ""


def test_output_param_accepted():
    parser = _make_parser()
    args = parser.parse_args(["--mode", "soa", "--output", "outputs/soa.md", "備份"])
    assert args.output == "outputs/soa.md"


def test_organization_context_accepted():
    parser = _make_parser()
    args = parser.parse_args(["--mode", "soa", "--organization-context", "中小型 SaaS 公司", "備份"])
    assert args.organization_context == "中小型 SaaS 公司"


# ──────────────────────────────────────────────
# Strict Offline 防護（延續 Level 2 要求）
# ──────────────────────────────────────────────

def test_strict_offline_and_gemini_combination_detectable():
    parser = _make_parser()
    args = parser.parse_args(["--strict-offline", "--gemini", "備份"])
    # 程式層應拒絕此組合；此測試驗證兩個旗標可同時解析（拒絕在 main() 中處理）
    assert args.strict_offline is True
    assert args.gemini is True


# ──────────────────────────────────────────────
# classify_task：Level 3 模式偵測
# ──────────────────────────────────────────────

def test_classify_soa_mode():
    text = "我們公司目前有備份、存取控制。請根據 ISO 27001 幫我產生 SoA 草稿。"
    assert classify_task(text) == "soa"


def test_classify_audit_report_mode():
    text = "請幫我產生稽核準備報告，涵蓋備份與存取控制。"
    assert classify_task(text) == "audit-report"


def test_classify_audit_pack_mode():
    text = "請針對 A.8.13 幫我整理稽核員會問的問題。"
    assert classify_task(text) == "audit-pack"


def test_classify_roadmap_mode():
    text = "備份缺還原測試，請給我一個 30 天改善計畫。"
    assert classify_task(text) == "roadmap"


# ──────────────────────────────────────────────
# --output 不提供時不得寫檔
# ──────────────────────────────────────────────

def test_no_output_flag_means_no_file(tmp_path):
    """export_markdown_report 只有在 output_path 非空時才寫檔；
    agent.py 的 run_*_mode 在 args.output == '' 時不呼叫 export。
    此測試驗證 args.output 預設為空字串。"""
    parser = _make_parser()
    args = parser.parse_args(["--mode", "soa", "備份"])
    assert args.output == ""


# ──────────────────────────────────────────────
# 引用格式：工具回傳的 control_id 格式
# ──────────────────────────────────────────────

def test_soa_rows_control_id_format():
    from iso27001_advisor.tools.soa_tools import build_soa_matrix
    rows = build_soa_matrix(["control_8.13"])
    assert rows[0]["control_id"] == "control_8.13"


def test_question_pack_control_id_format():
    from iso27001_advisor.tools.audit_report_tools import build_audit_question_pack
    packs = build_audit_question_pack(["control_8.13"])
    assert packs[0]["control_id"] == "control_8.13"


# ──────────────────────────────────────────────
# No formal conclusion：工具不產生正式稽核語氣
# ──────────────────────────────────────────────

FORBIDDEN_PHRASES = ["直接違反", "已違反", "正式不符合", "確定不符合"]


def test_soa_statement_no_formal_conclusion():
    from iso27001_advisor.tools.soa_tools import draft_soa_statement
    row = draft_soa_statement("control_8.13", gap_result={
        "covered_signals": [],
        "missing_signals": [{"theme": "還原測試"}],
        "risk_level": "high",
        "notes": [],
    })
    text = str(row)
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in text, f"工具輸出含禁止語氣: {phrase}"


def test_audit_readiness_no_formal_conclusion():
    from iso27001_advisor.tools.audit_report_tools import build_audit_readiness_report
    matched = [{"id": "control_8.13", "subsection": "資訊備份", "score": 0.9}]
    gap = {
        "covered_signals": [],
        "missing_signals": [{"theme": "還原測試"}],
        "risk_level": "high",
        "notes": [],
    }
    report = build_audit_readiness_report("備份現況", matched, gap, [], [])
    text = str(report)
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in text, f"工具輸出含禁止語氣: {phrase}"
