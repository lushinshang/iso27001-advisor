#!/usr/bin/env python3
"""level3_evaluation.py — Level 3 deterministic 評估腳本（不呼叫 LLM）。

評估項目：
1. SoA completeness   : SoA 草稿列包含所有必要欄位
2. Audit report       : 稽核準備報告含 summary、control_matrix
3. Question pack      : 問答包含必要欄位且至少 3 題
4. Roadmap            : 改善計畫含 days_30/60/90/owners
5. Evidence coverage  : 至少 4 項稽核證據
6. No formal conclusion: 工具輸出不含正式稽核結論語氣
7. Strict reference   : control_id 格式正確（control_x.x 或 clause_x.x）
"""

import json
from pathlib import Path
from typing import Dict, List, Any

from iso27001_advisor.tools.soa_tools import build_soa_matrix, draft_soa_statement
from iso27001_advisor.tools.audit_report_tools import build_audit_readiness_report, build_audit_question_pack
from iso27001_advisor.tools.action_plan_tools import build_remediation_roadmap
from iso27001_advisor.tools.evidence_tools import generate_audit_evidence_checklist
from agent import classify_task

DATASET_PATH = Path(__file__).resolve().parents[1] / "data" / "level3_eval_dataset.json"
FORBIDDEN_PHRASES = ["直接違反", "已違反", "正式不符合", "確定不符合"]

# 評估目標門檻
TARGETS = {
    "soa_completeness": 0.90,
    "audit_report_completeness": 0.90,
    "evidence_coverage": 0.90,
    "no_formal_conclusion": 1.00,
}

SOA_REQUIRED_FIELDS = [
    "control_id", "control_name", "applicability", "applicability_reason",
    "implementation_status", "gaps", "evidence", "recommendation",
]
AUDIT_REPORT_REQUIRED_FIELDS = ["summary", "control_matrix"]
QUESTION_PACK_REQUIRED_FIELDS = ["control_id", "control_name", "questions", "answer_points", "evidence"]
ROADMAP_REQUIRED_FIELDS = ["days_30", "days_60", "days_90", "owners"]


def _check_no_formal_conclusion(data: Any) -> bool:
    text = json.dumps(data, ensure_ascii=False)
    return all(p not in text for p in FORBIDDEN_PHRASES)


def _check_soa_completeness(rows: List[Dict]) -> float:
    if not rows:
        return 0.0
    scores = []
    for row in rows:
        hit = sum(1 for f in SOA_REQUIRED_FIELDS if f in row and row[f] is not None)
        scores.append(hit / len(SOA_REQUIRED_FIELDS))
    return sum(scores) / len(scores)


def _check_audit_report_completeness(report: Dict) -> float:
    hit = sum(1 for f in AUDIT_REPORT_REQUIRED_FIELDS if f in report)
    return hit / len(AUDIT_REPORT_REQUIRED_FIELDS)


def _check_question_pack_completeness(packs: List[Dict]) -> float:
    if not packs:
        return 0.0
    scores = []
    for pack in packs:
        field_hit = sum(1 for f in QUESTION_PACK_REQUIRED_FIELDS if f in pack)
        field_score = field_hit / len(QUESTION_PACK_REQUIRED_FIELDS)
        q_count = len(pack.get("questions", []))
        q_score = 1.0 if q_count >= 3 else q_count / 3
        scores.append((field_score + q_score) / 2)
    return sum(scores) / len(scores)


def _check_roadmap_completeness(roadmap: Dict) -> float:
    # list 欄位只驗證 key 存在（空 list 是合理結果，不計失分）
    # owners 若非空才算完整
    list_fields = {"days_30", "days_60", "days_90"}
    hit = 0
    for f in ROADMAP_REQUIRED_FIELDS:
        if f not in roadmap:
            continue
        if f in list_fields:
            hit += 1  # key 存在即通過
        elif roadmap[f]:
            hit += 1
    return hit / len(ROADMAP_REQUIRED_FIELDS)


def _check_evidence_coverage(evidence_list: List[Dict], min_items: int = 4) -> float:
    total = sum(len(e.get("evidence", [])) for e in evidence_list)
    return 1.0 if total >= min_items else total / min_items


def _make_mock_gap(missing_themes: List[str] = None) -> Dict:
    if missing_themes is None:
        missing_themes = ["還原測試", "備份保存期限"]
    return {
        "covered_signals": [{"keyword": "備份"}] if missing_themes else [],
        "missing_signals": [{"theme": t} for t in missing_themes],
        "risk_level": "high" if len(missing_themes) > 2 else "medium",
        "notes": [],
    }


