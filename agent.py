#!/usr/bin/env python3
"""
agent.py - ISO 27001 Level 2 文件缺口分析顧問 Agent CLI 入口

用法：
    python3 agent.py "問題或文件內容"
    python3 agent.py --mode gap "文件內容"
    python3 agent.py --mode evidence "備份稽核證據要準備什麼"
    python3 agent.py --mode qa "ISO 27001 怎麼要求備份"
    python3 agent.py --mode auto "..."          # 自動判斷（預設）
    python3 agent.py --model gemma3:12b-16k
    python3 agent.py --gemini
    python3 agent.py --strict-offline
    python3 agent.py --top-k 4
    python3 agent.py --deep                     # 啟用 Map-Reduce（僅 qa mode）
"""

import argparse
import os
import sys
import urllib.request
from typing import Optional, List

# ──────────────────────────────────────────────
# 從 package 匯入共用函式
# ──────────────────────────────────────────────
from iso27001_advisor.llm import (
    call_ollama,
    call_gemini,
    build_prompt,
    get_system_prompt,
    load_dotenv,
    map_reduce_query,
)

# ──────────────────────────────────────────────
# Level 3 tools（可選）
# ──────────────────────────────────────────────
_L3_TOOLS_AVAILABLE = False
_L3_TOOLS_ERROR: Optional[str] = None

try:
    from iso27001_advisor.tools.soa_tools import build_soa_matrix
    from iso27001_advisor.tools.audit_report_tools import build_audit_readiness_report, build_audit_question_pack
    from iso27001_advisor.tools.action_plan_tools import build_remediation_roadmap
    from iso27001_advisor.tools.export_tools import export_markdown_report
    _L3_TOOLS_AVAILABLE = True
except ImportError as _e3:
    _L3_TOOLS_ERROR = f"Level 3 tools 載入失敗：{_e3}"

# ──────────────────────────────────────────────
# 從 tools/ 匯入 Level 2 工具
# ──────────────────────────────────────────────
_TOOLS_AVAILABLE = False
_TOOLS_ERROR: Optional[str] = None

try:
    from iso27001_advisor.tools.iso_tools import search_iso, get_clause
    from iso27001_advisor.tools.gap_analysis_tools import analyze_document_coverage
    from iso27001_advisor.tools.evidence_tools import generate_audit_evidence_checklist
    from iso27001_advisor.tools.draft_tools import draft_gap_remediation
    _TOOLS_AVAILABLE = True
except ImportError as _e:
    _TOOLS_ERROR = (
        f"tools/ 目錄尚未完整建立，以下匯入失敗：{_e}\n"
        "請先執行對應的 subagent 建立 tools/ 下的模組，\n"
        "或確認 tools/gap_analysis_tools.py、tools/evidence_tools.py、"
        "tools/draft_tools.py 已存在。\n"
        "目前僅 qa mode 可用（不依賴 Level 2 工具）。"
    )

# ──────────────────────────────────────────────
# Level 2 System Prompt
# ──────────────────────────────────────────────
LEVEL2_SYSTEM_PROMPT = """你是一位 ISO 27001 資訊安全管理系統顧問。你只能依據提供的 ISO 條文、工具分析結果與使用者文件內容提出建議。

規則：
1. 一律使用繁體中文與台灣用語。
2. 不得編造 ISO 條文號碼或控制項名稱。
3. 所有引用必須使用格式：[A.x.x 控制項名稱] 或 [x.x 條文名稱]。
4. 若工具結果顯示缺口，只能說「可能缺口」、「可能不符合稽核期待」或「建議補強」，不得宣稱正式不符合。
5. 必須區分「使用者文件已明確描述」與「文件未描述」。
6. 必須提供稽核證據建議。
7. 禁止使用「直接違反」、「已違反」、「正式不符合」、「確定不符合」等正式稽核結論語氣。
8. 必須在結尾提醒：此建議不等同正式驗證，應由合格主導稽核員或法律顧問確認。"""

LEVEL3_SYSTEM_PROMPT = """你是一位 ISO 27001 資訊安全管理系統顧問。你會根據工具產生的結構化資料，協助使用者整理 SoA 草稿、稽核準備報告、稽核問答包與改善計畫。

規則：
1. 一律使用繁體中文與台灣用語。
2. 不得編造 ISO 條文、控制項名稱或稽核結論。
3. 所有控制項引用必須來自工具結果，格式為 [A.x.x 名稱] 或 [x.x 名稱]。
4. 不得宣稱正式符合或不符合，只能說「可能缺口」、「待確認」、「建議補強」。
5. 禁止使用「直接違反」、「已違反」、「正式不符合」、「確定不符合」等正式稽核結論語氣。
6. 必須區分「已提供的現況描述」、「工具判斷的可能缺口」與「建議補強」。
7. 若產出 SoA，只能稱為「草稿」，不得稱為正式 SoA。
8. 結尾必須提醒：正式文件應由組織管理階層、合格主導稽核員或法律顧問確認。"""


