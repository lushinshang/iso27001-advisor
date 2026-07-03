#!/usr/bin/env python3
"""建立 ISO 27001 Knowledge Graph。"""

import argparse
import json
import re
import sys
import random
import time
import urllib.request
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BASE_DIR / "src"
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from iso27001_advisor.core.kg_gates import (  # noqa: E402
    apply_degree_cap,
    cosine_similarity,
    gate_bidirectional,
    gate_evidence,
    gate_similarity,
    gate_structure,
    normalize_edge,
)

DEFAULT_STRUCTURE_PATH = BASE_DIR / "data" / "iso27001_structure.json"
DEFAULT_EMBEDDINGS_PATH = BASE_DIR / "data" / "clause_embeddings.json"
DEFAULT_OUTPUT_PATH = BASE_DIR / "data" / "knowledge_graph.json"
DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODELS = ["gemma3:12b-16k", "gemma4:e2b-mlx"]
DEFAULT_CHECKPOINT_DIR = BASE_DIR / "tmp" / "kg_checkpoints"
DEFAULT_CANDIDATE_LIMIT = 15


def _ensure_localhost(host):
    if not (host.startswith("http://localhost:") or host.startswith("http://127.0.0.1:")):
        raise ValueError("只允許 localhost Ollama，禁止非本機網路呼叫")


def _load_json(path):
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def _item_summary(item):
    content = item.get("content", "")
    return "\n".join(
        [
            f"ID: {item.get('id', '')}",
            f"標題: {item.get('title', '')}",
            f"段落: {item.get('subsection', '')}",
            f"內容: {content[:200]}",
        ]
    )


def parse_llm_json_response(raw_text):
    """解析 LLM 回應中的 JSON 物件，容忍 fenced JSON 與前後說明文字。"""
    text = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.S | re.I)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("LLM 回應不含可解析 JSON")
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM 回應 JSON 解析失敗：{exc}") from exc


def call_ollama_nominator(item, all_items, model, round_index, host=DEFAULT_HOST):
    """呼叫本機 Ollama 從候選清單確認關聯。JSON 失敗時重試一次。"""
    _ensure_localhost(host)
    candidates = [
        _item_summary(other)
        for other in all_items
        if other.get("id") != item.get("id")
    ]
    prompt = (
        "你是 ISO 27001 條文關聯確認器。請只從候選條文中挑出真正相關者；"
        "不得輸出候選清單以外的 id。若沒有相關者，輸出 {\"related\": []}。"
        "請只輸出 JSON，格式為 "
        '{"related":[{"id":"...","evidence_self":"...","evidence_other":"..."}]}。'
        "evidence_self 必須一字不差複製來源條文中的連續原文片段。"
        "evidence_other 必須一字不差複製對方條文中的連續原文片段。"
        "禁止改寫、摘要、省略號、增字、刪字或交換 self/other 引句。"
        f"\n來源條文：\n{_item_summary(item)}\n候選條文：\n"
        + "\n---\n".join(candidates)
    )
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }
    url = f"{host}/api/generate"
    last_error = None
    for _attempt in range(2):
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        try:
            return parse_llm_json_response(data.get("response", "{}"))
        except ValueError as exc:
            last_error = exc
    raise ValueError(f"提名器 JSON 解析失敗：{last_error}")


