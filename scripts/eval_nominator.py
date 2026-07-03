#!/usr/bin/env python3
"""提名器評測工具。"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BASE_DIR / "src"
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from scripts.build_knowledge_graph import (  # noqa: E402
    DEFAULT_EMBEDDINGS_PATH,
    DEFAULT_HOST,
    DEFAULT_MODELS,
    DEFAULT_STRUCTURE_PATH,
    run_kg_pipeline,
)

DEFAULT_CHT_PATH = BASE_DIR / "data" / "cht.md"
DEFAULT_PDCA_PATH = BASE_DIR / "data" / "pdca_graph.json"
DEFAULT_GOLD_PATH = BASE_DIR / "data" / "kg_gold_edges.json"
DEFAULT_RESULTS_PATH = BASE_DIR / "data" / "nominator_eval_results.json"


def _edge_key(edge):
    if isinstance(edge, dict):
        left = edge["from"]
        right = edge["to"]
    else:
        left, right = edge
    return tuple(sorted((left, right)))


def compute_honesty_rate(g2_passed, total_nominated):
    if total_nominated <= 0:
        return 0.0
    return g2_passed / total_nominated


def compute_convergence_curve(round_edges):
    seen = set()
    curve = []
    for edges in round_edges:
        new_count = 0
        for edge in edges:
            key = _edge_key(edge)
            if key not in seen:
                seen.add(key)
                new_count += 1
        curve.append(new_count)
    return curve


def compute_gold_recall(survived_edges, gold_edges):
    gold = {_edge_key(edge) for edge in gold_edges}
    if not gold:
        return 0.0
    survived = {_edge_key(edge) for edge in survived_edges}
    return len(gold & survived) / len(gold)


def extract_gold_edges(
    pdca_path=DEFAULT_PDCA_PATH,
    structure_path=DEFAULT_STRUCTURE_PATH,
    output_path=DEFAULT_GOLD_PATH,
):
    """從 pdca_graph.json 的 related 欄位抽取黃金邊；next 流程邊不採用。"""
    structure = json.loads(Path(structure_path).read_text(encoding="utf-8"))
    id_set = {item["id"] for item in structure}
    pdca_graph = json.loads(Path(pdca_path).read_text(encoding="utf-8"))
    edge_keys = set()
    for source_id, node in pdca_graph.items():
        if source_id not in id_set:
            continue
        for target_id in node.get("related", []):
            if target_id not in id_set or target_id == source_id:
                continue
            edge_keys.add(tuple(sorted((source_id, target_id))))

    edges = [
        {"from": left, "to": right, "source": "pdca_graph"}
        for left, right in sorted(edge_keys)
    ]
    output = {"source": str(pdca_path), "edges": edges}
    Path(output_path).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def evaluate_models(
    models,
    sample=25,
    rounds=2,
    structure_path=DEFAULT_STRUCTURE_PATH,
    embeddings_path=DEFAULT_EMBEDDINGS_PATH,
    gold_path=DEFAULT_GOLD_PATH,
    output_path=DEFAULT_RESULTS_PATH,
    host=DEFAULT_HOST,
):
    structure_items = json.loads(Path(structure_path).read_text(encoding="utf-8"))
    if not Path(gold_path).exists():
        extract_gold_edges(structure_path=structure_path, output_path=gold_path)
    gold_payload = json.loads(Path(gold_path).read_text(encoding="utf-8"))
    gold_edges = gold_payload.get("edges", [])

    rows = []
    for model in models:
        graph = run_kg_pipeline(
            structure_path=structure_path,
            embeddings_path=embeddings_path,
            output_path=Path(tempfile.gettempdir()) / f"kg_eval_{model.replace('/', '_').replace(':', '_')}.json",
            models=[model],
            rounds=rounds,
            host=host,
            sample=sample,
        )
        report = graph["gate_report"]
        total = report["nominated"]
        g2_passed = total - report["g2_rejected"]
        attempts = max(min(sample, len(structure_items)) * rounds, 1)
        format_failures = graph.get("format_failures", {}).get(model, 0)
        rows.append(
            {
                "model": model,
                "format_valid_rate": round(1 - (format_failures / attempts), 4),
                "honesty_rate": round(compute_honesty_rate(g2_passed, total), 4),
                "survived_edges": report["survived"],
                "convergence_curve": [report["survived"]],
                "gold_recall": round(compute_gold_recall(graph["edges"], gold_edges), 4),
                "gate_report": report,
            }
        )

    result = {"sample": min(sample, len(structure_items)), "rounds": rounds, "results": rows}
    Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _print_markdown(result):
    print("| model | format_valid_rate | honesty_rate | survived_edges | gold_recall |")
    print("|---|---:|---:|---:|---:|")
    for row in result["results"]:
        print(
            f"| {row['model']} | {row['format_valid_rate']:.2%} | "
            f"{row['honesty_rate']:.2%} | {row['survived_edges']} | {row['gold_recall']:.2%} |"
        )


def main():
    parser = argparse.ArgumentParser(description="評測 KG 提名器")
    parser.add_argument("--sample", type=int, default=25)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--extract-gold", action="store_true")
    args = parser.parse_args()

    if args.extract_gold:
        output = extract_gold_edges()
        print(f"✅ 黃金邊抽取完成：{len(output['edges'])} 條 → {DEFAULT_GOLD_PATH}")
        return

    models = [model.strip() for model in args.models.split(",") if model.strip()]
    result = evaluate_models(models, sample=args.sample, rounds=args.rounds, host=args.host)
    _print_markdown(result)
    print(f"\n結果已儲存至：{DEFAULT_RESULTS_PATH}")


if __name__ == "__main__":
    main()