# ──────────────────────────────────────────────
# 任務分類 heuristic
# ──────────────────────────────────────────────
def classify_task(text: str) -> str:
    """自動判斷任務類型，回傳 'soa'、'audit-report'、'audit-pack'、'roadmap'、'gap'、'evidence' 或 'qa'。"""
    text_lower = text.lower()

    # 純控制項 ID 輸入（如 "A.8.13 A.5.15" 或 "control_8.13,control_5.15"）→ audit-pack
    import re as _re
    _control_pattern = _re.compile(r'\b(?:A\.[\d.]+|control_[\d.]+|clause_[\d.]+)\b', _re.IGNORECASE)
    _control_hits = _control_pattern.findall(text)
    _non_control = _control_pattern.sub("", text).strip().rstrip(",; ")
    if len(_control_hits) >= 1 and len(_non_control) <= 10:
        return "audit-pack"

    # Level 3 訊號（優先判斷）
    soa_signals = ["soa", "適用性聲明", "soa 草稿", "適用性矩陣", "幫我產生 soa"]
    audit_report_signals = ["稽核準備報告", "稽核準備", "audit readiness", "準備報告", "缺口矩陣", "改善計畫報告"]
    audit_pack_signals = ["稽核問答", "問答包", "稽核員會問", "可能會問", "audit pack", "準備問題"]
    roadmap_signals = ["改善計畫", "路線圖", "roadmap", "30天", "60天", "90天", "30 天", "60 天", "90 天", "改善路線"]

    if any(s in text_lower for s in soa_signals):
        return "soa"
    if any(s in text_lower for s in audit_report_signals):
        return "audit-report"
    if any(s in text_lower for s in audit_pack_signals):
        return "audit-pack"
    if any(s in text_lower for s in roadmap_signals):
        return "roadmap"

    # Level 2 訊號
    evidence_signals = ["稽核證據", "證據", "查核", "準備什麼", "要準備"]
    strong_gap_signals = ["程序如下", "政策如下", "現況如下", "控制措施如下"]
    context_gap_signals = ["我們公司", "目前", "現況", "如下", "請幫我看"]
    negative_control_signals = ["沒有", "無", "缺乏", "尚未", "未定義", "未建立"]
    question_gap_signals = [
        "缺什麼",
        "符合嗎",
        "符合 iso",
        "缺口",
        "不足",
        "稽核時可能",
        "被挑戰",
        "挑戰哪些",
        "可能被挑戰",
        "會被挑戰",
    ]
    if any(s in text_lower for s in evidence_signals):
        return "evidence"
    if any(s in text_lower for s in strong_gap_signals):
        return "gap"
    if (
        any(s in text_lower for s in context_gap_signals)
        and any(s in text_lower for s in question_gap_signals)
    ):
        return "gap"
    if (
        any(s in text_lower for s in context_gap_signals)
        and any(s in text_lower for s in negative_control_signals)
    ):
        return "gap"
    if len(text) > 120 and any(s in text_lower for s in context_gap_signals + question_gap_signals):
        return "gap"
    return "qa"


# ──────────────────────────────────────────────
# Prompt 建構工具
# ──────────────────────────────────────────────
def _standard_citation(item_id: str, name: str) -> str:
    """將內部 ID 轉成 LLM 可直接引用的 ISO 顯示格式。"""
    if item_id.startswith("control_"):
        number = item_id.replace("control_", "")
        clean_name = name.removeprefix(f"{number} ").strip()
        return f"[A.{number} {clean_name}]"
    if item_id.startswith("clause_"):
        number = item_id.replace("clause_", "")
        clean_name = name.removeprefix(f"{number} ").strip()
        return f"[{number} {clean_name}]"
    return f"[{item_id} {name}]"


def _format_matched_context(matched_items: list, max_chars: int = 600) -> str:
    """將 search_iso 回傳的結果格式化成條文區塊字串。"""
    parts = []
    for idx, r in enumerate(matched_items, 1):
        content = r.get("content", "")
        if len(content) > max_chars:
            content = content[:max_chars] + "…（以下省略）"
        item_type_zh = "條文" if r.get("type") == "clause" else "附錄 A 控制措施"
        item_id = r.get("id", "")
        citation = _standard_citation(item_id, r.get("subsection", r.get("title", "")))
        parts.append(
            f"[{idx}] {item_type_zh} ID: {r.get('id', '')}\n"
            f"標準引用: {citation}\n"
            f"分類/章節: {r.get('section', '')}\n"
            f"名稱: {r.get('subsection', r.get('title', ''))}\n"
            f"條文內容:\n{content}\n"
            f"----------------------------------------"
        )
    return "\n".join(parts)


def _build_history_block(history: list, max_turns: int = 3) -> str:
    """將最近對話歷史轉為 prompt 可插入的情境區塊。"""
    if not history:
        return ""

    recent = history[-(max_turns * 2):]
    lines = ["【對話歷史（最近對話，供情境參考）】"]
    for msg in recent:
        role_label = "使用者" if msg.get("role") == "user" else "顧問"
        content = msg.get("content", "")
        if msg.get("role") == "assistant" and len(content) > 600:
            content = content[:600] + "…（略）"
        lines.append(f"{role_label}：{content}")
    lines.append("")
    return "\n".join(lines)