def run_evaluation():
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))

    results = {
        "soa_completeness": [],
        "audit_report_completeness": [],
        "question_pack_completeness": [],
        "roadmap_completeness": [],
        "evidence_coverage": [],
        "no_formal_conclusion": [],
        "mode_classify": [],
    }

    print(f"{'='*60}")
    print(f"  ISO 27001 Level 3 Deterministic Evaluation")
    print(f"  資料集：{len(dataset)} 題")
    print(f"{'='*60}\n")

    for case in dataset:
        cid = case["id"]
        category = case["category"]
        query = case["query"]
        expected_controls = case.get("expected_controls", [])
        checks = case.get("checks", {})

        print(f"[{cid}] {category} — {query[:50]}...")

        # 1. 模式分類
        classified = classify_task(query)
        expected_mode = case.get("expected_mode", category)
        mode_ok = classified == expected_mode
        results["mode_classify"].append(mode_ok)
        print(f"  模式分類: {classified} (預期: {expected_mode}) {'✅' if mode_ok else '❌'}")

        # 2. 依 category 執行對應工具
        if category == "soa":
            rows = build_soa_matrix(expected_controls, query)
            score = _check_soa_completeness(rows)
            results["soa_completeness"].append(score)
            print(f"  SoA completeness: {score:.0%}")

            no_conc = _check_no_formal_conclusion(rows)
            results["no_formal_conclusion"].append(no_conc)
            print(f"  No formal conclusion: {'✅' if no_conc else '❌'}")

            ev_list = generate_audit_evidence_checklist(expected_controls)
            ev_score = _check_evidence_coverage(ev_list)
            results["evidence_coverage"].append(ev_score)
            print(f"  Evidence coverage: {ev_score:.0%} ({sum(len(e['evidence']) for e in ev_list)} 項)")

            # 驗證 implementation_status
            if "implementation_status" in checks:
                for row in rows:
                    actual_status = row.get("implementation_status")
                    if row.get("gaps"):
                        status_ok = actual_status == "部分實作"
                        print(f"  implementation_status [{row['control_id']}]: {actual_status} {'✅' if status_ok else '❌'}")

        elif category == "audit-report":
            gap = _make_mock_gap(["還原測試", "備份保存期限", "日誌審查週期"])
            matched = [{"id": cid_ctrl, "subsection": cid_ctrl, "score": 0.8} for cid_ctrl in expected_controls]
            ev_list = generate_audit_evidence_checklist(expected_controls)
            report = build_audit_readiness_report(query, matched, gap, ev_list, [])

            score = _check_audit_report_completeness(report)
            results["audit_report_completeness"].append(score)
            print(f"  Audit report completeness: {score:.0%}")

            roadmap = build_remediation_roadmap(gap, expected_controls)
            rm_score = _check_roadmap_completeness(roadmap)
            results["roadmap_completeness"].append(rm_score)
            print(f"  Roadmap completeness: {rm_score:.0%}")

            no_conc = _check_no_formal_conclusion(report)
            results["no_formal_conclusion"].append(no_conc)
            print(f"  No formal conclusion: {'✅' if no_conc else '❌'}")

            ev_score = _check_evidence_coverage(ev_list)
            results["evidence_coverage"].append(ev_score)
            print(f"  Evidence coverage: {ev_score:.0%}")

        elif category == "audit-pack":
            packs = build_audit_question_pack(expected_controls)
            score = _check_question_pack_completeness(packs)
            results["question_pack_completeness"].append(score)
            print(f"  Question pack completeness: {score:.0%}")

            no_conc = _check_no_formal_conclusion(packs)
            results["no_formal_conclusion"].append(no_conc)
            print(f"  No formal conclusion: {'✅' if no_conc else '❌'}")

            ev_list = generate_audit_evidence_checklist(expected_controls)
            ev_score = _check_evidence_coverage(ev_list)
            results["evidence_coverage"].append(ev_score)
            print(f"  Evidence coverage: {ev_score:.0%}")

        elif category == "roadmap":
            gap = _make_mock_gap(["還原測試", "定期存取權限覆核", "日誌審查週期"])
            roadmap = build_remediation_roadmap(gap, expected_controls)
            score = _check_roadmap_completeness(roadmap)
            results["roadmap_completeness"].append(score)
            print(f"  Roadmap completeness: {score:.0%}")

            no_conc = _check_no_formal_conclusion(roadmap)
            results["no_formal_conclusion"].append(no_conc)
            print(f"  No formal conclusion: {'✅' if no_conc else '❌'}")

        print()

    # ── 彙整結果 ──
    print(f"{'='*60}")
    print("  評估結果彙整")
    print(f"{'='*60}")

    def _avg(lst): return sum(lst) / len(lst) if lst else None
    def _pass_fail(score, target): return "✅ PASS" if score is not None and score >= target else "❌ FAIL"

    metrics = {
        "SoA completeness":             (_avg(results["soa_completeness"]), TARGETS["soa_completeness"]),
        "Audit report completeness":     (_avg(results["audit_report_completeness"]), TARGETS["audit_report_completeness"]),
        "Evidence coverage":             (_avg(results["evidence_coverage"]), TARGETS["evidence_coverage"]),
        "No formal conclusion":          (_avg([float(x) for x in results["no_formal_conclusion"]]), TARGETS["no_formal_conclusion"]),
        "Mode classify accuracy":        (_avg([float(x) for x in results["mode_classify"]]), 0.80),
        "Question pack completeness":    (_avg(results["question_pack_completeness"]), 0.90),
        "Roadmap completeness":          (_avg(results["roadmap_completeness"]), 0.90),
    }

    all_passed = True
    for name, (score, target) in metrics.items():
        if score is None:
            print(f"  {name}: N/A（無樣本）")
            continue
        status = _pass_fail(score, target)
        print(f"  {name}: {score:.0%} (目標 {target:.0%}) {status}")
        if score < target:
            all_passed = False

    print(f"\n{'='*60}")
    print(f"  最終結果：{'✅ ALL PASS' if all_passed else '❌ SOME FAILED'}")
    print(f"{'='*60}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(run_evaluation())