def _safe_name(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _suffix(item_id):
    return item_id.split("_", 1)[1] if "_" in item_id else item_id


def _is_parent_child(left_id, right_id):
    left = _suffix(left_id)
    right = _suffix(right_id)
    return right.startswith(left + ".") or left.startswith(right + ".")


def _candidate_items(item, items, emb_map, limit=DEFAULT_CANDIDATE_LIMIT):
    source_emb = emb_map.get(item.get("id"))
    if source_emb is None:
        return [
            other
            for other in items
            if other.get("id") != item.get("id")
            and not _is_parent_child(item.get("id", ""), other.get("id", ""))
        ][:limit]

    scored = []
    for other in items:
        if other.get("id") == item.get("id"):
            continue
        if _is_parent_child(item.get("id", ""), other.get("id", "")):
            continue
        other_emb = emb_map.get(other.get("id"))
        if other_emb is None:
            continue
        scored.append((cosine_similarity(source_emb, other_emb), other))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [other for _score, other in scored[:limit]]


def _checkpoint_path(checkpoint_dir, model, round_index, item_id):
    return Path(checkpoint_dir) / f"{_safe_name(model)}__r{round_index}__{_safe_name(item_id)}.json"


def _collect_nominations(
    items,
    candidate_pool,
    models,
    rounds,
    nominator_func,
    host,
    emb_map=None,
    checkpoint_dir=None,
):
    nominations = []
    format_failures = {model: 0 for model in models}
    timing = {"llm_calls": 0, "total_llm_seconds": 0.0}
    if checkpoint_dir is not None:
        Path(checkpoint_dir).mkdir(parents=True, exist_ok=True)

    for model in models:
        for round_index in range(rounds):
            for offset, item in enumerate(items, start=1):
                print(
                    f"[KG] {model} round {round_index + 1}/{rounds} "
                    f"{offset}/{len(items)} {item['id']}",
                    flush=True,
                )
                candidates = _candidate_items(item, candidate_pool, emb_map or {})
                ckpt_path = (
                    _checkpoint_path(checkpoint_dir, model, round_index, item["id"])
                    if checkpoint_dir is not None
                    else None
                )
                if ckpt_path is not None and ckpt_path.exists():
                    response = json.loads(ckpt_path.read_text(encoding="utf-8"))
                else:
                    started_at = time.monotonic()
                    try:
                        try:
                            response = nominator_func(item, candidates, model, round_index)
                        except TypeError:
                            response = nominator_func(item, candidates, model, round_index, host)
                    except Exception:
                        elapsed = time.monotonic() - started_at
                        timing["llm_calls"] += 1
                        timing["total_llm_seconds"] += elapsed
                        format_failures[model] += 1
                        continue
                    elapsed = time.monotonic() - started_at
                    timing["llm_calls"] += 1
                    timing["total_llm_seconds"] += elapsed
                    if ckpt_path is not None:
                        ckpt_path.write_text(
                            json.dumps(response, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )

                if isinstance(response, str):
                    try:
                        response = json.loads(response)
                    except json.JSONDecodeError:
                        format_failures[model] += 1
                        continue

                related = response.get("related", []) if isinstance(response, dict) else []
                if not isinstance(related, list):
                    format_failures[model] += 1
                    continue

                for relation in related:
                    if not isinstance(relation, dict):
                        format_failures[model] += 1
                        continue
                    if relation.get("id") not in {candidate["id"] for candidate in candidates}:
                        format_failures[model] += 1
                        continue
                    nominations.append(
                        {
                            "from": item["id"],
                            "to": relation.get("id", ""),
                            "evidence_from": relation.get("evidence_self", ""),
                            "evidence_to": relation.get("evidence_other", ""),
                            "nominated_by": model,
                        }
                    )
    return nominations, format_failures, timing


def run_kg_pipeline(
    structure_path=DEFAULT_STRUCTURE_PATH,
    embeddings_path=DEFAULT_EMBEDDINGS_PATH,
    output_path=DEFAULT_OUTPUT_PATH,
    models=None,
    rounds=2,
    nominator_func=None,
    host=DEFAULT_HOST,
    checkpoint_dir=None,
    sample=None,
    from_pdca=False,
    pdca_path=None,
):
    """執行提名 → G1-G4 → degree cap → 輸出 KG。"""
    if from_pdca:
        pdca_path = pdca_path or (BASE_DIR / "data" / "pdca_graph.json")
        pdca_data = _load_json(pdca_path)
        source_items = _load_json(structure_path)
        emb_index = _load_json(embeddings_path)
        id_index = {item["id"]: item for item in source_items}
        emb_map = {item["id"]: item["embedding"] for item in emb_index.get("items", [])}

        # 1. 展開邊對
        initial_edges = {}
        for from_id, value in pdca_data.items():
            if not isinstance(value, dict) or "related" not in value:
                continue
            for to_id in value["related"]:
                # 去重正規化：from < to 字典序
                f, t = sorted([from_id, to_id])
                initial_edges[(f, t)] = {"from": f, "to": t}

        nominated_count = len(initial_edges)

        # 2. 套用 G1 結構規則
        passed = []
        g1_rejected_before_cap = 0
        for edge in initial_edges.values():
            if gate_structure(edge, id_index):
                from_emb = emb_map.get(edge["from"])
                to_emb = emb_map.get(edge["to"])
                if from_emb is not None and to_emb is not None:
                    edge["similarity"] = round(cosine_similarity(from_emb, to_emb), 4)
                else:
                    edge["similarity"] = 0.0
                passed.append(edge)
            else:
                g1_rejected_before_cap += 1

        # 3. 套用 degree cap
        edges = apply_degree_cap(passed, cap=6)
        g1_rejected_by_cap = len(passed) - len(edges)
        g1_rejected = g1_rejected_before_cap + g1_rejected_by_cap

        # 補上必要的屬性，G2/G3/G4 跳過，evidence 置空，source 標 pdca_graph
        for edge in edges:
            edge["evidence_from"] = ""
            edge["evidence_to"] = ""
            edge["nominated_by"] = ["pdca_graph"]
            edge["bidirectional"] = True
            edge["source"] = "pdca_graph"

        edges.sort(key=lambda edge: (edge["from"], edge["to"]))

        report = {
            "nominated": nominated_count,
            "g1_rejected": g1_rejected,
            "g2_rejected": 0,
            "g3_rejected": 0,
            "g4_rejected": 0,
            "survived": len(edges),
        }

        # 計算相似度分佈
        similarities = [edge["similarity"] for edge in edges]
        if similarities:
            min_sim = min(similarities)
            max_sim = max(similarities)
            avg_sim = sum(similarities) / len(similarities)
            sorted_sims = sorted(similarities)
            n = len(sorted_sims)
            if n % 2 == 1:
                median_sim = sorted_sims[n // 2]
            else:
                median_sim = (sorted_sims[n // 2 - 1] + sorted_sims[n // 2]) / 2.0
        else:
            min_sim = max_sim = avg_sim = median_sim = 0.0

        similarity_dist = {
            "count": len(similarities),
            "min": round(min_sim, 4),
            "max": round(max_sim, 4),
            "avg": round(avg_sim, 4),
            "median": round(median_sim, 4)
        }

        graph = {
            "built_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "nominators": ["pdca_graph"],
            "gates_version": 1,
            "gate_report": report,
            "similarity_distribution": similarity_dist,
            "edges": edges,
        }

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(graph, f, ensure_ascii=False, indent=2)

        print("[KG] --from-pdca 相似度分布統計：")
        print(f"     總邊數: {similarity_dist['count']}")
        print(f"     最小值: {similarity_dist['min']}")
        print(f"     最大值: {similarity_dist['max']}")
        print(f"     平均值: {similarity_dist['avg']}")
        print(f"     中位數: {similarity_dist['median']}")

        return graph

    _ensure_localhost(host)
    models = models or DEFAULT_MODELS
    nominator_func = nominator_func or call_ollama_nominator

    source_items = _load_json(structure_path)
    emb_index = _load_json(embeddings_path)
    id_index = {item["id"]: item for item in source_items}
    emb_map = {item["id"]: item["embedding"] for item in emb_index.get("items", [])}
    candidate_pool = [item for item in source_items if item.get("id") in emb_map]
    items = list(candidate_pool)
    if sample is not None:
        rng = random.Random(42)
        items = rng.sample(items, min(sample, len(items)))

    nominations, format_failures, timing = _collect_nominations(
        items,
        candidate_pool,
        models,
        rounds,
        nominator_func,
        host,
        emb_map=emb_map,
        checkpoint_dir=checkpoint_dir,
    )
    report = {
        "nominated": len(nominations),
        "g1_rejected": 0,
        "g2_rejected": 0,
        "g3_rejected": 0,
        "g4_rejected": 0,
        "survived": 0,
    }

    passed = []
    for edge in nominations:
        if not gate_structure(edge, id_index):
            report["g1_rejected"] += 1
            continue
        if not gate_evidence(edge, id_index):
            report["g2_rejected"] += 1
            continue
        if not gate_similarity(edge, emb_map, floor=0.5):
            report["g3_rejected"] += 1
            continue
        edge = dict(edge)
        edge["similarity"] = cosine_similarity(emb_map[edge["from"]], emb_map[edge["to"]])
        passed.append(edge)

    grouped = {}
    for edge in passed:
        if not gate_bidirectional(edge, passed):
            report["g4_rejected"] += 1
            continue

        normalized = normalize_edge(edge)
        key = (normalized["from"], normalized["to"])
        existing = grouped.get(key)
        if existing is None or normalized["similarity"] > existing["similarity"]:
            grouped[key] = {
                "from": normalized["from"],
                "to": normalized["to"],
                "evidence_from": normalized.get("evidence_from", ""),
                "evidence_to": normalized.get("evidence_to", ""),
                "similarity": round(normalized["similarity"], 4),
                "nominated_by": {edge["nominated_by"]},
                "bidirectional": True,
            }
        else:
            existing["nominated_by"].add(edge["nominated_by"])

    edges = apply_degree_cap(list(grouped.values()), cap=6)
    for edge in edges:
        edge["nominated_by"] = sorted(edge["nominated_by"])
    edges.sort(key=lambda edge: (edge["from"], edge["to"]))
    report["survived"] = len(edges)

    graph = {
        "built_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "nominators": models,
        "gates_version": 1,
        "gate_report": report,
        "format_failures": format_failures,
        "timing": {
            "llm_calls": timing["llm_calls"],
            "total_llm_seconds": round(timing["total_llm_seconds"], 3),
            "avg_llm_seconds": round(
                timing["total_llm_seconds"] / timing["llm_calls"], 3
            )
            if timing["llm_calls"]
            else 0.0,
        },
        "edges": edges,
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)
    return graph


def main():
    parser = argparse.ArgumentParser(description="建立 ISO 27001 Knowledge Graph")
    parser.add_argument("--structure-path", default=str(DEFAULT_STRUCTURE_PATH))
    parser.add_argument("--embeddings-path", default=str(DEFAULT_EMBEDDINGS_PATH))
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--sample", type=int)
    parser.add_argument("--extract-gold", action="store_true")
    parser.add_argument("--from-pdca", action="store_true", help="直接從 pdca_graph.json 建立圖譜")
    parser.add_argument("--pdca-path", default=None, help="pdca_graph.json 的路徑")
    args = parser.parse_args()

    if args.extract_gold:
        from scripts.eval_nominator import extract_gold_edges

        output = extract_gold_edges(structure_path=args.structure_path)
        print(f"✅ 黃金邊抽取完成：{len(output['edges'])} 條")
        return

    graph = run_kg_pipeline(
        structure_path=args.structure_path,
        embeddings_path=args.embeddings_path,
        output_path=args.output_path,
        models=[model.strip() for model in args.models.split(",") if model.strip()],
        rounds=args.rounds,
        host=args.host,
        checkpoint_dir=DEFAULT_CHECKPOINT_DIR,
        sample=args.sample,
        from_pdca=args.from_pdca,
        pdca_path=args.pdca_path,
    )
    print(f"✅ KG 建置完成：{graph['gate_report']}")
    if graph.get("timing"):
        print(f"⏱️  LLM 呼叫耗時：{graph['timing']}")



if __name__ == "__main__":
    main()