def build_gap_prompt(
    document_text: str,
    matched_items: list,
    gap_result: dict,
    evidence_list: list,
    remediation_bullets: list,
    recs: list,
    max_chars: int = 600,
    detail_level: str = "standard",
    history: list = None,
) -> str:
    """組裝 Gap Analysis 的最終 LLM Prompt。"""
    history_block = _build_history_block(history or [])
    matched_context = _format_matched_context(matched_items, max_chars)

    covered_signals = gap_result.get("covered_signals", [])
    missing_signals = gap_result.get("missing_signals", [])
    risk_level = gap_result.get("risk_level", "未知")
    notes = gap_result.get("notes", [])

    covered_text = "\n".join(f"- {s}" for s in covered_signals) if covered_signals else "（無明確覆蓋訊號）"
    missing_text = "\n".join(f"- {s}" for s in missing_signals) if missing_signals else "（未偵測到明顯缺口）"
    notes_text = "\n".join(f"- {n}" for n in notes) if notes else ""
    notes_block = ("【備註】\n" + notes_text + "\n") if notes_text else ""

    evidence_lines = []
    for item in evidence_list:
        clause_id = item.get("clause_id", "")
        clause_name = item.get("clause_name", "")
        citation = _standard_citation(clause_id, clause_name)
        for ev in item.get("evidence", []):
            evidence_lines.append(f"- {citation} {ev}")
    evidence_text = "\n".join(evidence_lines) if evidence_lines else "（無稽核證據建議）"

    remediation_text = "\n".join(f"- {b}" for b in remediation_bullets) if remediation_bullets else "（無補強建議）"

    recs_text = "\n".join(f"- {r.get('question', '')}" for r in recs) if recs else "（無可追問問題）"

    if detail_level == "deep":
        output_depth_instruction = """【輸出深度要求】
本次使用者選擇「深度分析」。請輸出完整顧問版報告：
- 必須完整保留所有指定章節，不得只輸出摘要與適用條文。
- 「主要文件缺口」至少列 3 點，並區分文件缺口、證據缺口、執行落差。
- 「稽核證據建議」至少列 5 項可被稽核員查驗的文件、紀錄、截圖或訪談證據。
- 「建議補強文字」需提供可直接放入程序書或政策的草稿，至少 2 段。
- 「建議改善行動」需給出 3 個具體優先順序。
- 回答長度應明顯比一般模式完整。"""
    else:
        output_depth_instruction = """【輸出深度要求】
本次使用者選擇「一般」。請輸出精簡顧問版報告：
- 必須完整保留所有指定章節。
- 「判斷摘要」限 2 句。
- 「主要文件缺口」最多列 3 點。
- 「稽核證據建議」最多列 5 項。
- 「建議補強文字」限 1 段。
- 「建議改善行動」最多列 3 點，避免展開長篇政策草稿。"""

    prompt = f"""{history_block}【使用者文件或現況描述】
{document_text}

【檢索到的 ISO 27001 相關條文】
{matched_context}

【工具分析：已覆蓋訊號】
{covered_text}

【工具分析：可能缺口（風險等級：{risk_level}）】
{missing_text}
{notes_block}
【稽核證據建議】
{evidence_text}

【建議補強方向】
{remediation_text}

【可追問的相關問題】
{recs_text}

{output_depth_instruction}

【合規語氣限制】
- 不得使用「直接違反」、「已違反」、「正式不符合」、「確定不符合」等正式稽核結論。
- 可使用「可能缺口」、「可能不符合稽核期待」、「稽核時可能被挑戰」、「建議補強」。
- 引用條文時只能使用上方「標準引用」格式，不要自行改寫成其他條文號。

請輸出一份 ISO 27001 文件缺口分析，格式如下：

## 判斷摘要
用 2-3 句話說明整體判斷。不得宣稱正式符合或不符合，只能說明可能缺口或稽核時可能被挑戰之處。

## 適用條文
列出引用條文與控制項。

## 已覆蓋事項
只列使用者文件中明確提到的內容。

## 主要文件缺口
列出文件未描述或證據不足之處。

## 稽核證據建議
列出稽核時應準備的文件、紀錄或截圖。

## 建議補強文字
提供可放入政策或程序書的補強文字草稿。

## 建議改善行動
列出 2-3 個後續建議。

## 免責與合規警示
提醒此建議不等同正式稽核結論，應由合格主導稽核員確認。"""
    return prompt


def build_evidence_prompt(
    query: str,
    matched_items: list,
    evidence_list: list,
    max_chars: int = 600,
    history: list = None,
) -> str:
    """組裝 Evidence 模式的最終 LLM Prompt。"""
    history_block = _build_history_block(history or [])
    matched_context = _format_matched_context(matched_items, max_chars)

    evidence_lines = []
    for item in evidence_list:
        clause_id = item.get("clause_id", "")
        clause_name = item.get("clause_name", "")
        citation = _standard_citation(clause_id, clause_name)
        for ev in item.get("evidence", []):
            evidence_lines.append(f"- {citation} {ev}")
    evidence_text = "\n".join(evidence_lines) if evidence_lines else "（無稽核證據建議）"

    prompt = f"""{history_block}【使用者問題】
{query}

【檢索到的 ISO 27001 相關條文】
{matched_context}

【工具產生的稽核證據清單】
{evidence_text}

請以稽核顧問角色，輸出稽核證據建議清單，格式如下：

## 查詢摘要
說明問題對應的 ISO 27001 條文範圍。

## 適用條文與控制項
列出相關條文 ID 與名稱。

## 稽核證據清單
依條文分組，列出應準備的文件、紀錄、截圖或訪談確認事項。

## 實務建議
提供 2-3 點稽核準備的實務提醒。

## 免責與合規警示
提醒此建議不等同正式稽核結論，應由合格主導稽核員確認。"""
    return prompt


# ──────────────────────────────────────────────
# Ollama 可用性檢查
# ──────────────────────────────────────────────
def _check_ollama_available(host: str) -> bool:
    try:
        urllib.request.urlopen(f"{host}/api/tags", timeout=2)
        return True
    except Exception:
        return False


