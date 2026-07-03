"""Markdown 匯出工具。

export_markdown_report() : 將結構化報告 dict 輸出為 Markdown 檔案。

安全注意：
- 預設不寫檔。只有呼叫端明確提供 output_path 時才寫入。
- 建議 output_path 指向 outputs/ 目錄，並將該目錄加入 .gitignore。
"""

import os
import json
from datetime import datetime
from typing import Dict, Any

_DISCLAIMER = (
    "\n---\n\n"
    "> **免責聲明**：本文件為 AI 輔助草稿，不等同正式文件。"
    "正式版本應由組織管理階層與合格主導稽核員或法律顧問確認後方可使用。\n"
)


def _render_soa_matrix(rows: list) -> str:
    lines = [
        "| 控制項 | 名稱 | 適用性 | 實作狀態 | 缺口 | 建議 |",
        "|--------|------|--------|----------|------|------|",
    ]
    for row in rows:
        cid = row.get("control_id", "")
        name = row.get("control_name", "")
        applicability = row.get("applicability", "適用")
        status = row.get("implementation_status", "待確認")
        gaps = "、".join(row.get("gaps", [])) or "無"
        rec = row.get("recommendation", "")
        lines.append(f"| {cid} | {name} | {applicability} | {status} | {gaps} | {rec} |")
    return "\n".join(lines)


def _render_control_matrix(matrix: list) -> str:
    lines = [
        "| 控制項 | 名稱 | 優先級 | 缺口數 |",
        "|--------|------|--------|--------|",
    ]
    for item in matrix:
        cid = item.get("control_id", "")
        name = item.get("control_name", cid)
        priority = item.get("priority", "")
        gaps = len(item.get("gaps", []))
        lines.append(f"| {cid} | {name} | {priority} | {gaps} |")
    return "\n".join(lines)


def export_markdown_report(report: Dict[str, Any], output_path: str) -> str:
    """將報告 dict 輸出為 Markdown 檔案，回傳實際寫入路徑。

    Args:
        report      : 結構化報告 dict（soa_matrix / audit_readiness / question_pack / roadmap）。
        output_path : 輸出檔案路徑（呼叫端必須明確提供）。

    Returns:
        output_path（實際寫入路徑）。
    """
    report_type = report.get("report_type", "generic")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines: list = []

    if report_type == "soa":
        lines.append(f"# ISO 27001 SoA 草稿\n\n_產生時間：{generated_at}_\n")
        context = report.get("organization_context", "")
        if context:
            lines.append(f"**組織背景**：{context}\n")
        lines.append("\n## 控制項適用性矩陣\n")
        rows = report.get("soa_rows", [])
        lines.append(_render_soa_matrix(rows))
        lines.append("\n\n## 主要缺口摘要\n")
        all_gaps = []
        for row in rows:
            all_gaps.extend(row.get("gaps", []))
        if all_gaps:
            for g in dict.fromkeys(all_gaps):
                lines.append(f"- {g}")
        else:
            lines.append("- 未偵測到明顯缺口，建議持續維護文件。")
        lines.append("\n\n## 稽核證據建議\n")
        evidence_section = report.get("evidence_section", [])
        for ev_item in evidence_section:
            cname = ev_item.get("clause_name", ev_item.get("clause_id", ""))
            lines.append(f"\n**{cname}**")
            for ev in ev_item.get("evidence", []):
                lines.append(f"- {ev}")

    elif report_type == "audit_readiness":
        lines.append(f"# ISO 27001 稽核準備報告\n\n_產生時間：{generated_at}_\n")
        summary = report.get("summary", {})
        lines.append(
            f"**風險等級**：{summary.get('risk_level', '未知')}　"
            f"**比對控制項**：{summary.get('matched_control_count', 0)}　"
            f"**可能缺口**：{summary.get('gap_count', 0)}\n"
        )
        lines.append("\n## 控制項與缺口矩陣\n")
        lines.append(_render_control_matrix(report.get("control_matrix", [])))
        lines.append("\n\n## 優先改善項目\n")
        for item in report.get("control_matrix", []):
            if item.get("priority") == "P0" and item.get("gaps"):
                gaps_str = "、".join(item["gaps"][:3])
                lines.append(f"- **[P0] {item['control_name']}**：{gaps_str}")
        lines.append("\n\n## Quick Wins（文件補強即可）\n")
        for qw in report.get("quick_wins", []):
            lines.append(f"- {qw}")
        lines.append("\n\n## 30 / 60 / 90 天改善計畫\n")
        roadmap = report.get("roadmap", {})
        for window, label in [("days_30", "30 天"), ("days_60", "60 天"), ("days_90", "90 天")]:
            items = roadmap.get(window, [])
            if items:
                lines.append(f"\n### {label}\n")
                for item in items:
                    lines.append(f"- {item}")
        lines.append("\n\n## 待確認事項\n")
        for oq in report.get("open_questions", []):
            lines.append(f"- {oq}")

    elif report_type == "question_pack":
        lines.append(f"# ISO 27001 稽核問答包\n\n_產生時間：{generated_at}_\n")
        for pack in report.get("packs", []):
            cname = pack.get("control_name", pack.get("control_id", ""))
            cid = pack.get("control_id", "")
            lines.append(f"\n## [{cid}] {cname}\n")
            lines.append("### 稽核員可能問題\n")
            for q in pack.get("questions", []):
                lines.append(f"- {q}")
            lines.append("\n### 建議回答要點\n")
            for a in pack.get("answer_points", []):
                lines.append(f"- {a}")
            lines.append("\n### 常見追問\n")
            for f in pack.get("common_followups", []):
                lines.append(f"- {f}")
            lines.append("\n### 可展示證據\n")
            for ev in pack.get("evidence", []):
                lines.append(f"- {ev}")

    elif report_type == "roadmap":
        lines.append(f"# ISO 27001 改善路線圖\n\n_產生時間：{generated_at}_\n")
        roadmap = report.get("roadmap", {})
        lines.append(f"**{roadmap.get('summary', '')}**\n")
        for window, label in [("days_30", "30 天"), ("days_60", "60 天"), ("days_90", "90 天")]:
            items = roadmap.get(window, [])
            lines.append(f"\n## {label} 目標\n")
            if items:
                for item in items:
                    lines.append(f"- {item}")
            else:
                lines.append("- 無待改善項目")
        owners = roadmap.get("owners", [])
        if owners:
            lines.append(f"\n\n**負責團隊**：{'、'.join(owners)}")

    else:
        # 通用序列化
        lines.append(f"# ISO 27001 顧問報告\n\n_產生時間：{generated_at}_\n")
        lines.append("```json")
        lines.append(json.dumps(report, ensure_ascii=False, indent=2))
        lines.append("```")

    lines.append(_DISCLAIMER)
    content = "\n".join(lines)

    # 確保輸出目錄存在
    output_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(output_dir, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    return output_path
