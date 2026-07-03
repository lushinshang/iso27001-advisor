"""Level 2 Gap Analysis Evaluation Script.

自動評估 ISO 27001 Level 2 gap analysis 工具的準確率。
只測試 deterministic tools，不呼叫 LLM。

Usage:
    python3 level2_evaluation.py [--top-k N] [--verbose]
    SKIP_DOTENV=1 python3 level2_evaluation.py
"""

import argparse
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from iso27001_advisor.tools.iso_tools import search_iso
from iso27001_advisor.tools.gap_analysis_tools import analyze_document_coverage
from iso27001_advisor.tools.evidence_tools import generate_audit_evidence_checklist

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# 資料載入
# ---------------------------------------------------------------------------

def load_dataset(path: str) -> List[Dict]:
    """載入評估資料集。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 指標 1：Clause Retrieval Hit Rate
# ---------------------------------------------------------------------------

def eval_clause_retrieval(question: Dict, top_k: int) -> Tuple[bool, List[str]]:
    """呼叫 search_iso，檢查 expected_clause_ids 是否至少命中一個。

    Returns:
        (hit: bool, retrieved_ids: List[str])
    """
    doc = question["document"]
    expected = question.get("expected_clause_ids", [])

    results = search_iso(doc, top_k=top_k)
    retrieved_ids = [r["id"] for r in results]

    hit = any(eid in retrieved_ids for eid in expected)
    return hit, retrieved_ids


# ---------------------------------------------------------------------------
# 指標 2：Gap Detection Recall  +  指標 3：Coverage Signal Precision
# ---------------------------------------------------------------------------

def eval_gap_and_coverage(
    question: Dict, retrieved_ids: List[str]
) -> Tuple[Optional[bool], List[str], List[str], Optional[bool]]:
    """呼叫 analyze_document_coverage，評估 gap 與 coverage。

    Returns:
        gap_detected_all: None if no expected_gaps, else bool
        detected_gaps: list of theme strings found in missing_signals
        missing_from_detection: expected gaps not found
        coverage_hit: None if no expected_covered, else bool (at least one keyword hit)
    """
    doc = question["document"]
    expected_gaps = question.get("expected_gaps", [])
    expected_covered = question.get("expected_covered", [])

    # 用 retrieved_ids 組建 matched_items（只需 id 欄位）
    matched_items = [{"id": rid} for rid in retrieved_ids]

    analysis = analyze_document_coverage(doc, matched_items)
    missing_signals: List[Dict] = analysis.get("missing_signals", [])
    covered_signals: List[Dict] = analysis.get("covered_signals", [])

    detected_gap_themes = [s["theme"] for s in missing_signals]
    detected_covered_keywords = [s["keyword"] for s in covered_signals]

    # Gap detection
    if not expected_gaps:
        gap_detected_all = None
        missing_from_detection = []
    else:
        missing_from_detection = [
            eg for eg in expected_gaps
            if not any(eg in dt for dt in detected_gap_themes)
        ]
        gap_detected_all = len(missing_from_detection) == 0

    # Coverage signal
    if not expected_covered:
        coverage_hit = None
    else:
        coverage_hit = any(
            any(ek.lower() in ck.lower() or ck.lower() in ek.lower()
                for ck in detected_covered_keywords)
            for ek in expected_covered
        )

    return gap_detected_all, detected_gap_themes, missing_from_detection, coverage_hit


# ---------------------------------------------------------------------------
# 指標 4：Evidence Checklist Coverage
# ---------------------------------------------------------------------------

def eval_evidence_checklist(question: Dict) -> bool:
    """呼叫 generate_audit_evidence_checklist，確認至少回傳 1 筆証據。"""
    clause_ids = question.get("expected_clause_ids", [])
    results = generate_audit_evidence_checklist(clause_ids)
    return len(results) > 0


# ---------------------------------------------------------------------------
# 主評估流程
# ---------------------------------------------------------------------------

def run_evaluation(
    dataset: List[Dict],
    top_k: int = 4,
    verbose: bool = False,
) -> Dict[str, Any]:
    """執行全部評估，回傳彙整結果。"""
    total = len(dataset)
    gap_questions = [q for q in dataset if q.get("mode") == "gap"]
    evidence_questions = [q for q in dataset if q.get("mode") == "evidence"]

    # 計數器
    retrieval_hits = 0

    gap_with_expected = []   # 有 expected_gaps 的題目
    fully_detected = 0
    partially_detected = 0
    not_detected = 0

    coverage_with_expected = []   # 有 expected_covered 的題目
    coverage_hit_count = 0

    evidence_non_empty = 0

    details = []

    # Per-control 統計：{control_area: {"total": n, "retrieval_hit": n, "gap_expected": n, "gap_hit": n}}
    per_control: Dict[str, Dict] = {}

    for q in dataset:
        qid = q["id"]
        mode = q.get("mode", "gap")
        control_area = q.get("control_area", "unknown")

        if control_area not in per_control:
            per_control[control_area] = {
                "total": 0,
                "retrieval_hit": 0,
                "gap_expected": 0,
                "gap_hit": 0,
            }
        per_control[control_area]["total"] += 1

        # --- Metric 1: Clause Retrieval ---
        hit, retrieved_ids = eval_clause_retrieval(q, top_k=top_k)
        if hit:
            retrieval_hits += 1
            per_control[control_area]["retrieval_hit"] += 1

        # --- Metric 2 & 3: Gap + Coverage ---
        gap_detected_all, detected_gaps, missing_from_detection, coverage_hit = (
            eval_gap_and_coverage(q, retrieved_ids)
        )

        expected_gaps = q.get("expected_gaps", [])
        expected_covered = q.get("expected_covered", [])

        if expected_gaps:
            gap_with_expected.append(qid)
            per_control[control_area]["gap_expected"] += 1
            if gap_detected_all:
                fully_detected += 1
                per_control[control_area]["gap_hit"] += 1
            elif len(missing_from_detection) < len(expected_gaps):
                partially_detected += 1
            else:
                not_detected += 1

        if expected_covered:
            coverage_with_expected.append(qid)
            if coverage_hit:
                coverage_hit_count += 1

        # --- Metric 4: Evidence Checklist (evidence mode only) ---
        evidence_result = None
        if mode == "evidence":
            evidence_result = eval_evidence_checklist(q)
            if evidence_result:
                evidence_non_empty += 1

        # Detail record
        detail: Dict[str, Any] = {
            "id": qid,
            "mode": mode,
            "control_area": control_area,
            "clause_hit": hit,
            "retrieved_ids": retrieved_ids,
        }

        if expected_gaps is not None:
            detail["gap_detected_all"] = gap_detected_all
            detail["expected_gaps"] = expected_gaps
            detail["detected_gaps"] = detected_gaps
            detail["missing_from_detection"] = missing_from_detection

        if expected_covered is not None:
            detail["coverage_signal_hit"] = coverage_hit
            detail["expected_covered"] = expected_covered

        if evidence_result is not None:
            detail["evidence_checklist_non_empty"] = evidence_result

        details.append(detail)

        if verbose:
            gap_str = f"gap_all={gap_detected_all}" if expected_gaps else "gap=N/A"
            cov_str = f"cov={coverage_hit}" if expected_covered else "cov=N/A"
            print(
                f"  [{qid}] retrieval={'HIT' if hit else 'MISS'} "
                f"{gap_str} {cov_str}"
            )

    # --- 計算指標 ---
    hit_rate = retrieval_hits / total if total > 0 else 0.0

    n_gap_expected = len(gap_with_expected)
    gap_detection_recall = fully_detected / n_gap_expected if n_gap_expected > 0 else 0.0
    gap_partial_rate = partially_detected / n_gap_expected if n_gap_expected > 0 else 0.0
    gap_miss_rate = not_detected / n_gap_expected if n_gap_expected > 0 else 0.0

    n_cov_expected = len(coverage_with_expected)
    coverage_precision = coverage_hit_count / n_cov_expected if n_cov_expected > 0 else 0.0

    n_evidence = len(evidence_questions)
    evidence_coverage = evidence_non_empty / n_evidence if n_evidence > 0 else 0.0

    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "total": total,
        "top_k": top_k,
        "gap_mode_count": len(gap_questions),
        "evidence_mode_count": len(evidence_questions),
        # Metric 1
        "retrieval_hits": retrieval_hits,
        "hit_rate": round(hit_rate, 4),
        # Metric 2
        "gap_questions_with_expected": n_gap_expected,
        "gap_fully_detected": fully_detected,
        "gap_partially_detected": partially_detected,
        "gap_not_detected": not_detected,
        "gap_detection_recall": round(gap_detection_recall, 4),
        "gap_partial_rate": round(gap_partial_rate, 4),
        "gap_miss_rate": round(gap_miss_rate, 4),
        # Metric 3
        "coverage_questions_with_expected": n_cov_expected,
        "coverage_signal_hits": coverage_hit_count,
        "coverage_signal_precision": round(coverage_precision, 4),
        # Metric 4
        "evidence_mode_questions": n_evidence,
        "evidence_non_empty": evidence_non_empty,
        "evidence_checklist_coverage": round(evidence_coverage, 4),
        # Per-control
        "per_control": per_control,
        # Detail
        "details": details,
    }


# ---------------------------------------------------------------------------
# 報告輸出
# ---------------------------------------------------------------------------

def print_report(result: Dict[str, Any], output_path: str) -> None:
    """印出評估報告。"""
    total = result["total"]
    top_k = result["top_k"]
    gap_mode = result["gap_mode_count"]
    ev_mode = result["evidence_mode_count"]

    rh = result["retrieval_hits"]
    hr = result["hit_rate"]

    n_gap = result["gap_questions_with_expected"]
    gfd = result["gap_fully_detected"]
    gpd = result["gap_partially_detected"]
    gnd = result["gap_not_detected"]
    gdr = result["gap_detection_recall"]
    gpr = result["gap_partial_rate"]
    gmr = result["gap_miss_rate"]

    n_cov = result["coverage_questions_with_expected"]
    csh = result["coverage_signal_hits"]
    csp = result["coverage_signal_precision"]

    n_ev = result["evidence_mode_questions"]
    ene = result["evidence_non_empty"]
    ecc = result["evidence_checklist_coverage"]

    per_control: Dict = result["per_control"]

    print("=" * 52)
    print(" ISO 27001 Level 2 Evaluation Results")
    print("=" * 52)
    print(f"Total questions: {total}")
    print(f"  gap mode: {gap_mode}  |  evidence mode: {ev_mode}")
    print()

    print("--- Clause Retrieval ---")
    print(f"Hit Rate @ {top_k}: {rh}/{total} = {hr * 100:.1f}%")
    print()

    print("--- Gap Detection ---")
    print(f"Questions with expected_gaps: {n_gap}")
    print(f"Fully detected:     {gfd}/{n_gap} = {gdr * 100:.1f}%")
    print(f"Partially detected: {gpd}/{n_gap} = {gpr * 100:.1f}%")
    print(f"Not detected:       {gnd}/{n_gap} = {gmr * 100:.1f}%")
    print()

    print("--- Coverage Signal ---")
    print(f"Questions with expected_covered: {n_cov}")
    print(f"At least one signal found: {csh}/{n_cov} = {csp * 100:.1f}%")
    print()

    print("--- Evidence Checklist ---")
    print(f"Evidence mode questions: {n_ev}")
    print(f"Non-empty checklists: {ene}/{n_ev} = {ecc * 100:.1f}%")
    print()

    print("--- Per-Control Summary ---")
    for ctrl, stats in sorted(per_control.items()):
        n = stats["total"]
        r_hit = stats["retrieval_hit"]
        g_exp = stats["gap_expected"]
        g_hit = stats["gap_hit"]
        gap_str = f", gap_recall {g_hit}/{g_exp}" if g_exp > 0 else ""
        print(f"{ctrl} ({n} q): retrieval {r_hit}/{n}{gap_str}")
    print()

    print("=" * 52)
    print(f"Saved to: {output_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate ISO 27001 Level 2 gap analysis tools."
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=4,
        help="Number of results to retrieve per query (default: 4)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-question results during evaluation",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default=os.path.join(_PROJECT_DIR, "data", "level2_eval_dataset.json"),
        help="Path to evaluation dataset JSON",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=os.path.join(_PROJECT_DIR, "data", "level2_eval_results.json"),
        help="Path for output results JSON",
    )
    args = parser.parse_args()

    print(f"Loading dataset: {args.dataset}")
    dataset = load_dataset(args.dataset)
    print(f"Loaded {len(dataset)} questions")

    if args.verbose:
        print("\n--- Per-question evaluation ---")

    result = run_evaluation(dataset, top_k=args.top_k, verbose=args.verbose)

    # 存結果
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print()
    print_report(result, args.output)


if __name__ == "__main__":
    main()