# ──────────────────────────────────────────────
# 各模式執行邏輯
# ──────────────────────────────────────────────
def run_qa_mode(
    query: str,
    top_k: int,
    model: str,
    host: str,
    use_gemini: bool,
    api_key: Optional[str],
    gemini_model: str,
    deep: bool,
) -> bool:
    """QA 模式：RAG 檢索 + LLM 回答。"""
    print("🔍 檢索條文...", file=sys.stderr)

    if _TOOLS_AVAILABLE:
        matched_items = search_iso(query, top_k=top_k)
        # 轉換為 build_prompt 所需格式（{item: {...}, score: ...}）
        matched_for_prompt = [
            {
                "item": {
                    "id": r.get("id", ""),
                    "type": r.get("type", "clause"),
                    "section": r.get("section", ""),
                    "subsection": r.get("subsection", r.get("title", "")),
                    "content": r.get("content", ""),
                },
                "score": r.get("score", 0.0),
            }
            for r in matched_items
        ]
    else:
        # fallback：使用 ISO27001Searcher
        from iso27001_advisor.core.search_tool import ISO27001Searcher
        searcher = ISO27001Searcher()
        matched_for_prompt = searcher.search(query, limit=top_k)
        matched_items = matched_for_prompt  # 同格式

    if not matched_for_prompt:
        print("⚠️ 找不到與該關鍵字相關的條文。", file=sys.stderr)
        return False

    print(f"📌 檢索到 {len(matched_for_prompt)} 筆相關條文，正在產生顧問解答...", file=sys.stderr)
    print("\n==================== 📖 ISO 27001 顧問解答 ====================")

    try:
        if use_gemini:
            prompt = build_prompt(query, matched_for_prompt)
            ans = call_gemini(prompt, LEVEL2_SYSTEM_PROMPT, api_key, model=gemini_model)
            print(ans)
        elif deep:
            map_reduce_query(
                query,
                matched_for_prompt,
                model=model,
                host=host,
                on_progress=lambda msg: print(f"  ⚙️  {msg}", flush=True),
                on_chunk=lambda c: print(c, end="", flush=True),
            )
        else:
            prompt = build_prompt(query, matched_for_prompt)
            call_ollama(
                prompt,
                LEVEL2_SYSTEM_PROMPT,
                model=model,
                host=host,
                on_chunk=lambda c: print(c, end="", flush=True),
            )
        print("\n==============================================================\n")
    except Exception as e:
        print(f"\n❌ 推理失敗: {e}", file=sys.stderr)
        return False

    _print_cited_clauses(matched_for_prompt)
    return True


def run_gap_mode(
    document_text: str,
    top_k: int,
    model: str,
    host: str,
    use_gemini: bool,
    api_key: Optional[str],
    gemini_model: str,
) -> bool:
    """Gap Analysis 模式：工具分析 + 缺口報告。"""
    if not _TOOLS_AVAILABLE:
        print(f"❌ Gap 模式需要 tools/ 目錄中的完整工具集。\n{_TOOLS_ERROR}", file=sys.stderr)
        return False

    print("🔍 檢索條文...", file=sys.stderr)
    matched_items = search_iso(document_text, top_k=top_k)

    if not matched_items:
        print("⚠️ 找不到與該文件相關的條文。", file=sys.stderr)
        return False

    print(f"📌 檢索到 {len(matched_items)} 筆相關條文", file=sys.stderr)
    print("🧩 分析文件覆蓋率...", file=sys.stderr)
    gap_result = analyze_document_coverage(document_text, matched_items)

    hit_clause_ids = [r["id"] for r in matched_items]

    print("📋 產生稽核證據清單...", file=sys.stderr)
    evidence_list = generate_audit_evidence_checklist(hit_clause_ids)

    print("🛠️  產生補強建議...", file=sys.stderr)
    remediation_bullets = draft_gap_remediation(gap_result, hit_clause_ids)

    # 可選：取得推薦下一步問題
    recs: list = []
    try:
        from iso27001_advisor.core.recommendation import RecommendationEngine
        rec_engine = RecommendationEngine()
        recs = rec_engine.recommend(hit_clause_ids)
    except Exception:
        pass

    print("💬 正在產生缺口分析報告...", file=sys.stderr)
    prompt = build_gap_prompt(
        document_text,
        matched_items,
        gap_result,
        evidence_list,
        remediation_bullets,
        recs,
    )

    print("\n==================== 📖 ISO 27001 文件缺口分析報告 ====================")
    try:
        if use_gemini:
            ans = call_gemini(prompt, LEVEL2_SYSTEM_PROMPT, api_key, model=gemini_model)
            print(ans)
        else:
            call_ollama(
                prompt,
                LEVEL2_SYSTEM_PROMPT,
                model=model,
                host=host,
                on_chunk=lambda c: print(c, end="", flush=True),
            )
        print("\n=======================================================================\n")
    except Exception as e:
        print(f"\n❌ 推理失敗: {e}", file=sys.stderr)
        return False

    _print_cited_clauses_from_iso_tools(matched_items)
    return True


def run_evidence_mode(
    query: str,
    top_k: int,
    model: str,
    host: str,
    use_gemini: bool,
    api_key: Optional[str],
    gemini_model: str,
) -> bool:
    """Evidence 模式：工具產生稽核證據清單 + LLM 整理。"""
    if not _TOOLS_AVAILABLE:
        print(f"❌ Evidence 模式需要 tools/ 目錄中的完整工具集。\n{_TOOLS_ERROR}", file=sys.stderr)
        return False

    print("🔍 檢索條文...", file=sys.stderr)
    matched_items = search_iso(query, top_k=top_k)

    if not matched_items:
        print("⚠️ 找不到與該問題相關的條文。", file=sys.stderr)
        return False

    print(f"📌 檢索到 {len(matched_items)} 筆相關條文", file=sys.stderr)
    hit_clause_ids = [r["id"] for r in matched_items]

    print("📋 產生稽核證據清單...", file=sys.stderr)
    evidence_list = generate_audit_evidence_checklist(hit_clause_ids)

    print("💬 正在產生稽核證據建議...", file=sys.stderr)
    prompt = build_evidence_prompt(query, matched_items, evidence_list)

    print("\n==================== 📋 ISO 27001 稽核證據建議 ====================")
    try:
        if use_gemini:
            ans = call_gemini(prompt, LEVEL2_SYSTEM_PROMPT, api_key, model=gemini_model)
            print(ans)
        else:
            call_ollama(
                prompt,
                LEVEL2_SYSTEM_PROMPT,
                model=model,
                host=host,
                on_chunk=lambda c: print(c, end="", flush=True),
            )
        print("\n===================================================================\n")
    except Exception as e:
        print(f"\n❌ 推理失敗: {e}", file=sys.stderr)
        return False

    _print_cited_clauses_from_iso_tools(matched_items)
    return True


