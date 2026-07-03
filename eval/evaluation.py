import json
import os
import sys

from iso27001_advisor.core.search_tool import ISO27001Searcher


def compute_recall(expected: list, retrieved: list) -> float:
    """計算 Recall：命中的期望條款數 / 期望條款總數。"""
    if not expected:
        return 0.0
    hits = sum(1 for clause in expected if clause in retrieved)
    return hits / len(expected)


def compute_precision(expected: list, retrieved: list) -> float:
    """計算 Precision：retrieved 中屬於 expected 的比例。"""
    if not retrieved:
        return 0.0
    hits = sum(1 for clause in retrieved if clause in expected)
    return hits / len(retrieved)


def compute_mrr(expected: list, retrieved: list) -> float:
    """計算 MRR（Mean Reciprocal Rank）貢獻值。

    MRR = 1 / rank_of_first_hit
    若沒有任何命中，回傳 0.0。

    Note: 本函式回傳的是單題的 Reciprocal Rank，
          呼叫端對所有題目平均後即為 MRR。
    """
    for rank, clause_id in enumerate(retrieved, start=1):
        if clause_id in expected:
            return 1.0 / rank
    return 0.0


def evaluate_retrieval(top_k=4, dataset_path=None, results_path=None, searcher=None):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if dataset_path is None:
        dataset_path = os.path.join(base_dir, "data", "eval_dataset.json")
    if results_path is None:
        try:
            from iso27001_advisor.core.hybrid_search import HybridSearcher
            if isinstance(searcher, HybridSearcher):
                mode = getattr(searcher, "mode", "full")
                if mode == "keyword":
                    results_path = os.path.join(base_dir, "data", "eval_results_keyword.json")
                elif mode == "keyword+KG":
                    results_path = os.path.join(base_dir, "data", "eval_results_keyword_kg.json")
                elif mode == "keyword+RRF":
                    results_path = os.path.join(base_dir, "data", "eval_results_keyword_rrf.json")
                else:
                    results_path = os.path.join(base_dir, "data", "eval_results_hybrid.json")
            else:
                results_path = os.path.join(base_dir, "data", "eval_results.json")
        except ImportError:
            results_path = os.path.join(base_dir, "data", "eval_results.json")

    if not os.path.exists(dataset_path):
        print(f"❌ 找不到評估數據集: {dataset_path}")
        return

    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    if searcher is None:
        searcher = ISO27001Searcher()

    total_questions = len(dataset)
    retrieval_success_count = 0
    sum_recall = 0.0
    sum_precision = 0.0
    sum_rr = 0.0     # Reciprocal Rank 累計（用於計算 MRR）

    report_items = []

    print("====================================================")
    print(f"📊 開始評估檢索準確度 (Recall @ {top_k} / MRR @ {top_k})...")
    print("====================================================")

    for item in dataset:
        q_id = item["id"]
        question = item["question"]
        expected = item["expected_clauses"]

        # 進行檢索
        results = searcher.search(question, limit=top_k)
        retrieved_ids = [r["item"]["id"] for r in results]

        # 計算各指標
        recall = compute_recall(expected, retrieved_ids)
        precision = compute_precision(expected, retrieved_ids)
        rr = compute_mrr(expected, retrieved_ids)
        success = recall > 0.0

        sum_recall += recall
        sum_precision += precision
        sum_rr += rr

        if success:
            retrieval_success_count += 1
            status_str = "✅ 成功"
        else:
            status_str = "❌ 失敗"

        print(f"[{q_id}] {item['category']} - {question}")
        print(f"  期望引用: {expected}")
        print(f"  實際檢索: {retrieved_ids}")
        print(f"  結果: {status_str} (Recall: {recall*100:.1f}%  Precision: {precision*100:.1f}%  RR: {rr:.3f})")
        print("-" * 50)

        report_items.append({
            "id": q_id,
            "category": item["category"],
            "question": question,
            "expected_clauses": expected,
            "retrieved_clauses": retrieved_ids,
            "recall": recall,
            "precision": precision,
            "reciprocal_rank": rr,
            "success": success,
        })

    # 彙總指標
    hit_rate = (retrieval_success_count / total_questions) * 100
    avg_recall = (sum_recall / total_questions) * 100
    avg_precision = (sum_precision / total_questions) * 100
    mrr = sum_rr / total_questions          # Mean Reciprocal Rank

    summary = {
        "top_k": top_k,
        "total_questions": total_questions,
        "retrieval_success_count": retrieval_success_count,
        "hit_rate_percent": hit_rate,           # Any Hit：至少命中一個期望條款的題數比率
        "avg_recall_percent": avg_recall,        # 平均 Recall（命中比例的均值）
        "avg_precision_percent": avg_precision,  # 平均 Precision（retrieved 中相關比例的均值）
        "mrr": round(mrr, 4),                    # Mean Reciprocal Rank（排名品質）
        "details": report_items,
    }

    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("====================================================")
    print(f"📈 評估總結 (top_k={top_k})")
    print(f"總測試問題數:                     {total_questions}")
    print(f"Hit Rate @ {top_k} (至少命中一個): {hit_rate:.1f}%")
    print(f"Avg Recall @ {top_k}:            {avg_recall:.1f}%")
    print(f"Avg Precision @ {top_k}:         {avg_precision:.1f}%")
    print(f"MRR @ {top_k}:                   {mrr:.4f}")
    print(f"詳細報告已儲存至: {results_path}")
    print("====================================================")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="評估 ISO 27001 檢索準確度")
    parser.add_argument("top_k", type=int, nargs="?", default=4, help="檢索 top-k 數量")
    parser.add_argument("--hybrid", action="store_true", help="使用 HybridSearcher (RRF + KG)")
    parser.add_argument(
        "--mode",
        choices=["keyword", "keyword+KG", "keyword+RRF", "full"],
        default=None,
        help="消融實驗檢索模式"
    )
    parser.add_argument("--results-path", default=None, help="結果儲存路徑")
    args = parser.parse_args()

    if args.top_k < 1:
        print("❌ top-k 必須為正整數（≥ 1）", file=sys.stderr)
        sys.exit(1)

    if args.mode:
        mode = args.mode
    elif args.hybrid:
        mode = "full"
    else:
        mode = "keyword"

    if mode == "keyword" and not args.mode:
        searcher = ISO27001Searcher()
        print("💡 模式：使用純關鍵字 ISO27001Searcher")
    else:
        from iso27001_advisor.core.hybrid_search import HybridSearcher
        searcher = HybridSearcher(mode=mode)
        print(f"💡 模式：使用 HybridSearcher ({mode})")

    evaluate_retrieval(top_k=args.top_k, searcher=searcher, results_path=args.results_path)
