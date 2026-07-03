"""tests/test_level2_agent.py
agent.py 的 deterministic 邏輯測試 — 不呼叫 LLM，不需要 Ollama。
"""
import ast
import os
import sys
import subprocess
from pathlib import Path

from agent import classify_task

PROJECT_ROOT = Path(__file__).parent.parent


# ──────────────────────────────────────────────
# classify_task
# ──────────────────────────────────────────────

def test_classify_gap():
    # 注意：不可含 evidence_signals（稽核證據、查核、準備什麼 等）否則會被優先分類為 evidence
    text = (
        "我們公司的備份程序如下：每日凌晨自動備份資料庫，備份檔保存在 NAS，"
        "IT 每週確認備份作業是否成功完成，並將結果記錄於備份日誌中。"
        "目前尚未針對備份執行定期還原測試，也缺乏加密與異地保存機制。"
        "請幫我看這樣符合 ISO 27001 嗎？缺什麼？"
    )
    assert len(text) > 120, f"測試前提：文字長度需 > 120，實際 {len(text)}"
    assert classify_task(text) == "gap"


def test_classify_short_gap_with_explicit_signals():
    text = (
        "我們公司的備份程序如下：每日凌晨自動備份資料庫，備份檔保存在 NAS，"
        "IT 每週檢查備份成功與否。請幫我看這樣符合 ISO 27001 嗎？缺什麼？"
    )
    assert len(text) < 120
    assert classify_task(text) == "gap"


def test_classify_consultant_challenge_question_as_gap():
    text = (
        "我們目前讓 IT 主管每月人工檢查帳號權限，但沒有正式權限審查紀錄，"
        "也沒有離職帳號停用 SLA。稽核時可能被挑戰哪些點？"
    )
    assert classify_task(text) == "gap"


def test_classify_evidence():
    assert classify_task("備份的稽核證據要準備什麼？") == "evidence"


def test_classify_qa():
    assert classify_task("ISO 27001 的備份條文是什麼？") == "qa"


def test_classify_evidence_takes_priority_over_gap():
    """evidence 信號應優先於 gap 信號（長文 + 稽核證據關鍵字）。"""
    text = (
        "我們公司的備份程序如下：每日凌晨自動備份資料庫，備份檔保存在 NAS，"
        "IT 每週檢查備份成功與否。請問稽核證據要準備什麼？"
    )
    assert classify_task(text) == "evidence"


def test_classify_short_text_defaults_to_qa():
    """短文且無明確信號，應預設為 qa。"""
    assert classify_task("備份是什麼？") == "qa"


# ──────────────────────────────────────────────
# --strict-offline 與 --gemini 互斥
# ──────────────────────────────────────────────

def test_strict_offline_rejects_gemini():
    result = subprocess.run(
        [sys.executable, "agent.py", "--strict-offline", "--gemini", "測試"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "SKIP_DOTENV": "1"},
    )
    assert result.returncode != 0, "strict-offline + gemini 應以非零 exit code 退出"
    combined_output = (result.stderr + result.stdout).lower()
    assert any(kw in combined_output for kw in ["strict", "gemini", "不允許"]), (
        f"stderr/stdout 應包含 strict/gemini/不允許 相關錯誤說明，實際:\n{result.stderr}"
    )


# ──────────────────────────────────────────────
# agent.py 語法正確性
# ──────────────────────────────────────────────

def test_agent_syntax():
    agent_path = PROJECT_ROOT / "agent.py"
    source = agent_path.read_text(encoding="utf-8")
    # ast.parse 拋出 SyntaxError 代表語法錯誤
    tree = ast.parse(source)
    assert tree is not None


# ──────────────────────────────────────────────
# agent.py 頂層 import（tools 可用時）
# ──────────────────────────────────────────────

def test_agent_imports_tools():
    """確認 agent.py 中 _TOOLS_AVAILABLE 為 True（tools/ 已存在）。"""
    import agent as ag
    assert ag._TOOLS_AVAILABLE is True, (
        f"_TOOLS_AVAILABLE 應為 True，錯誤訊息: {ag._TOOLS_ERROR}"
    )


# ──────────────────────────────────────────────
# build_gap_prompt / build_evidence_prompt 煙霧測試
# ──────────────────────────────────────────────

def test_build_gap_prompt_returns_string():
    from agent import build_gap_prompt
    from iso27001_advisor.tools.iso_tools import search_iso
    from iso27001_advisor.tools.gap_analysis_tools import analyze_document_coverage
    from iso27001_advisor.tools.evidence_tools import generate_audit_evidence_checklist
    from iso27001_advisor.tools.draft_tools import draft_gap_remediation

    doc = "我們公司每日凌晨自動備份資料庫，備份檔保存在 NAS。"
    items = search_iso("備份", top_k=2)
    gap_result = analyze_document_coverage(doc, items)
    clause_ids = [r["id"] for r in items]
    evidence_list = generate_audit_evidence_checklist(clause_ids)
    remediation_bullets = draft_gap_remediation(gap_result, clause_ids)

    prompt = build_gap_prompt(doc, items, gap_result, evidence_list, remediation_bullets, [])
    assert isinstance(prompt, str)
    assert len(prompt) > 50  # 非空白
    assert "條文內容" in prompt
    assert "直接違反" in prompt
    assert "不得使用" in prompt
    assert any(item["content"][:20] in prompt for item in items if item.get("content"))
    assert "[A.8.13" in prompt
    assert "[control_8.13" not in prompt


def test_build_evidence_prompt_returns_string():
    from agent import build_evidence_prompt
    from iso27001_advisor.tools.iso_tools import search_iso
    from iso27001_advisor.tools.evidence_tools import generate_audit_evidence_checklist

    query = "備份的稽核證據要準備什麼？"
    items = search_iso("備份", top_k=2)
    clause_ids = [r["id"] for r in items]
    evidence_list = generate_audit_evidence_checklist(clause_ids)

    prompt = build_evidence_prompt(query, items, evidence_list)
    assert isinstance(prompt, str)
    assert len(prompt) > 50  # 非空白
    assert "條文內容" in prompt
    assert any(item["content"][:20] in prompt for item in items if item.get("content"))


def test_web_app_uses_same_short_gap_classifier():
    import app
    text = (
        "我們公司的備份程序如下：每日凌晨自動備份資料庫，備份檔保存在 NAS，"
        "IT 每週檢查備份成功與否。請幫我看這樣符合 ISO 27001 嗎？缺什麼？"
    )
    assert app._classify_task(text) == "gap"