# ──────────────────────────────────────────────
# Level 3 Prompt Builders
# ──────────────────────────────────────────────

def build_soa_prompt(
    document_text: str,
    soa_rows: list,
    evidence_list: list,
    organization_context: str = "",
    detail_level: str = "standard",
    history: list = None,
) -> str:
    import json as _json
    history_block = _build_history_block(history or [])
    soa_text = _json.dumps(soa_rows, ensure_ascii=False, indent=2)
    ev_lines = []
    for item in evidence_list:
        clause_id = item.get("clause_id", "")
        clause_name = item.get("clause_name", "")
        citation = _standard_citation(clause_id, clause_name)
        for ev in item.get("evidence", []):
            ev_lines.append(f"- {citation} {ev}")
    ev_text = "\n".join(ev_lines) or "（無）"
    depth = (
        "請輸出完整 SoA 草稿報告，表格需包含所有控制項，缺口與建議需充分展開。"
        if detail_level == "deep"
        else "請輸出精簡 SoA 草稿，表格完整但建議文字簡潔。"
    )
    return f"""{history_block}【組織背景】
{organization_context or '（未提供）'}

【使用者現況描述】
{document_text}

【SoA 矩陣草稿（工具產生）】
{soa_text}

【稽核證據建議】
{ev_text}

{depth}

請整理為 ISO 27001 SoA 草稿，輸出以下章節：

## SoA 草稿摘要

## 控制項適用性矩陣

| 控制項 | 名稱 | 適用性 | 理由 | 實作狀態 | 缺口 | 證據 |

## 主要缺口

## 建議補強

## 待管理階層確認事項

## 免責與合規警示"""


def build_audit_report_prompt(
    document_text: str,
    readiness_report: dict,
    roadmap: dict,
    detail_level: str = "standard",
    history: list = None,
) -> str:
    import json as _json
    history_block = _build_history_block(history or [])
    report_text = _json.dumps(readiness_report, ensure_ascii=False, indent=2)
    roadmap_text = _json.dumps(roadmap, ensure_ascii=False, indent=2)
    depth = (
        "請輸出完整稽核準備報告，各章節充分展開，30/60/90 天計畫需列出具體行動。"
        if detail_level == "deep"
        else "請輸出精簡稽核準備報告，重點突出高優先級項目。"
    )
    return f"""{history_block}【使用者現況描述】
{document_text}

【稽核準備結構化資料（工具產生）】
{report_text}

【改善路線圖（工具產生）】
{roadmap_text}

{depth}

請整理為 ISO 27001 稽核準備報告，輸出以下章節：

## 稽核準備摘要

## 控制項與缺口矩陣

## 優先改善項目

## 30 / 60 / 90 天改善計畫

## 建議稽核證據

## 待確認事項

## 免責與合規警示"""


def build_audit_pack_prompt(
    query: str,
    question_packs: list,
    detail_level: str = "standard",
    history: list = None,
) -> str:
    import json as _json
    history_block = _build_history_block(history or [])
    packs_text = _json.dumps(question_packs, ensure_ascii=False, indent=2)
    depth = (
        "請完整展開每個控制項的問答內容，包含常見追問與風險提醒。"
        if detail_level == "deep"
        else "請精簡輸出各控制項的問答重點。"
    )
    return f"""{history_block}【使用者指定控制項或問題】
{query}

【稽核問答包（工具產生）】
{packs_text}

{depth}

請整理為稽核問答包，每個控制項輸出以下章節：

## [控制項 ID] 控制項名稱

### 稽核員可能問題
### 建議回答要點
### 可展示證據
### 常見追問
### 風險提醒

## 免責與合規警示"""


def build_roadmap_prompt(
    document_text: str,
    roadmap: dict,
    detail_level: str = "standard",
    context_query: str = "",
    history: list = None,
) -> str:
    import json as _json
    history_block = _build_history_block(history or [])
    roadmap_text = _json.dumps(roadmap, ensure_ascii=False, indent=2)
    current_state_text = context_query if context_query else document_text
    depth = (
        "請完整展開每個改善項目的執行細節與成功標準。"
        if detail_level == "deep"
        else "請輸出精簡的改善路線圖，重點說明優先順序。"
    )
    return f"""{history_block}【使用者現況描述或缺口描述】
{current_state_text}

【改善路線圖（工具產生）】
{roadmap_text}

{depth}

請整理為 ISO 27001 改善計畫，輸出以下章節：

## 改善計畫摘要

## 30 天目標（高優先）

## 60 天目標（中優先）

## 90 天目標（持續改善）

## 負責團隊建議

## 免責與合規警示"""


# ──────────────────────────────────────────────
# Level 3 Run Functions
# ──────────────────────────────────────────────

def _parse_control_ids(controls_str: str) -> list:
    """解析 --controls 參數，回傳 normalized ID 清單。"""
    return [c.strip().lower() for c in controls_str.split(",") if c.strip()]


def _extract_control_ids_from_text(text: str) -> list:
    """從文字中抽取控制項 ID（如 A.8.13 → control_8.13）。"""
    import re
    ids = []
    for m in re.finditer(r'\bA\.(\d+\.\d+)\b', text, re.IGNORECASE):
        ids.append(f"control_{m.group(1)}")
    for m in re.finditer(r'\bcontrol_[\d.]+\b', text, re.IGNORECASE):
        ids.append(m.group(0).lower())
    return list(dict.fromkeys(ids))  # 去重保序


def run_soa_mode(
    document_text: str,
    top_k: int,
    model: str,
    host: str,
    use_gemini: bool,
    api_key: Optional[str],
    gemini_model: str,
    organization_context: str = "",
    controls_str: str = "",
    output_path: str = "",
    detail_level: str = "standard",
) -> bool:
    if not _L3_TOOLS_AVAILABLE:
        print(f"❌ Level 3 tools 不可用。{_L3_TOOLS_ERROR}", file=sys.stderr)
        return False
    if not _TOOLS_AVAILABLE:
        print(f"❌ Level 2 tools 不可用。{_TOOLS_ERROR}", file=sys.stderr)
        return False

    # 決定控制項清單
    if controls_str:
        clause_ids = _parse_control_ids(controls_str)
    else:
        print("🔍 未指定 --controls，自動檢索相關條文...", file=sys.stderr)
        matched = search_iso(document_text, top_k=top_k)
        clause_ids = [r["id"] for r in matched]

    if not clause_ids:
        print("⚠️ 找不到相關控制項。", file=sys.stderr)
        return False

    print(f"📋 目標控制項：{', '.join(clause_ids)}", file=sys.stderr)
    print("🧩 產生 SoA 矩陣...", file=sys.stderr)
    soa_rows = build_soa_matrix(clause_ids, document_text, organization_context)

    print("📋 產生稽核證據清單...", file=sys.stderr)
    evidence_list = generate_audit_evidence_checklist(clause_ids)

    prompt = build_soa_prompt(document_text, soa_rows, evidence_list, organization_context, detail_level)

    print("\n==================== 📄 ISO 27001 SoA 草稿 ====================")
    answer = ""
    try:
        if use_gemini:
            answer = call_gemini(prompt, LEVEL3_SYSTEM_PROMPT, api_key, model=gemini_model)
            print(answer)
        else:
            chunks = []
            def _collect(c):
                chunks.append(c)
                print(c, end="", flush=True)
            call_ollama(prompt, LEVEL3_SYSTEM_PROMPT, model=model, host=host, on_chunk=_collect)
            answer = "".join(chunks)
        print("\n==============================================================\n")
    except Exception as e:
        print(f"\n❌ 推理失敗: {e}", file=sys.stderr)
        return False

    if output_path:
        report = {
            "report_type": "soa",
            "organization_context": organization_context,
            "soa_rows": soa_rows,
            "evidence_section": evidence_list,
        }
        written = export_markdown_report(report, output_path)
        print(f"📁 報告已輸出至：{written}")

    _print_cited_clauses_from_iso_tools([{"id": cid, "subsection": cid, "score": 0.0} for cid in clause_ids])
    return True


def run_audit_report_mode(
    document_text: str,
    top_k: int,
    model: str,
    host: str,
    use_gemini: bool,
    api_key: Optional[str],
    gemini_model: str,
    organization_context: str = "",
    output_path: str = "",
    detail_level: str = "standard",
) -> bool:
    if not _L3_TOOLS_AVAILABLE:
        print(f"❌ Level 3 tools 不可用。{_L3_TOOLS_ERROR}", file=sys.stderr)
        return False
    if not _TOOLS_AVAILABLE:
        print(f"❌ Level 2 tools 不可用。{_TOOLS_ERROR}", file=sys.stderr)
        return False

    print("🔍 檢索條文...", file=sys.stderr)
    matched = search_iso(document_text, top_k=top_k)
    if not matched:
        print("⚠️ 找不到相關條文。", file=sys.stderr)
        return False

    print("🧩 分析文件缺口...", file=sys.stderr)
    gap_result = analyze_document_coverage(document_text, matched)

    print("📋 產生稽核證據清單...", file=sys.stderr)
    clause_ids = [r["id"] for r in matched]
    evidence_list = generate_audit_evidence_checklist(clause_ids)

    print("🛠️  產生補強建議...", file=sys.stderr)
    remediation = draft_gap_remediation(gap_result, clause_ids)

    print("🗺️  產生改善路線圖...", file=sys.stderr)
    roadmap = build_remediation_roadmap(gap_result, clause_ids)

    print("📊 產生稽核準備報告...", file=sys.stderr)
    readiness = build_audit_readiness_report(document_text, matched, gap_result, evidence_list, remediation)

    prompt = build_audit_report_prompt(document_text, readiness, roadmap, detail_level)

    print("\n==================== 📊 ISO 27001 稽核準備報告 ====================")
    try:
        if use_gemini:
            ans = call_gemini(prompt, LEVEL3_SYSTEM_PROMPT, api_key, model=gemini_model)
            print(ans)
        else:
            call_ollama(prompt, LEVEL3_SYSTEM_PROMPT, model=model, host=host,
                        on_chunk=lambda c: print(c, end="", flush=True))
        print("\n====================================================================\n")
    except Exception as e:
        print(f"\n❌ 推理失敗: {e}", file=sys.stderr)
        return False

    if output_path:
        report = {
            "report_type": "audit_readiness",
            **readiness,
            "roadmap": roadmap,
        }
        written = export_markdown_report(report, output_path)
        print(f"📁 報告已輸出至：{written}")

    _print_cited_clauses_from_iso_tools(matched)
    return True


def run_audit_pack_mode(
    query: str,
    top_k: int,
    model: str,
    host: str,
    use_gemini: bool,
    api_key: Optional[str],
    gemini_model: str,
    controls_str: str = "",
    output_path: str = "",
    detail_level: str = "standard",
) -> bool:
    if not _L3_TOOLS_AVAILABLE:
        print(f"❌ Level 3 tools 不可用。{_L3_TOOLS_ERROR}", file=sys.stderr)
        return False

    if controls_str:
        clause_ids = _parse_control_ids(controls_str)
    else:
        extracted = _extract_control_ids_from_text(query)
        if extracted:
            clause_ids = extracted
        elif _TOOLS_AVAILABLE:
            print("🔍 自動檢索相關條文...", file=sys.stderr)
            matched = search_iso(query, top_k=top_k)
            clause_ids = [r["id"] for r in matched]
        else:
            print("⚠️ 請透過 --controls 指定控制項 ID。", file=sys.stderr)
            return False

    if not clause_ids:
        print("⚠️ 找不到相關控制項。", file=sys.stderr)
        return False

    print(f"📋 產生問答包，控制項：{', '.join(clause_ids)}", file=sys.stderr)
    packs = build_audit_question_pack(clause_ids)

    prompt = build_audit_pack_prompt(query, packs, detail_level)

    print("\n==================== 🎯 ISO 27001 稽核問答包 ====================")
    try:
        if use_gemini:
            ans = call_gemini(prompt, LEVEL3_SYSTEM_PROMPT, api_key, model=gemini_model)
            print(ans)
        else:
            call_ollama(prompt, LEVEL3_SYSTEM_PROMPT, model=model, host=host,
                        on_chunk=lambda c: print(c, end="", flush=True))
        print("\n===================================================================\n")
    except Exception as e:
        print(f"\n❌ 推理失敗: {e}", file=sys.stderr)
        return False

    if output_path:
        report = {"report_type": "question_pack", "packs": packs}
        written = export_markdown_report(report, output_path)
        print(f"📁 報告已輸出至：{written}")

    return True


def run_roadmap_mode(
    document_text: str,
    top_k: int,
    model: str,
    host: str,
    use_gemini: bool,
    api_key: Optional[str],
    gemini_model: str,
    output_path: str = "",
    detail_level: str = "standard",
) -> bool:
    if not _L3_TOOLS_AVAILABLE:
        print(f"❌ Level 3 tools 不可用。{_L3_TOOLS_ERROR}", file=sys.stderr)
        return False
    if not _TOOLS_AVAILABLE:
        print(f"❌ Level 2 tools 不可用。{_TOOLS_ERROR}", file=sys.stderr)
        return False

    print("🔍 檢索條文...", file=sys.stderr)
    matched = search_iso(document_text, top_k=top_k)
    clause_ids = [r["id"] for r in matched] if matched else []

    print("🧩 分析缺口...", file=sys.stderr)
    gap_result = analyze_document_coverage(document_text, matched) if matched else {
        "covered_signals": [], "missing_signals": [], "risk_level": "low", "notes": [],
    }

    print("🗺️  產生改善路線圖...", file=sys.stderr)
    roadmap = build_remediation_roadmap(gap_result, clause_ids)

    prompt = build_roadmap_prompt(document_text, roadmap, detail_level)

    print("\n==================== 🗺️  ISO 27001 改善計畫 ====================")
    try:
        if use_gemini:
            ans = call_gemini(prompt, LEVEL3_SYSTEM_PROMPT, api_key, model=gemini_model)
            print(ans)
        else:
            call_ollama(prompt, LEVEL3_SYSTEM_PROMPT, model=model, host=host,
                        on_chunk=lambda c: print(c, end="", flush=True))
        print("\n================================================================\n")
    except Exception as e:
        print(f"\n❌ 推理失敗: {e}", file=sys.stderr)
        return False

    if output_path:
        report = {"report_type": "roadmap", "roadmap": roadmap}
        written = export_markdown_report(report, output_path)
        print(f"📁 報告已輸出至：{written}")

    _print_cited_clauses_from_iso_tools(matched if matched else [])
    return True


# ──────────────────────────────────────────────
# 工具函式
# ──────────────────────────────────────────────
def _print_cited_clauses(matched_for_prompt: list) -> None:
    """列印引用條文（main.py 格式：{item: {...}, score: ...}）。"""
    print("📋 【本次回答所引用之條文依據】")
    for m in matched_for_prompt:
        item = m["item"]
        item_type = "條文" if item.get("type") == "clause" else "控制措施"
        print(f"- [{item['id']}] {item.get('subsection', '')} ({item_type}, 分數: {m.get('score', 0.0):.2f})")
    print()


def _print_cited_clauses_from_iso_tools(matched_items: list) -> None:
    """列印引用條文（search_iso 格式：{id, type, section, subsection, score, ...}）。"""
    print("📋 【本次回答所引用之條文依據】")
    for r in matched_items:
        item_type = "條文" if r.get("type") == "clause" else "控制措施"
        name = r.get("subsection", r.get("title", ""))
        print(f"- [{r.get('id', '')}] {name} ({item_type}, 分數: {r.get('score', 0.0):.2f})")
    print()


# ──────────────────────────────────────────────
# argparse 驗證
# ──────────────────────────────────────────────
def _positive_int(value: str) -> int:
    try:
        ivalue = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"必須為整數，收到: {value}")
    if ivalue < 1:
        raise argparse.ArgumentTypeError(f"--top-k 必須為正整數（≥ 1），收到: {value}")
    return ivalue


# ──────────────────────────────────────────────
# main
# ──────────────────────────────────────────────
def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="ISO 27001 Level 2 文件缺口分析顧問 Agent CLI"
    )
    parser.add_argument(
        "query",
        nargs="?",
        type=str,
        help="問題或文件內容（若未提供則進入互動模式）",
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "qa", "gap", "evidence", "soa", "audit-report", "audit-pack", "roadmap"],
        default="auto",
        help="任務模式：auto / qa / gap / evidence / soa / audit-report / audit-pack / roadmap（預設：auto）",
    )
    parser.add_argument(
        "--controls",
        type=str,
        default="",
        help="指定控制項 ID，逗號分隔，如 control_8.13,control_5.15",
    )
    parser.add_argument(
        "--organization-context",
        type=str,
        default="",
        help="組織背景描述，如「中小型 SaaS 公司，約 120 人」",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Markdown 報告輸出路徑，如 outputs/report.md（不提供則不寫檔）",
    )
    parser.add_argument(
        "--format",
        choices=["markdown"],
        default="markdown",
        help="輸出格式（目前僅支援 markdown）",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gemma3:12b-16k",
        help="Ollama 模型名稱，預設為 gemma3:12b-16k",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="http://localhost:11434",
        help="Ollama API 位址，預設為 http://localhost:11434",
    )
    parser.add_argument(
        "--gemini",
        action="store_true",
        help="使用 Gemini API 作為推理後端（需設定 GEMINI_API_KEY）",
    )
    parser.add_argument(
        "--gemini-model",
        type=str,
        default="gemini-2.5-pro",
        help="Gemini 模型名稱，預設為 gemini-2.5-pro",
    )
    parser.add_argument(
        "--top-k",
        type=_positive_int,
        default=4,
        help="檢索條文的數量，預設為 4",
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="啟用 Map-Reduce 深度分析模式（僅 qa mode）",
    )
    parser.add_argument(
        "--strict-offline",
        action="store_true",
        help="嚴格離線模式：禁止使用 Gemini，Ollama 不可用時直接報錯",
    )
    args = parser.parse_args()

    # ── strict-offline 前置檢查 ──
    if args.strict_offline:
        if args.gemini:
            print(
                "❌ 錯誤：--strict-offline 模式下不允許使用 --gemini。",
                file=sys.stderr,
            )
            sys.exit(1)
        if not _check_ollama_available(args.host):
            print(
                f"❌ 錯誤：--strict-offline 模式下 Ollama 服務不可用 ({args.host})。\n"
                "請確認 Ollama 已啟動，或移除 --strict-offline 以允許備用雲端推理。",
                file=sys.stderr,
            )
            sys.exit(1)
        use_gemini = False
        api_key: Optional[str] = None
    else:
        api_key = os.environ.get("GEMINI_API_KEY")
        use_gemini = args.gemini

        # 未指定 --gemini 但有 API key 且 Ollama 不可用 → 自動切換
        if not use_gemini and api_key and not _check_ollama_available(args.host):
            print(
                "💡 偵測到本地 Ollama 服務未啟動，但已設定 GEMINI_API_KEY，"
                "系統自動切換至 Gemini API 進行推理。"
            )
            use_gemini = True

        if use_gemini and not api_key:
            print(
                "❌ 錯誤：使用 Gemini 推理需要設定 GEMINI_API_KEY 環境變數。",
                file=sys.stderr,
            )
            sys.exit(1)

    detail_level = "deep" if args.deep else "standard"

    def process(text: str) -> bool:
        if not text.strip():
            return True

        # 決定模式
        mode = args.mode
        if mode == "auto":
            mode = classify_task(text)
            print(f"🤖 自動判斷模式：{mode}", file=sys.stderr)

        if mode == "qa":
            return run_qa_mode(
                text, args.top_k, args.model, args.host,
                use_gemini, api_key, args.gemini_model, args.deep,
            )
        elif mode == "gap":
            return run_gap_mode(
                text, args.top_k, args.model, args.host,
                use_gemini, api_key, args.gemini_model,
            )
        elif mode == "evidence":
            return run_evidence_mode(
                text, args.top_k, args.model, args.host,
                use_gemini, api_key, args.gemini_model,
            )
        elif mode == "soa":
            return run_soa_mode(
                text, args.top_k, args.model, args.host,
                use_gemini, api_key, args.gemini_model,
                organization_context=args.organization_context,
                controls_str=args.controls,
                output_path=args.output,
                detail_level=detail_level,
            )
        elif mode == "audit-report":
            return run_audit_report_mode(
                text, args.top_k, args.model, args.host,
                use_gemini, api_key, args.gemini_model,
                organization_context=args.organization_context,
                output_path=args.output,
                detail_level=detail_level,
            )
        elif mode == "audit-pack":
            return run_audit_pack_mode(
                text, args.top_k, args.model, args.host,
                use_gemini, api_key, args.gemini_model,
                controls_str=args.controls,
                output_path=args.output,
                detail_level=detail_level,
            )
        elif mode == "roadmap":
            return run_roadmap_mode(
                text, args.top_k, args.model, args.host,
                use_gemini, api_key, args.gemini_model,
                output_path=args.output,
                detail_level=detail_level,
            )
        else:
            print(f"❌ 未知模式：{mode}", file=sys.stderr)
            return False

    if args.query:
        success = process(args.query)
        if not success:
            sys.exit(1)
    else:
        # REPL 互動模式
        print("====================================================")
        print("🛡️  歡迎使用 ISO 27001 Level 2 文件缺口分析顧問 Agent")
        if use_gemini:
            print(f"  - 推理後端: Gemini API ({args.gemini_model})")
        else:
            print(f"  - 推理後端: Ollama 本地服務 ({args.model})")
        print(f"  - 任務模式: {args.mode}")
        if args.strict_offline:
            print("  - 模式: 嚴格離線（Strict Offline）")
        if not _TOOLS_AVAILABLE:
            print(f"  ⚠️  Level 2 工具不可用（僅支援 qa mode）")
        print("  - 輸入 'exit' 或 'quit' 可退出。")
        print("====================================================")

        while True:
            try:
                user_input = input("\n💬 請輸入您的問題或文件內容：\n> ")
                if user_input.strip().lower() in ("exit", "quit"):
                    print("👋 感謝使用，再見！")
                    break
                process(user_input)
            except KeyboardInterrupt:
                print("\n👋 感謝使用，再見！")
                break
            except Exception as e:
                print(f"發生未預期錯誤: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
